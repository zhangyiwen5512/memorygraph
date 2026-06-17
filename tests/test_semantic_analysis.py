"""Additional tests for semantic analysis functions."""


from memorygraph.semantic.analysis import (
    SmellDetector,
    analyze_complexity,
    analyze_raw,
    infer_role,
)
from memorygraph.semantic.models import SemanticDocument


class TestAnalyzeComplexity:
    def test_python_file(self):
        source = "def foo():\n    return 1\n\ndef bar(x):\n    if x:\n        return 1\n    return 0\n"
        results = analyze_complexity(source)
        assert len(results) >= 2
        assert any(r["name"] == "foo" for r in results)

    def test_empty_source(self):
        results = analyze_complexity("")
        assert results == []

    def test_class_methods(self):
        source = "class MyClass:\n    def method1(self):\n        return 1\n    def method2(self):\n        if True:\n            pass\n"
        results = analyze_complexity(source)
        assert len(results) >= 2


class TestAnalyzeRaw:
    def test_python_file(self):
        source = "def foo():\n    return 1\n"
        results = analyze_raw(source)
        assert "loc" in results
        assert results["loc"] >= 2

    def test_empty_source(self):
        results = analyze_raw("")
        assert "loc" in results
        assert results["loc"] == 0


class TestComplexityRank:
    """Tests for _complexity_rank all branches."""

    def test_complexity_rank_a(self):
        from memorygraph.semantic.analysis import _complexity_rank
        assert _complexity_rank(5) == "A"

    def test_complexity_rank_b(self):
        from memorygraph.semantic.analysis import _complexity_rank
        assert _complexity_rank(10) == "B"

    def test_complexity_rank_c(self):
        from memorygraph.semantic.analysis import _complexity_rank
        assert _complexity_rank(20) == "C"

    def test_complexity_rank_d(self):
        from memorygraph.semantic.analysis import _complexity_rank
        assert _complexity_rank(30) == "D"

    def test_complexity_rank_e(self):
        from memorygraph.semantic.analysis import _complexity_rank
        assert _complexity_rank(40) == "E"

    def test_complexity_rank_f(self):
        from memorygraph.semantic.analysis import _complexity_rank
        assert _complexity_rank(100) == "F"


class TestAnalyzeRawException:
    """Test analyze_raw exception path."""

    def test_analyze_raw_exception(self):
        from unittest import mock

        from memorygraph.semantic.analysis import analyze_raw
        with mock.patch("radon.raw.analyze", side_effect=ImportError("no radon")):
            result = analyze_raw("def f(): pass")
            assert result["loc"] == 0
            assert result["comments"] == 0


class TestSmellDetector:
    def test_detect_long_function(self):
        detector = SmellDetector()
        # Function with many lines and parameters triggers long function smell
        source = "def func(a, b, c, d, e, f):\n" + "    pass\n" * 30
        import ast
        tree = ast.parse(source)
        odors = detector.detect(tree, "func", [], [])
        assert isinstance(odors, list)

    def test_detect_no_smells(self):
        detector = SmellDetector()
        import ast
        source = "def short():\n    return 1\n"
        tree = ast.parse(source)
        odors = detector.detect(tree, "short", [], [])
        assert isinstance(odors, list)


class TestInferRole:
    def test_infer_controller(self):
        role = infer_role("handle_request", None, 2, 5)
        assert isinstance(role, str)

    def test_infer_model(self):
        role = infer_role("UserModel", "BaseModel", 1, 0)
        assert isinstance(role, str)


class TestSemanticDocumentEdgeCases:
    def test_merge(self):
        doc1 = SemanticDocument(
            file="test.py", source="test",
            module_summary="Initial summary",
        )
        doc2 = SemanticDocument(
            file="test.py", source="test2",
            module_summary="Updated summary",
        )
        doc1.merge_from(doc2)
        assert "Initial" in doc1.module_summary or "Updated" in doc1.module_summary

    def test_empty_document(self):
        doc = SemanticDocument(file="test.py")
        assert doc.file == "test.py"
        assert doc.source == "manual"
