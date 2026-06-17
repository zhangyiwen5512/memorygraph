"""IRExtractor——将 tree-sitter AST 转为统一 IR 的 Symbol + Edge。"""
from __future__ import annotations

import hashlib

from tree_sitter import Language, Node, Query, QueryCursor, Tree

from memorygraph.parsing.ir import (
    Edge,
    EdgeKind,
    FileInfo,
    ParseResult,
    Span,
    Symbol,
    SymbolKind,
)

# Module-level caches for compiled Query objects.
# Key: (language_name, query_string) — safe because Query objects are
# deterministic for a given grammar and can be reused across Language
# instances for the same language.
_QUERY_CACHE: dict[tuple[str, str], Query] = {}
_ERROR_QUERY_CACHE: dict[str, Query] = {}  # language_name → (ERROR) query


def _get_cached_query(
    lang_obj: Language, query_string: str, language_name: str,
) -> Query:
    """Return a cached compiled Query, or compile and cache on first use."""
    cache_key = (language_name, query_string)
    cached = _QUERY_CACHE.get(cache_key)
    if cached is not None:
        return cached
    query = Query(lang_obj, query_string)
    _QUERY_CACHE[cache_key] = query
    return query


def _get_cached_error_query(lang_obj: Language, language_name: str) -> Query:
    """Return a cached (ERROR) @error Query."""
    cached = _ERROR_QUERY_CACHE.get(language_name)
    if cached is not None:
        return cached  # pragma: no cover — cache hit, only on 2nd+ call per language
    query = Query(lang_obj, "(ERROR) @error")  # type: ignore[attr-defined]
    _ERROR_QUERY_CACHE[language_name] = query  # pragma: no cover — coverage.py quirk, line above is covered
    return query  # pragma: no cover — same quirk, Query assignment always sets query


class IRExtractor:
    """提取器基类——子类提供 query 字符串和钩子方法。"""

    @property
    def symbol_queries(self) -> dict[SymbolKind, str]:
        raise NotImplementedError

    @property
    def edge_queries(self) -> dict[EdgeKind, str]:
        raise NotImplementedError

    def extract_signature(self, node: Node, kind: SymbolKind, source: bytes) -> str | None:
        """从源码字节中提取签名文本。默认：取从节点起始到第一行结束。"""
        start = node.start_byte
        end = node.end_byte
        text = source[start:end].decode("utf-8", errors="replace")
        newline = text.find("\n")
        if newline != -1:
            text = text[:newline]
        return text.strip()

    @staticmethod
    def _decode_node_text(node: Node) -> str | None:
        """Safely decode tree-sitter node text, handling None and IndexError."""
        try:
            text = node.text
        except IndexError:
            return None
        if text is None:
            return None
        return text.decode("utf-8", errors="replace")

    def resolve_parent_symbol(self, node: Node, tree: Tree) -> str | None:
        """向上遍历 AST，找到最近的类/接口定义。"""
        cursor: Node | None = node
        while cursor is not None:
            if cursor.type in self._parent_node_types():
                name_node = cursor.child_by_field_name("name")
                if name_node is not None:
                    return self._decode_node_text(name_node)
            cursor = cursor.parent
        return None

    def _parent_node_types(self) -> list[str]:
        """包含 parent 关系的节点类型名。子类可覆盖。"""
        return ["class_definition", "class_declaration"]

    def extract(
        self, file_path: str, tree: Tree, source_bytes: bytes, language: str
    ) -> ParseResult:
        """模板方法：运行合并 query（单次 tree walk）→ 构造 Symbol + Edge → 后处理。"""
        lang_obj = tree.language
        file_info = FileInfo(
            path=file_path,
            language=language,
            content_hash=hashlib.sha256(source_bytes).hexdigest(),
        )
        symbols: list[Symbol] = []
        edges: list[Edge] = []
        errors: list[str] = []

        self._extract_symbols(tree, lang_obj, language, source_bytes, file_path, symbols, errors)
        self._mark_methods(symbols)
        self._extract_edges(tree, lang_obj, language, source_bytes, file_path, edges, errors)

        return ParseResult(file=file_info, symbols=symbols, edges=edges, errors=errors)

    def _extract_symbols(
        self, tree: Tree, lang_obj, language: str, source_bytes: bytes,
        file_path: str, symbols: list[Symbol], errors: list[str],
    ) -> None:
        """Extract all symbols from tree via combined query (with per-kind fallback)."""
        symbol_kinds = list(self.symbol_queries.keys())
        if not symbol_kinds:
            return

        combined_query_str = "\n".join(self.symbol_queries.values())
        try:
            query = _get_cached_query(lang_obj, combined_query_str, language)
            cursor = QueryCursor(query)
            seen_names: set[str] = set()
            for pattern_idx, captures in cursor.matches(tree.root_node):
                if pattern_idx >= len(symbol_kinds):
                    continue  # pragma: no cover — defensive, pattern_idx always in bounds
                kind = symbol_kinds[pattern_idx]
                name_nodes = captures.get("name", [])
                def_nodes = captures.get("def", name_nodes)
                node = def_nodes[0] if def_nodes else None
                if node is None:
                    continue
                name = self._extract_name(node, source_bytes)
                if name is None or name in seen_names:
                    continue
                seen_names.add(name)
                self._make_symbol(node, kind, source_bytes, file_path, tree, language, lang_obj,
                                  symbols, errors)
        except Exception:  # pragma: no cover — fallback for malformed queries
            for kind, query_str in self.symbol_queries.items():
                try:
                    query = _get_cached_query(lang_obj, query_str, language)
                    cursor = QueryCursor(query)
                    fb_seen_names: set[str] = set()
                    for _, captures in cursor.matches(tree.root_node):
                        name_nodes = captures.get("name", [])
                        def_nodes = captures.get("def", name_nodes)
                        node = def_nodes[0] if def_nodes else None
                        if node is None:
                            continue
                        name = self._extract_name(node, source_bytes)
                        if name is None or name in fb_seen_names:
                            continue
                        fb_seen_names.add(name)
                        self._make_symbol(node, kind, source_bytes, file_path, tree,
                                          language, lang_obj, symbols, errors)
                except Exception as e:
                    errors.append(f"Query failed for symbol {kind.value}: {e}")

    def _make_symbol(
        self, node, kind: SymbolKind, source_bytes: bytes, file_path: str,
        tree: Tree, language: str, lang_obj, symbols: list[Symbol], errors: list[str],
    ) -> None:
        """Construct and append a Symbol from a matched capture node."""
        span = self._node_span(file_path, node)
        signature = self.extract_signature(node, kind, source_bytes)
        parent = self.resolve_parent_symbol(node, tree)
        is_partial = self._has_error_node(node, language, lang_obj)
        symbols.append(Symbol(
            name=self._extract_name(node, source_bytes) or "?",
            kind=kind,
            span=span,
            parent_symbol=parent,
            signature=signature,
            is_partial=is_partial,
        ))
        if is_partial:
            errors.append(f"Partial parse for {kind.value} '{symbols[-1].name}'")

    def _extract_edges(
        self, tree: Tree, lang_obj, language: str, source_bytes: bytes,
        file_path: str, edges: list[Edge], errors: list[str],
    ) -> None:
        """Extract all edges from tree via combined query (with per-kind fallback)."""
        edge_kinds = list(self.edge_queries.keys())
        if not edge_kinds:
            return

        combined_edge_query = "\n".join(self.edge_queries.values())
        try:
            query = _get_cached_query(lang_obj, combined_edge_query, language)
            cursor = QueryCursor(query)
            for pattern_idx, captures in cursor.matches(tree.root_node):
                if pattern_idx >= len(edge_kinds):
                    continue
                ekind = edge_kinds[pattern_idx]
                call_nodes = captures.get("call", [])
                target_nodes = captures.get("target", [])
                node = call_nodes[0] if call_nodes else None
                tgt_node = target_nodes[0] if target_nodes else None
                if node is None or tgt_node is None:
                    continue
                src_name = self._extract_source_for_edge(node, ekind, source_bytes)
                tgt_name = self._extract_target_for_edge(tgt_node, ekind, source_bytes)
                if tgt_name is None or src_name is None:
                    continue
                edges.append(Edge(
                    source=src_name,
                    target=tgt_name,
                    kind=ekind,
                    source_span=self._node_span(file_path, node),
                ))
        except Exception:  # pragma: no cover — fallback for malformed edge queries
            for ekind, query_str in self.edge_queries.items():
                try:
                    query = _get_cached_query(lang_obj, query_str, language)
                    cursor = QueryCursor(query)
                    for _, captures in cursor.matches(tree.root_node):
                        call_nodes = captures.get("call", [])
                        target_nodes = captures.get("target", [])
                        node = call_nodes[0] if call_nodes else None
                        tgt_node = target_nodes[0] if target_nodes else None
                        if node is None or tgt_node is None:
                            continue
                        src_name = self._extract_source_for_edge(node, ekind, source_bytes)
                        tgt_name = self._extract_target_for_edge(tgt_node, ekind, source_bytes)
                        if tgt_name is None or src_name is None:
                            continue
                        edges.append(Edge(
                            source=src_name,
                            target=tgt_name,
                            kind=ekind,
                            source_span=self._node_span(file_path, node),
                        ))
                except Exception as e:
                    errors.append(f"Query failed for edge {ekind.value}: {e}")

    def _mark_methods(self, symbols: list[Symbol]) -> None:
        """将父节点是 class 的 function 标记为 METHOD。"""
        class_names = {s.name for s in symbols if s.kind == SymbolKind.CLASS}
        for sym in symbols:
            if (
                sym.kind == SymbolKind.FUNCTION
                and sym.parent_symbol
                and sym.parent_symbol in class_names
            ):
                sym.kind = SymbolKind.METHOD

    def _extract_name(self, node: Node, source: bytes) -> str | None:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return self._decode_node_text(name_node)
        if node.type == "identifier":
            return self._decode_node_text(node)
        return None

    def _extract_source_for_edge(
        self, node: Node, kind: EdgeKind, source: bytes
    ) -> str | None:
        """Extract the source symbol name for an edge.

        For CALLS edges: walking up to nearest enclosing function.
        For structural edges (IMPORTS, EXTENDS, etc.): walking up to nearest
        class/interface, or returning '<module_level>' for top-level edges.
        """
        if kind != EdgeKind.CALLS:
            cursor: Node | None = node
            while cursor is not None:
                if cursor.type in self._parent_node_types():
                    name_node = cursor.child_by_field_name("name")
                    if name_node is not None:
                        return self._decode_node_text(name_node)
                    for child in cursor.children:
                        if child.type in ("identifier", "type_identifier",
                                          "property_identifier"):
                            return self._decode_node_text(child)
                cursor = cursor.parent
            return "<module_level>"

        # Original CALLS logic
        call_cursor: Node | None = node
        while call_cursor is not None:
            if call_cursor.type in (
                "function_definition", "function_declaration",
                "method_definition", "method_declaration",
                "arrow_function", "function_expression",
            ):
                name_node = call_cursor.child_by_field_name("name")
                if name_node is not None:
                    return self._decode_node_text(name_node)
                return "<anonymous>"
            call_cursor = call_cursor.parent
        return "<module_level>"

    def _extract_target_for_edge(
        self, node: Node, kind: EdgeKind, source: bytes
    ) -> str | None:
        """提取边的目标符号名。"""
        if kind == EdgeKind.CALLS:
            func_node = node.child_by_field_name("function")
            if func_node is not None:
                return self._decode_node_text(func_node)
            # Fallback: 取第一个 identifier
            for child in node.children:
                if child.type == "identifier":
                    return self._decode_node_text(child)
                if child.type == "attribute":
                    return self._decode_node_text(child)
            text = self._decode_node_text(node)
            if text:
                return text.split("(")[0].strip()
            return None
        # For non-CALLS edges (IMPORTS, EXTENDS, etc.), use direct text
        return self._decode_node_text(node)

    def _node_span(self, file_path: str, node: Node) -> Span:
        return Span(
            file=file_path,
            start_line=node.start_point[0],
            start_col=node.start_point[1],
            end_line=node.end_point[0],
            end_col=node.end_point[1],
        )

    def _has_error_node(self, node: Node, language: str = "", lang_obj: Language | None = None) -> bool:
        """Check if tree contains ERROR nodes using tree-sitter query (O(matches) vs O(nodes)).

        Uses a module-level cache for the (ERROR) @error query per language.
        When lang_obj is provided, uses it directly (tree-sitter Node has no .language attr).
        """
        try:
            if lang_obj is not None:
                query = _get_cached_error_query(lang_obj, language)
            else:
                query = _get_cached_error_query(node.language, language)  # type: ignore[attr-defined]  # pragma: no cover — fallback for tree-sitter versions with node.language
            cursor = QueryCursor(query)
            for _ in cursor.matches(node):
                return True
            return False
        except Exception:  # pragma: no cover — fallback for unusual node types
            if node.type == "ERROR":
                return True
            return any(self._has_error_node(child, language) for child in node.children)


class PythonExtractor(IRExtractor):
    """Python 语言的 IRExtractor。"""

    @property
    def symbol_queries(self) -> dict[SymbolKind, str]:
        return {
            SymbolKind.FUNCTION: """
                (function_definition
                  name: (identifier) @name
                ) @def
            """,
            SymbolKind.CLASS: """
                (class_definition
                  name: (identifier) @name
                ) @def
            """,
            SymbolKind.VARIABLE: """
                (module
                  (expression_statement
                    (assignment
                      left: (identifier) @name
                    )
                  )
                )
            """,
        }

    @property
    def edge_queries(self) -> dict[EdgeKind, str]:
        return {
            EdgeKind.CALLS: """
                (call
                  function: [
                    (identifier) @target
                    (attribute) @target
                  ]
                ) @call
            """,
            EdgeKind.IMPORTS: """
                (import_statement
                  name: (dotted_name
                    (identifier) @target
                  )
                ) @call
                (import_from_statement
                  module_name: (dotted_name
                    (identifier) @target
                  )
                ) @call
            """,
            EdgeKind.EXTENDS: """
                (class_definition
                  superclasses: (argument_list
                    (identifier) @target
                  )
                ) @call
            """,
        }

    def _parent_node_types(self) -> list[str]:
        return ["class_definition"]

    def resolve_parent_symbol(self, node: Node, tree: Tree) -> str | None:
        """对 Python function_definition，检查是否位于 class_definition 内部。"""
        cursor = node.parent
        while cursor is not None:
            if cursor.type == "class_definition":
                name_node = cursor.child_by_field_name("name")
                if name_node is not None:
                    return self._decode_node_text(name_node)
            cursor = cursor.parent
        return None


class TypeScriptExtractor(IRExtractor):
    """TypeScript 语言的 IRExtractor。"""

    @property
    def symbol_queries(self) -> dict[SymbolKind, str]:
        return {
            SymbolKind.FUNCTION: """
                (function_declaration
                  name: (identifier) @name
                ) @def
            """,
            SymbolKind.METHOD: """
                (method_definition
                  name: (property_identifier) @name
                ) @def
            """,
            SymbolKind.CLASS: """
                (class_declaration
                  name: (type_identifier) @name
                ) @def
            """,
            SymbolKind.INTERFACE: """
                (interface_declaration
                  name: (type_identifier) @name
                ) @def
            """,
            SymbolKind.TYPE_ALIAS: """
                (type_alias_declaration
                  name: (type_identifier) @name
                ) @def
            """,
            SymbolKind.VARIABLE: """
                (variable_declarator
                  name: (identifier) @name
                ) @def
            """,
        }

    @property
    def edge_queries(self) -> dict[EdgeKind, str]:
        return {
            EdgeKind.CALLS: """
                (call_expression
                  function: (identifier) @target
                ) @call
            """,
            EdgeKind.IMPORTS: """
                (import_statement
                  source: (string) @target
                ) @call
            """,
            EdgeKind.EXTENDS: """
                (class_declaration
                  (class_heritage
                    (extends_clause value: (type_identifier) @target)
                  )
                ) @call
            """,
            EdgeKind.IMPLEMENTS: """
                (class_declaration
                  (class_heritage
                    (implements_clause value: (type_identifier) @target)
                  )
                ) @call
            """,
        }

    def _parent_node_types(self) -> list[str]:
        return ["class_declaration", "interface_declaration"]


class JavaScriptExtractor(TypeScriptExtractor):
    """JavaScript 使用 TypeScript 的语法树，复用相同的 query。"""
    pass


class GoExtractor(IRExtractor):
    """Go 语言的 IRExtractor。"""

    @property
    def symbol_queries(self) -> dict[SymbolKind, str]:
        return {
            SymbolKind.FUNCTION: """
                (function_declaration
                  name: (identifier) @name
                ) @def
            """,
            SymbolKind.METHOD: """
                (method_declaration
                  name: (field_identifier) @name
                ) @def
            """,
            SymbolKind.CLASS: """
                (type_declaration
                  (type_spec
                    name: (type_identifier) @name
                    type: (struct_type)
                  ) @def
                )
            """,
            SymbolKind.INTERFACE: """
                (type_declaration
                  (type_spec
                    name: (type_identifier) @name
                    type: (interface_type)
                  ) @def
                )
            """,
            SymbolKind.VARIABLE: """
                (var_declaration
                  (var_spec
                    name: (identifier) @name
                  )
                )
                (const_declaration
                  (const_spec
                    name: (identifier) @name
                  )
                )
            """,
        }

    @property
    def edge_queries(self) -> dict[EdgeKind, str]:
        return {
            EdgeKind.CALLS: """
                (call_expression
                  function: [
                    (identifier) @target
                    (selector_expression
                      field: (field_identifier) @target
                    )
                  ]
                ) @call
            """,
            EdgeKind.IMPORTS: """
                (import_declaration
                  (import_spec
                    path: (interpreted_string_literal) @target
                  )
                ) @call
            """,
            EdgeKind.TYPE_REFERENCES: """
                (parameter_declaration
                  type: (type_identifier) @target
                ) @call
                (pointer_type
                  (type_identifier) @target
                ) @call
                (field_declaration
                  type: (type_identifier) @target
                ) @call
            """,
        }

    def _parent_node_types(self) -> list[str]:
        return ["type_declaration"]


class RustExtractor(IRExtractor):
    """Rust 语言的 IRExtractor。"""

    @property
    def symbol_queries(self) -> dict[SymbolKind, str]:
        return {
            SymbolKind.FUNCTION: """
                (function_item
                  name: (identifier) @name
                ) @def
            """,
            SymbolKind.CLASS: """
                (struct_item
                  name: (type_identifier) @name
                ) @def
            """,
            SymbolKind.INTERFACE: """
                (trait_item
                  name: (type_identifier) @name
                ) @def
            """,
            SymbolKind.VARIABLE: """
                (const_item
                  name: (identifier) @name
                )
            """,
        }

    @property
    def edge_queries(self) -> dict[EdgeKind, str]:
        return {
            EdgeKind.CALLS: """
                (call_expression
                  function: [
                    (identifier) @target
                    (field_expression
                      field: (field_identifier) @target
                    )
                  ]
                ) @call
            """,
            EdgeKind.IMPORTS: """
                (use_declaration
                  argument: (scoped_identifier
                    name: (identifier) @target
                  )
                ) @call
            """,
            EdgeKind.TYPE_REFERENCES: """
                (function_item
                  parameters: (parameters
                    (parameter
                      type: (type_identifier) @target
                    )
                  )
                ) @call
            """,
        }

    def _parent_node_types(self) -> list[str]:
        return ["struct_item", "trait_item", "impl_item"]


class JavaExtractor(IRExtractor):
    """Java 语言的 IRExtractor。"""

    @property
    def symbol_queries(self) -> dict[SymbolKind, str]:
        return {
            SymbolKind.METHOD: """
                (method_declaration
                  name: (identifier) @name
                ) @def
            """,
            SymbolKind.CLASS: """
                (class_declaration
                  name: (identifier) @name
                ) @def
            """,
            SymbolKind.INTERFACE: """
                (interface_declaration
                  name: (identifier) @name
                ) @def
            """,
        }

    @property
    def edge_queries(self) -> dict[EdgeKind, str]:
        return {
            EdgeKind.CALLS: """
                (method_invocation
                  name: (identifier) @target
                ) @call
            """,
            EdgeKind.IMPORTS: """
                (import_declaration
                  (scoped_identifier
                    (identifier) @target
                  )
                ) @call
            """,
            EdgeKind.EXTENDS: """
                (class_declaration
                  superclass: (type_identifier) @target
                ) @call
            """,
            EdgeKind.IMPLEMENTS: """
                (class_declaration
                  superinterfaces: (type_list
                    (type_identifier) @target
                  )
                ) @call
            """,
            EdgeKind.TYPE_REFERENCES: """
                (formal_parameter
                  type: (type_identifier) @target
                ) @call
                (field_declaration
                  type: (type_identifier) @target
                ) @call
                (local_variable_declaration
                  type: (type_identifier) @target
                ) @call
            """,
        }

    def _parent_node_types(self) -> list[str]:
        return ["class_declaration", "interface_declaration"]


class CSharpExtractor(IRExtractor):
    """C# 语言的 IRExtractor。"""

    @property
    def symbol_queries(self) -> dict[SymbolKind, str]:
        return {
            SymbolKind.METHOD: """
                (method_declaration
                  name: (identifier) @name
                ) @def
            """,
            SymbolKind.CLASS: """
                (class_declaration
                  name: (identifier) @name
                ) @def
            """,
            SymbolKind.INTERFACE: """
                (interface_declaration
                  name: (identifier) @name
                ) @def
            """,
        }

    @property
    def edge_queries(self) -> dict[EdgeKind, str]:
        return {
            EdgeKind.CALLS: """
                (invocation_expression
                  function: (identifier) @target
                ) @call
            """,
            EdgeKind.IMPORTS: """
                (using_directive
                  (identifier) @target
                ) @call
                (using_directive
                  (qualified_name
                    (identifier) @target
                  )
                ) @call
            """,
            EdgeKind.EXTENDS: """
                (class_declaration
                  (base_list
                    (identifier) @target
                  )
                ) @call
            """,
            EdgeKind.IMPLEMENTS: """
                (class_declaration
                  (base_list
                    (identifier) @target
                  )
                ) @call
            """,
            EdgeKind.TYPE_REFERENCES: """
                (parameter
                  type: (identifier) @target
                ) @call
                (variable_declaration
                  type: (identifier) @target
                ) @call
                (declaration_expression
                  type: (identifier) @target
                ) @call
            """,
        }

    def _parent_node_types(self) -> list[str]:
        return ["class_declaration", "interface_declaration"]
