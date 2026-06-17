"""Tests for Python IRExtractor."""
import os

import pytest

from memorygraph.parsing.detector import LanguageDetector
from memorygraph.parsing.extractor import IRExtractor, PythonExtractor
from memorygraph.parsing.ir import EdgeKind, SymbolKind
from memorygraph.parsing.registry import LanguageRegistry
from memorygraph.parsing.ts_parser import TreeSitterParser

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


# === Module-scoped fixtures — created once, shared across all tests ===
# This avoids repeated tree-sitter grammar loading (.so) and CST building
# which are the dominant memory consumers in this test file.

@pytest.fixture(scope="module")
def registry():
    """Module-scoped: LanguageRegistry with class-level grammar cache."""
    return LanguageRegistry()


@pytest.fixture(scope="module")
def parser(registry):
    """Module-scoped: TreeSitterParser with cached parser per language."""
    return TreeSitterParser(registry)


@pytest.fixture(scope="module")
def detector(registry):
    """Module-scoped: LanguageDetector."""
    return LanguageDetector(registry)


@pytest.fixture(scope="module")
def sample_path():
    """Module-scoped: path to sample.py fixture."""
    return os.path.join(FIXTURE_DIR, "sample.py")


@pytest.fixture(scope="module")
def sample_parse_result(registry, parser, detector, sample_path):
    """Module-scoped: parse sample.py once, share (file_path, tree, source_bytes, config).

    This is the biggest memory win — instead of each test independently
    reading the file and building a tree-sitter CST (~13 times before),
    we do it once and share the immutable tree across all readers.
    """
    config = detector.detect(sample_path)
    tree, source_bytes = parser.parse(sample_path, config)
    return sample_path, tree, source_bytes, config


# === IRExtractor base class tests (lightweight, mock-only — no changes needed) ===


class TestIRExtractorBase:
    """Tests for IRExtractor base class abstract methods."""

    def test_symbol_queries_not_implemented(self):
        """IRExtractor.symbol_queries raises NotImplementedError."""
        class IncompleteExtractor(IRExtractor):
            pass
        ext = IncompleteExtractor()
        with pytest.raises(NotImplementedError):
            _ = ext.symbol_queries

    def test_edge_queries_not_implemented(self):
        """IRExtractor.edge_queries raises NotImplementedError."""
        class IncompleteExtractor(IRExtractor):
            pass
        ext = IncompleteExtractor()
        with pytest.raises(NotImplementedError):
            _ = ext.edge_queries

    def test_default_parent_node_types(self):
        """Default _parent_node_types returns class_definition, class_declaration."""
        class MinimalExtractor(IRExtractor):
            @property
            def symbol_queries(self):
                return {}
            @property
            def edge_queries(self):
                return {}
        ext = MinimalExtractor()
        types = ext._parent_node_types()
        assert "class_definition" in types
        assert "class_declaration" in types


# === _has_error_node tests (lightweight, mock-only — no changes needed) ===


class TestHasErrorNode:
    """Tests for _has_error_node method."""

    def test_has_error_node_direct(self):
        """_has_error_node returns True when node itself is ERROR type."""
        from unittest import mock
        extractor = PythonExtractor()
        mock_node = mock.MagicMock()
        mock_node.type = "ERROR"
        assert extractor._has_error_node(mock_node) is True

    def test_has_error_node_in_child(self):
        """_has_error_node returns True when a child has ERROR type."""
        from unittest import mock
        extractor = PythonExtractor()
        child_node = mock.MagicMock()
        child_node.type = "ERROR"
        parent_node = mock.MagicMock()
        parent_node.type = "expression"
        parent_node.children = [child_node]
        assert extractor._has_error_node(parent_node) is True

    def test_has_error_node_no_errors(self):
        """_has_error_node returns False when no ERROR nodes exist."""
        from unittest import mock
        extractor = PythonExtractor()
        child = mock.MagicMock()
        child.type = "identifier"
        child.children = []
        parent = mock.MagicMock()
        parent.type = "function_definition"
        parent.children = [child]
        assert extractor._has_error_node(parent) is False


# === _extract_source_for_edge tests (lightweight, mock-only) ===


class TestExtractSourceForEdge:
    """Tests for _extract_source_for_edge method."""

    def test_anonymous_function_source(self):
        """CALLS edge on function without name returns '<anonymous>'."""
        from unittest import mock
        extractor = PythonExtractor()
        mock_node = mock.MagicMock()
        mock_node.type = "function_definition"
        mock_node.child_by_field_name.return_value = None  # no name
        mock_node.parent = None
        result = extractor._extract_source_for_edge(mock_node, EdgeKind.CALLS, b"")
        assert result == "<anonymous>"

    def test_structural_edge_class_source(self):
        """Non-CALLS edge walks up to find enclosing class name."""
        from unittest import mock
        extractor = PythonExtractor()
        inner_node = mock.MagicMock()
        inner_node.type = "identifier"
        class_node = mock.MagicMock()
        class_node.type = "class_definition"
        name_mock = mock.MagicMock()
        name_mock.text.decode.return_value = "MyClass"
        class_node.child_by_field_name.return_value = name_mock
        class_node.parent = None
        inner_node.parent = class_node
        result = extractor._extract_source_for_edge(inner_node, EdgeKind.IMPLEMENTS, b"")
        assert result == "MyClass"

    def test_structural_edge_fallback_to_identifier(self):
        """Non-CALLS edge falls back to identifier child when name field missing."""
        from unittest import mock
        extractor = PythonExtractor()
        inner_node = mock.MagicMock()
        inner_node.type = "identifier"
        class_node = mock.MagicMock()
        class_node.type = "class_definition"
        class_node.child_by_field_name.return_value = None
        id_child = mock.MagicMock()
        id_child.type = "identifier"
        id_child.text.decode.return_value = "MyClass"
        class_node.children = [id_child]
        class_node.parent = None
        inner_node.parent = class_node
        result = extractor._extract_source_for_edge(inner_node, EdgeKind.EXTENDS, b"")
        assert result == "MyClass"


# === _decode_node_text tests (lightweight, mock-only) ===


class TestDecodeNodeText:
    """Cover _decode_node_text lines 45-46 (IndexError), 48 (None text)."""

    def test_decode_node_text_index_error(self):
        """_decode_node_text returns None when node.text raises IndexError."""
        from unittest import mock

        from memorygraph.parsing.extractor import PythonExtractor
        extractor = PythonExtractor()
        mock_node = mock.MagicMock()
        # Setting text as a property that raises IndexError
        type(mock_node).text = mock.PropertyMock(side_effect=IndexError)
        result = extractor._decode_node_text(mock_node)
        assert result is None

    def test_decode_node_text_none_text(self):
        """_decode_node_text returns None when node.text is None."""
        from unittest import mock

        from memorygraph.parsing.extractor import PythonExtractor
        extractor = PythonExtractor()
        mock_node = mock.MagicMock()
        type(mock_node).text = mock.PropertyMock(return_value=None)
        result = extractor._decode_node_text(mock_node)
        assert result is None


# === _extract_target_for_edge tests (lightweight, mock-only) ===


class TestExtractTargetForEdge:
    """Tests for _extract_target_for_edge method."""

    def test_calls_target_by_function_field(self):
        """CALLS target extracts function name via 'function' child field."""
        from unittest import mock
        extractor = PythonExtractor()
        mock_node = mock.MagicMock()
        func_mock = mock.MagicMock()
        func_mock.text.decode.return_value = "target_func"
        mock_node.child_by_field_name.return_value = func_mock
        mock_node.children = []
        result = extractor._extract_target_for_edge(mock_node, EdgeKind.CALLS, b"")
        assert result == "target_func"

    def test_calls_target_fallback_to_text(self):
        """CALLS target falls back to text before '(' when no function field or identifier."""
        from unittest import mock
        extractor = PythonExtractor()
        mock_node = mock.MagicMock()
        mock_node.child_by_field_name.return_value = None
        mock_node.children = []
        mock_node.text.decode.return_value = "some_call(arg1, arg2)"
        result = extractor._extract_target_for_edge(mock_node, EdgeKind.CALLS, b"")
        assert result == "some_call"

    def test_non_calls_target_uses_direct_text(self):
        """Non-CALLS edge target uses direct node text (e.g., IMPORTS)."""
        from unittest import mock
        extractor = PythonExtractor()
        mock_node = mock.MagicMock()
        mock_node.text = b"some_module"
        result = extractor._extract_target_for_edge(mock_node, EdgeKind.IMPORTS, b"")
        assert result == "some_module"

    def test_calls_target_fallback_to_identifier(self):
        """CALLS target: fallback to identifier child when no function field."""
        from unittest import mock
        extractor = PythonExtractor()
        mock_node = mock.MagicMock()
        mock_node.child_by_field_name.return_value = None
        ident_child = mock.MagicMock()
        ident_child.type = "identifier"
        ident_child.text.decode.return_value = "fallback_func"
        mock_node.children = [ident_child]
        result = extractor._extract_target_for_edge(mock_node, EdgeKind.CALLS, b"")
        assert result == "fallback_func"

    def test_calls_target_fallback_to_attribute(self):
        """CALLS target: fallback to attribute child when no function field."""
        from unittest import mock
        extractor = PythonExtractor()
        mock_node = mock.MagicMock()
        mock_node.child_by_field_name.return_value = None
        attr_child = mock.MagicMock()
        attr_child.type = "attribute"
        attr_child.text.decode.return_value = "obj.method"
        mock_node.children = [attr_child]
        result = extractor._extract_target_for_edge(mock_node, EdgeKind.CALLS, b"")
        assert result == "obj.method"

    def test_calls_target_empty_text_returns_none(self):
        """CALLS target returns None when text is empty (cover line 222)."""
        from unittest import mock
        extractor = PythonExtractor()
        mock_node = mock.MagicMock()
        mock_node.child_by_field_name.return_value = None
        mock_node.children = []
        with mock.patch.object(extractor, "_decode_node_text", return_value=""):
            result = extractor._extract_target_for_edge(mock_node, EdgeKind.CALLS, b"")
        assert result is None


# === extract() error handling tests (use shared fixtures) ===


class TestExtractExceptionPaths:
    """Cover extract() lines 90-92 (query exception)."""

    def test_symbol_query_exception(self):
        """extract catches exception from symbol query and adds to errors."""
        from unittest import mock

        from memorygraph.parsing.ir import SymbolKind

        class BadExtractor(PythonExtractor):
            @property
            def symbol_queries(self):
                return {SymbolKind.FUNCTION: "(bad_query"}

        extractor = BadExtractor()
        mock_tree = mock.MagicMock()
        mock_tree.language = mock.MagicMock()

        result = extractor.extract("/test.py", mock_tree, b"def foo(): pass", "python")
        assert len(result.errors) > 0
        assert any("Query failed" in e for e in result.errors)

    def test_partial_parse_appends_error(self, sample_parse_result):
        """extract appends error when is_partial is True (cover line 90)."""
        from unittest import mock

        file_path, tree, source_bytes, config = sample_parse_result
        extractor = PythonExtractor()

        with mock.patch.object(extractor, "_has_error_node", return_value=True):
            result = extractor.extract(file_path, tree, source_bytes, config.name)
            assert any("Partial parse" in e for e in result.errors)
            assert any(s.is_partial for s in result.symbols)

    def test_edge_query_exception_fallback(self):
        """extract catches exception from edge query and falls back to per-kind."""
        from unittest import mock

        from memorygraph.parsing.ir import EdgeKind

        class BadEdgeExtractor(PythonExtractor):
            @property
            def edge_queries(self):
                return {EdgeKind.CALLS: "(bad_edge_query"}

        extractor = BadEdgeExtractor()
        mock_tree = mock.MagicMock()
        mock_tree.language = mock.MagicMock()

        result = extractor.extract("/test.py", mock_tree, b"def foo(): pass", "python")
        assert len(result.errors) > 0
        assert any("Query failed for edge" in e for e in result.errors)

    def test_has_error_node_fallback_recursive(self):
        """_has_error_node falls back to recursive check when query fails."""
        from unittest import mock
        extractor = PythonExtractor()

        # Mock node without .language to trigger query fallback
        mock_node = mock.MagicMock(spec=[])
        mock_node.type = "ERROR"
        mock_node.children = []
        # .language is not defined → Query(node.language, ...) raises AttributeError
        # → fallback checks type == "ERROR" → True

        assert extractor._has_error_node(mock_node) is True

        # Normal node (no error) → fallback returns False
        mock_ok = mock.MagicMock(spec=[])
        mock_ok.type = "identifier"
        mock_ok.children = []
        assert extractor._has_error_node(mock_ok) is False


# === Edge extraction None-guard tests (use shared fixtures) ===


class TestExtractEdgeNoneGuards:
    """Cover extract() lines 107-108, 111-112 (edge None guards)."""

    def test_edge_extraction_skips_missing_call_node(self):
        """Edge extraction continues when call_nodes capture list is empty."""
        from unittest import mock

        from memorygraph.parsing.ir import EdgeKind

        class EdgeTestExtractor(PythonExtractor):
            @property
            def symbol_queries(self):
                return {}

            @property
            def edge_queries(self):
                return {EdgeKind.CALLS: "(call) @call"}

        extractor = EdgeTestExtractor()
        mock_tree = mock.MagicMock()
        mock_tree.language = mock.MagicMock()
        mock_tree.root_node = mock.MagicMock()

        result = extractor.extract("/test.py", mock_tree, b"", "python")
        assert len(result.edges) == 0

    def test_edge_extraction_skips_missing_target_node(self):
        """Edge extraction continues when target_nodes capture list is empty."""
        from unittest import mock

        from memorygraph.parsing.ir import EdgeKind

        class EdgeTargetTestExtractor(PythonExtractor):
            @property
            def symbol_queries(self):
                return {}

            @property
            def edge_queries(self):
                return {EdgeKind.CALLS: "(call) @call"}

        extractor = EdgeTargetTestExtractor()
        mock_tree = mock.MagicMock()
        mock_tree.language = mock.MagicMock()

        result = extractor.extract("/test.py", mock_tree, b"", "python")
        assert len(result.edges) == 0

    def test_edge_extraction_skips_when_src_name_none(self, sample_parse_result):
        """Edge extraction continues when _extract_source_for_edge returns None (line 111-112)."""
        from unittest import mock

        file_path, tree, source_bytes, config = sample_parse_result
        extractor = PythonExtractor()
        with mock.patch.object(extractor, "_extract_source_for_edge", return_value=None):
            result = extractor.extract(file_path, tree, source_bytes, config.name)
            assert len(result.edges) == 0

    def test_edge_extraction_from_real_file_with_calls(self, sample_parse_result):
        """Edge extraction from a real Python file with function calls."""
        file_path, tree, source_bytes, config = sample_parse_result
        extractor = PythonExtractor()
        result = extractor.extract(file_path, tree, source_bytes, config.name)
        call_edges = [e for e in result.edges if e.kind == EdgeKind.CALLS]
        assert len(call_edges) > 0

    def test_edge_extraction_skips_when_tgt_name_none(self, sample_parse_result):
        """Edge extraction continues when _extract_target_for_edge returns None (cover line 133)."""
        from unittest import mock

        file_path, tree, source_bytes, config = sample_parse_result
        extractor = PythonExtractor()
        with mock.patch.object(extractor, "_extract_target_for_edge", return_value=None):
            result = extractor.extract(file_path, tree, source_bytes, config.name)
            assert len(result.edges) == 0


# === Symbol extraction continue-guard tests (use shared fixtures) ===


class TestExtractSymbolContinueGuards:
    """Cover extract() line 72 (continue when def/node is None)."""

    def test_extract_symbols_continues_on_missing_name(self, sample_parse_result):
        """_extract_symbols continues when _extract_name returns None (line 74-75)."""
        from unittest import mock

        file_path, tree, source_bytes, config = sample_parse_result
        extractor = PythonExtractor()

        with mock.patch.object(extractor, "_extract_name", return_value=None):
            result = extractor.extract(file_path, tree, source_bytes, config.name)
            assert len(result.symbols) == 0

    def test_extract_symbols_skips_when_def_none_with_real_cursor(self, sample_parse_result):
        """Trigger the 'if node is None: continue' (line 71-72) via empty captures dict."""
        from unittest import mock

        from memorygraph.parsing.ir import SymbolKind

        file_path, tree, source_bytes, config = sample_parse_result
        extractor = PythonExtractor()

        # Mock cursor yields empty captures for all queries
        # PythonExtractor has 1 patched symbol query + 3 edge queries = 4 iterations
        mock_cursor = mock.MagicMock()
        mock_cursor.matches.side_effect = [
            iter([(0, {})]),   # symbol FUNCTION (patched)
            iter([(0, {})]),   # edge CALLS
            iter([(0, {})]),   # edge IMPORTS
            iter([(0, {})]),   # edge EXTENDS
        ]

        with mock.patch.object(type(extractor), "symbol_queries",
                                new_callable=mock.PropertyMock,
                                return_value={SymbolKind.FUNCTION: "(function_definition name: (identifier) @name)"}):
            with mock.patch("memorygraph.parsing.extractor.QueryCursor", return_value=mock_cursor):
                result = extractor.extract(file_path, tree, source_bytes, config.name)
                assert len(result.symbols) == 0

    def test_edge_extraction_skips_when_call_none_with_real_cursor(self, sample_parse_result):
        """Trigger the 'if node is None or tgt_node is None: continue' (line 107-108).

        Uses shared parse result for the real tree-sitter Language object
        (required by Query compilation), but mocks the cursor with controlled captures.
        """
        from unittest import mock


        file_path, tree, source_bytes, config = sample_parse_result
        extractor = PythonExtractor()

        # Mock nodes MUST have parent=None — otherwise resolve_parent_symbol
        # enters infinite loop: MagicMock.parent → MagicMock, never None
        mock_node = mock.MagicMock()
        mock_node.parent = None

        mock_cursor = mock.MagicMock()
        mock_cursor.matches.side_effect = [
            iter([(0, {"name": [mock_node]})]),  # symbol FUNCTION
            iter([(0, {"name": [mock_node]})]),  # symbol CLASS
            iter([(0, {})]),                     # symbol VARIABLE (empty)
            iter([(0, {})]),                     # edge CALLS
            iter([(0, {})]),                     # edge IMPORTS
            iter([(0, {})]),                     # edge EXTENDS
        ]

        with mock.patch("memorygraph.parsing.extractor.QueryCursor", return_value=mock_cursor):
            result = extractor.extract(file_path, tree, source_bytes, config.name)
            assert len(result.edges) == 0


# === _extract_name tests (lightweight, mock-only — no changes needed) ===


class TestExtractNameNoneGuard:
    """Cover extract_name line 139 (return None)."""

    def test_extract_name_returns_none_for_non_identifier_nodes(self):
        """_extract_name returns None when node has no name field and is not identifier."""
        from unittest import mock
        extractor = PythonExtractor()
        mock_node = mock.MagicMock()
        mock_node.child_by_field_name.return_value = None
        mock_node.type = "string_literal"
        result = extractor._extract_name(mock_node, b"")
        assert result is None

    def test_extract_name_with_identifier_fallback(self):
        """_extract_name falls back to node text when node type is identifier."""
        from unittest import mock
        extractor = PythonExtractor()
        mock_node = mock.MagicMock()
        mock_node.child_by_field_name.return_value = None
        mock_node.type = "identifier"
        mock_node.text.decode.return_value = "my_var"
        result = extractor._extract_name(mock_node, b"")
        assert result == "my_var"


# === Integration tests with real fixture file (use shared parse result) ===


def test_python_extractor_extracts_functions(sample_parse_result):
    file_path, tree, source_bytes, config = sample_parse_result
    extractor = PythonExtractor()
    result = extractor.extract(file_path, tree, source_bytes, config.name)

    func_names = [s.name for s in result.symbols if s.kind == SymbolKind.FUNCTION]
    assert "greet" in func_names
    assert "main" in func_names


def test_python_extractor_extracts_class(sample_parse_result):
    file_path, tree, source_bytes, config = sample_parse_result
    extractor = PythonExtractor()
    result = extractor.extract(file_path, tree, source_bytes, config.name)

    class_names = [s.name for s in result.symbols if s.kind == SymbolKind.CLASS]
    assert "Calculator" in class_names


def test_python_extractor_extracts_variable(sample_parse_result):
    file_path, tree, source_bytes, config = sample_parse_result
    extractor = PythonExtractor()
    result = extractor.extract(file_path, tree, source_bytes, config.name)

    var_names = [s.name for s in result.symbols if s.kind == SymbolKind.VARIABLE]
    assert "COUNT" in var_names


def test_python_extractor_extracts_methods(sample_parse_result):
    file_path, tree, source_bytes, config = sample_parse_result
    extractor = PythonExtractor()
    result = extractor.extract(file_path, tree, source_bytes, config.name)

    method_names = [s.name for s in result.symbols if s.kind == SymbolKind.METHOD]
    assert "add" in method_names
    assert "multiply" in method_names
    add_sym = next(s for s in result.symbols if s.name == "add")
    assert add_sym.parent_symbol is not None
    assert "Calculator" in add_sym.parent_symbol


def test_python_extractor_extracts_call_edges(sample_parse_result):
    file_path, tree, source_bytes, config = sample_parse_result
    extractor = PythonExtractor()
    result = extractor.extract(file_path, tree, source_bytes, config.name)

    call_edges = [e for e in result.edges if e.kind == EdgeKind.CALLS]
    assert len(call_edges) > 0
    targets = [e.target for e in call_edges]
    assert "greet" in targets or any("greet" in t for t in targets)


def test_python_extractor_produces_non_empty_result(sample_parse_result):
    file_path, tree, source_bytes, config = sample_parse_result
    extractor = PythonExtractor()
    result = extractor.extract(file_path, tree, source_bytes, config.name)

    assert len(result.symbols) > 0
    assert result.fatal_error is None


def test_python_extractor_partial_on_syntax_error(registry, parser, detector):
    """Test extraction with syntax error — uses module-scoped fixtures + temp file."""
    import tempfile
    path = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    )
    path.write("def broken(:\n    pass\n\ndef ok():\n    return 1\n")
    path.close()
    try:
        config = detector.detect(path.name)
        tree, source_bytes = parser.parse(path.name, config)
        extractor = PythonExtractor()
        result = extractor.extract(path.name, tree, source_bytes, config.name)
        func_names = [s.name for s in result.symbols if s.kind == SymbolKind.FUNCTION]
        assert "ok" in func_names
    finally:
        os.unlink(path.name)


def test_extractor_empty_edge_queries_returns_early():
    """_extract_edges with no edge queries returns early (line 193)."""
    import os
    import tempfile

    from memorygraph.parsing.extractor import PythonExtractor
    from memorygraph.parsing.ir import EdgeKind

    class NoEdgeExtractor(PythonExtractor):
        @property
        def edge_queries(self) -> dict[EdgeKind, str]:
            return {}  # empty — triggers early return at line 192-193

    extractor = NoEdgeExtractor()
    import tree_sitter_python as tspy
    from tree_sitter import Language, Parser

    lang = Language(tspy.language())
    parser = Parser(lang)
    source = b"def foo(): pass\n"
    tree = parser.parse(source)

    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        path = f.name
    try:
        result = extractor.extract(path, tree, source, lang)
        # Should extract the function symbol (from parent class queries)
        # but no edges (edge_queries is empty)
        assert len(result.symbols) >= 1
        assert len(result.edges) == 0
    finally:
        os.unlink(path)
