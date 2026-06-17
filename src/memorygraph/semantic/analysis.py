"""Static analysis: complexity, code smells, module role inference."""
import ast
import logging
import re

logger = logging.getLogger(__name__)


def _complexity_rank(score: int) -> str:
    """Convert cyclomatic complexity score to A-F rank."""
    if score <= 5:
        return "A"
    elif score <= 10:
        return "B"
    elif score <= 20:
        return "C"
    elif score <= 30:
        return "D"
    elif score <= 40:
        return "E"
    else:
        return "F"


def analyze_complexity(source: str) -> list[dict]:
    """Return per-function cyclomatic complexity via radon."""
    try:
        from radon.complexity import cc_visit
        blocks = cc_visit(source)
    except Exception:
        logger.warning("radon complexity analysis failed", exc_info=True)
        return []
    return [
        {"name": b.name, "lineno": b.lineno,
         "complexity": b.complexity, "rank": _complexity_rank(b.complexity)}
        for b in blocks
    ]


def analyze_raw(source: str) -> dict:
    """Return raw metrics: LOC, logical LOC, comments, blanks."""
    try:
        from radon.raw import analyze as raw_analyze
        raw = raw_analyze(source)
        return {"loc": raw.loc, "lloc": raw.lloc, "sloc": raw.sloc,
                "comments": raw.comments, "multi": raw.multi, "blank": raw.blank}
    except Exception:
        logger.warning("radon raw analysis failed", exc_info=True)
        return {"loc": 0, "lloc": 0, "sloc": 0, "comments": 0, "multi": 0, "blank": 0}


class SmellDetector:
    """Detect code smells via AST pattern matching.

    Detection is symbol-scoped: god_class only checks methods within a
    specific ClassDef node, long_method checks a specific FunctionDef, etc.
    """

    def detect(self, tree: ast.AST, symbol_name: str,
               callers: list, callees: list,
               _source_lines: list | None = None,
               node_map: dict[str, ast.AST] | None = None) -> list[dict]:
        smells = []

        # Extract the simple name (last component of qualified_name)
        short_name = symbol_name.split(".")[-1] if "." in symbol_name else symbol_name

        # Use caller-provided node_map if available, otherwise build one.
        # Callers that process many symbols against the same tree should
        # build the map once and pass it to avoid O(n*m) AST walks.
        if node_map is None:
            node_map = self._build_node_map(tree)

        # Find the specific AST node for this symbol
        target_node = node_map.get(short_name)

        # If the target is a class, check class-level smells
        if target_node is not None and isinstance(target_node, ast.ClassDef):
            class_methods = [n for n in target_node.body if isinstance(n, ast.FunctionDef)]
            if len(class_methods) > 20:
                smells.append({"rule": "god_class", "symbol": symbol_name,
                              "count": len(class_methods), "severity": "warning"})

        # If the target is a function/method, check function-level smells
        if target_node is not None and isinstance(target_node, ast.FunctionDef):
            body_lines = (target_node.end_lineno or 0) - (target_node.lineno or 0)
            if body_lines > 50:
                smells.append({"rule": "long_method", "symbol": symbol_name,
                              "lines": body_lines, "severity": "info"})

            params = [a for a in target_node.args.args if a.arg != "self"]
            if len(params) > 5:
                smells.append({"rule": "long_parameter_list", "symbol": symbol_name,
                              "count": len(params), "severity": "info"})

            max_depth = self._max_nesting(target_node)
            if max_depth > 4:
                smells.append({"rule": "deep_nesting", "symbol": symbol_name,
                              "depth": max_depth, "severity": "warning"})

            if target_node.name.startswith("_") and len(callers) == 0:
                smells.append({"rule": "dead_code", "symbol": symbol_name,
                              "severity": "info"})

        # Shotgun Surgery: >10 direct callers (symbol-level, doesn't need AST)
        if len(callers) > 10:
            smells.append({"rule": "shotgun_surgery", "symbol": symbol_name,
                          "caller_count": len(callers), "severity": "warning"})

        # Feature Envy: more external calls than internal (symbol-level)
        if callees and callers:
            internal_calls = sum(1 for c in callees if c.get("target", "").startswith(symbol_name))
            external_calls = len(callees) - internal_calls
            if external_calls > internal_calls:
                smells.append({"rule": "feature_envy", "symbol": symbol_name,
                              "external": external_calls, "internal": internal_calls,
                              "severity": "warning"})

        return smells

    def _build_node_map(self, tree: ast.AST) -> dict[str, ast.AST]:
        """Build a name→node map in a single AST walk (O(nodes))."""
        node_map: dict[str, ast.AST] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                node_map[node.name] = node
        return node_map

    def _max_nesting(self, node: ast.AST, current: int = 0) -> int:
        """Recursively find max nesting depth of if/for/while/try."""
        max_depth = current
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.Try)):
                depth = self._max_nesting(child, current + 1)
                max_depth = max(max_depth, depth)
            else:
                depth = self._max_nesting(child, current)
                max_depth = max(max_depth, depth)
        return max_depth


def infer_role(symbol_name: str, _parent_class: str | None,
               callers_count: int, callees_count: int) -> str:
    """Infer architectural role from naming and relationship patterns."""
    name = symbol_name.split(".")[-1] if "." in symbol_name else symbol_name

    role_patterns = [
        (r"(Controller|Handler|View|Resource|Endpoint)$", "controller"),
        (r"(Service|Manager|UseCase|Interactor|Facade)$", "service"),
        (r"(Repository|Store|DAO|DataAccess|Gateway)$", "repository"),
        (r"(Model|Entity|Schema|DTO|ValueObject)$", "model"),
        (r"(Middleware|Interceptor|Filter)$", "middleware"),
        (r"(Util|Helper|Tool)$", "utility"),
        (r"(Config|Settings|Options)$", "config"),
        (r"(Factory|Builder)$", "factory"),
    ]

    for pattern, role in role_patterns:
        if re.search(pattern, name, re.IGNORECASE):
            return role

    if callees_count > callers_count * 2:
        return "orchestrator"
    if callers_count > callees_count * 2 and callers_count > 0:
        return "utility"

    return "unknown"
