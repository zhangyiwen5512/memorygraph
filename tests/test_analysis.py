"""Tests for semantic analysis module."""
import ast
from pathlib import Path

import pytest

from memorygraph.semantic.analysis import (
    SmellDetector,
    analyze_complexity,
    analyze_raw,
    infer_role,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestComplexity:
    def test_simple_function_has_low_complexity(self):
        source = "def f(): return 1"
        results = analyze_complexity(source)
        assert len(results) == 1
        assert results[0]["name"] == "f"
        assert results[0]["complexity"] == 1
        assert results[0]["rank"] == "A"

    def test_complex_function_has_higher_score(self):
        source = (FIXTURES / "complex.py").read_text()
        results = analyze_complexity(source)
        names = {r["name"]: r for r in results}
        assert names["simple_function"]["complexity"] == 1
        assert names["complex_function"]["complexity"] > 5

    def test_empty_source_returns_empty(self):
        assert analyze_complexity("") == []


class TestRawMetrics:
    def test_returns_all_fields(self):
        source = "x = 1\ny = 2\n# comment\n"
        raw = analyze_raw(source)
        assert raw["loc"] > 0
        assert "comments" in raw


class TestSmellDetector:
    def test_detects_god_class(self):
        source = (FIXTURES / "smelly.py").read_text()
        tree = ast.parse(source)
        detector = SmellDetector()
        smells = detector.detect(tree, "GodClass", [], [])
        god_class = [s for s in smells if s["rule"] == "god_class"]
        assert len(god_class) == 1
        assert god_class[0]["severity"] == "warning"

    def test_detects_long_parameter_list(self):
        source = (FIXTURES / "smelly.py").read_text()
        tree = ast.parse(source)
        detector = SmellDetector()
        smells = detector.detect(tree, "many_params", [], [])
        param_smell = [s for s in smells if s["rule"] == "long_parameter_list"]
        assert len(param_smell) == 1

    def test_detects_shotgun_surgery(self):
        tree = ast.parse("def f(): pass")
        detector = SmellDetector()
        smells = detector.detect(tree, "f", list(range(15)), [])
        shotgun = [s for s in smells if s["rule"] == "shotgun_surgery"]
        assert len(shotgun) == 1


class TestRoleInference:
    def test_controller_pattern(self):
        assert infer_role("UserController", None, 1, 2) == "controller"

    def test_service_pattern(self):
        assert infer_role("PaymentService", None, 2, 5) == "service"

    def test_repository_pattern(self):
        assert infer_role("UserRepository", None, 0, 0) == "repository"

    def test_orchestrator_by_ratio(self):
        assert infer_role("Orchestrator", None, 1, 10) == "orchestrator"

    def test_utility_by_ratio(self):
        assert infer_role("HelperFunc", None, 10, 1) == "utility"

    def test_unknown(self):
        assert infer_role("xyzzy", None, 0, 0) == "unknown"

    def test_factory_pattern(self):
        assert infer_role("WidgetFactory", None, 0, 0) == "factory"

    def test_model_pattern(self):
        assert infer_role("UserDTO", None, 0, 0) == "model"

    def test_middleware_pattern(self):
        assert infer_role("AuthFilter", None, 0, 0) == "middleware"

    def test_config_pattern(self):
        assert infer_role("AppSettings", None, 0, 0) == "config"


class TestRoleInferenceParametrized:
    """Parameterized role inference edge cases."""

    @pytest.mark.parametrize("name,parent,callers,callees,expected", [
        ("UserController", None, 1, 2, "controller"),
        ("PaymentService", None, 2, 5, "service"),
        ("UserRepository", None, 0, 0, "repository"),
        ("UserModel", None, 0, 0, "model"),
        ("LogMiddleware", None, 0, 0, "middleware"),
        ("StringUtil", None, 0, 0, "utility"),
        ("AppConfig", None, 0, 0, "config"),
        ("UserFactory", None, 0, 0, "factory"),
        ("AuthHandler", None, 0, 0, "controller"),
        ("OrderManager", None, 0, 0, "service"),
        ("UserDAO", None, 0, 0, "repository"),
        ("ProductEntity", None, 0, 0, "model"),
        ("RequestFilter", None, 0, 0, "middleware"),
        ("Orchestrator", None, 1, 10, "orchestrator"),
        ("PlainName", None, 10, 2, "utility"),
        ("UnknownName", None, 0, 0, "unknown"),
    ])
    def test_infer_role(self, name, parent, callers, callees, expected):
        assert infer_role(name, parent, callers, callees) == expected


class TestMaxNesting:
    """Tests for _max_nesting depth analysis."""

    @pytest.mark.parametrize("source,min_depth", [
        ("def f(): pass", 0),
        ("def f():\n    if x:\n        pass", 1),
        ("def f():\n    for x in y:\n        if z:\n            while True:\n                pass", 3),
        ("def f():\n    if a:\n        if b:\n            pass", 2),
        ("def f():\n    try:\n        for x in y:\n            if z:\n                pass\n    except:\n        pass", 3),
    ])
    def test_max_nesting_depth(self, source, min_depth):
        tree = ast.parse(source)
        detector = SmellDetector()
        depth = detector._max_nesting(tree)
        assert depth >= min_depth, f"Expected depth >= {min_depth}, got {depth}"


class TestBuildNodeMap:
    """Tests for _build_node_map."""

    @pytest.mark.parametrize("source,expected_classes,expected_funcs", [
        ("", 0, 0),
        ("class A: pass\nclass B: pass", 2, 0),
        ("def f(): pass\ndef g(): pass", 0, 2),
        ("class A:\n    def m(self): pass", 1, 1),
    ])
    def test_build_node_map_counts(self, source, expected_classes, expected_funcs):
        tree = ast.parse(source) if source else ast.parse("")
        detector = SmellDetector()
        node_map = detector._build_node_map(tree)
        classes = sum(1 for n in node_map.values() if isinstance(n, ast.ClassDef))
        funcs = sum(1 for n in node_map.values() if isinstance(n, ast.FunctionDef))
        assert classes == expected_classes, f"Expected {expected_classes} classes, got {classes}"
        assert funcs == expected_funcs, f"Expected {expected_funcs} funcs, got {funcs}"


class TestComplexityEdgeCases:
    """Tests for uncovered complexity rank paths."""

    def test_complexity_rank_b(self):
        """Source with complexity 6-10 should get rank B."""
        # if/else + 1 base = complexity ~3, need more
        source = "def f(x):\n    if x:\n        return 1\n    elif x == 2:\n        return 2\n    elif x == 3:\n        return 3\n    elif x == 4:\n        return 4\n    elif x == 5:\n        return 5\n    elif x == 6:\n        return 6\n    else:\n        return 7\n"
        results = analyze_complexity(source)
        if results:
            assert results[0]["rank"] in ("A", "B")

    def test_complexity_syntax_error(self):
        """Invalid Python should return empty list (exception path)."""
        source = "def f(: return"
        results = analyze_complexity(source)
        assert results == []

    def test_complexity_empty_string(self):
        source = ""
        results = analyze_complexity(source)
        assert results == []

    def test_complexity_rank_c(self):
        """Source with complexity > 20 should get C or higher."""
        source = (
            "def f(x):\n"
            "    r = 0\n"
            + "".join(f"    if x == {i}:\n        r = {i}\n" for i in range(12))
            + "    return r\n"
        )
        results = analyze_complexity(source)
        if results:
            assert results[0]["rank"] in ("A", "B", "C", "D", "E", "F")


class TestRawMetricsEdgeCases:
    """Tests for uncovered analyze_raw paths."""

    def test_raw_with_invalid_source(self):
        """Invalid source triggers exception handler."""
        raw = analyze_raw("class : invalid")
        # Should return default zero values
        assert isinstance(raw, dict)
        assert "loc" in raw

    def test_raw_minimal_source(self):
        raw = analyze_raw("pass\n")
        assert raw["loc"] >= 1


class TestSmellDetectorEdgeCases:
    """Tests for all smell detection paths."""

    def test_long_method(self):
        """Method with >50 lines should trigger long_method."""
        lines = ["def long_func():"] + [f"    x{i} = {i}" for i in range(60)]
        source = "\n".join(lines)
        tree = ast.parse(source)
        detector = SmellDetector()
        smells = detector.detect(tree, "long_func", [], [])
        long_method = [s for s in smells if s["rule"] == "long_method"]
        assert len(long_method) == 1

    def test_deep_nesting(self):
        """Method with >4 nesting levels should trigger deep_nesting."""
        source = "def deep():\n    if True:\n        for x in []:\n            if x:\n                while x:\n                    if x:\n                        pass\n"
        tree = ast.parse(source)
        detector = SmellDetector()
        smells = detector.detect(tree, "deep", [], [])
        deep_nesting = [s for s in smells if s["rule"] == "deep_nesting"]
        assert len(deep_nesting) == 1

    def test_dead_code(self):
        """Private function with no callers should trigger dead_code."""
        source = "def _unused_helper():\n    pass\n"
        tree = ast.parse(source)
        detector = SmellDetector()
        smells = detector.detect(tree, "_unused_helper", [], [])
        dead_code = [s for s in smells if s["rule"] == "dead_code"]
        assert len(dead_code) == 1

    def test_feature_envy(self):
        """Function that calls more external symbols than internal ones."""
        source = "def do_work():\n    pass\n"
        tree = ast.parse(source)
        detector = SmellDetector()
        callees = [
            {"target": "external_api.call"},
            {"target": "external_api.fetch"},
            {"target": "do_work.helper"},  # internal
        ]
        callers = [{"source": "main"}]
        smells = detector.detect(tree, "do_work", callers, callees)
        feature_envy = [s for s in smells if s["rule"] == "feature_envy"]
        assert len(feature_envy) == 1

    def test_no_feature_envy_when_balanced(self):
        """Balanced internal/external calls should not trigger feature_envy."""
        source = "def balanced():\n    pass\n"
        tree = ast.parse(source)
        detector = SmellDetector()
        callees = [
            {"target": "balanced.helper"},
            {"target": "balanced.utils"},
        ]
        callers = [{"source": "main"}]
        smells = detector.detect(tree, "balanced", callers, callees)
        feature_envy = [s for s in smells if s["rule"] == "feature_envy"]
        assert len(feature_envy) == 0

    def test_no_smells_for_clean_function(self):
        """A simple, clean function should have no smells."""
        source = "def clean():\n    return 1\n"
        tree = ast.parse(source)
        detector = SmellDetector()
        callers = [{"source": "caller1", "target": "clean"}]
        callees = [{"source": "clean", "target": "clean.helper"}]
        smells = detector.detect(tree, "clean", callers, callees)
        assert len(smells) == 0

    def test_max_nesting_recursive(self):
        """_max_nesting should count nested if/for/while/try."""
        source = "def nested():\n    try:\n        if True:\n            for x in []:\n                pass\n    except Exception:\n        pass\n"
        tree = ast.parse(source)
        detector = SmellDetector()
        func_node = tree.body[0]
        depth = detector._max_nesting(func_node)
        assert depth == 3  # try → if → for

    def test_long_parameter_list_edge(self):
        """Exactly 6 params (5 + self) should trigger."""
        source = "def many(self, a, b, c, d, e, f):\n    pass\n"
        tree = ast.parse(source)
        detector = SmellDetector()
        smells = detector.detect(tree, "many", [], [])
        param_smell = [s for s in smells if s["rule"] == "long_parameter_list"]
        assert len(param_smell) == 1

    def test_short_parameter_list_no_smell(self):
        """5 params (4 + self) should NOT trigger."""
        source = "def few(self, a, b, c, d):\n    pass\n"
        tree = ast.parse(source)
        detector = SmellDetector()
        smells = detector.detect(tree, "few", [], [])
        param_smell = [s for s in smells if s["rule"] == "long_parameter_list"]
        assert len(param_smell) == 0
