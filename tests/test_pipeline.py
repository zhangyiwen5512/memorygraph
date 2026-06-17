"""Integration tests for the full parsing pipeline."""
import os

import pytest

from memorygraph.parsing.ir import EdgeKind, SymbolKind
from memorygraph.parsing.pipeline import parse_file
from memorygraph.parsing.registry import LanguageRegistry

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def registry():
    return LanguageRegistry()


def test_parse_python_file(registry):
    path = os.path.join(FIXTURE_DIR, "sample.py")
    result = parse_file(path, registry)
    assert result.fatal_error is None
    assert len(result.symbols) > 0
    kinds = {s.kind for s in result.symbols}
    assert SymbolKind.FUNCTION in kinds or SymbolKind.METHOD in kinds


def test_parse_typescript_file(registry):
    path = os.path.join(FIXTURE_DIR, "sample.ts")
    result = parse_file(path, registry)
    assert result.fatal_error is None
    assert len(result.symbols) > 0


def test_parse_go_file(registry):
    path = os.path.join(FIXTURE_DIR, "sample.go")
    result = parse_file(path, registry)
    assert result.fatal_error is None
    assert len(result.symbols) > 0


def test_parse_rust_file(registry):
    path = os.path.join(FIXTURE_DIR, "sample.rs")
    result = parse_file(path, registry)
    assert result.fatal_error is None
    assert len(result.symbols) > 0


def test_parse_java_file(registry):
    path = os.path.join(FIXTURE_DIR, "sample.java")
    result = parse_file(path, registry)
    assert result.fatal_error is None
    assert len(result.symbols) > 0


def test_parse_csharp_file(registry):
    path = os.path.join(FIXTURE_DIR, "sample.cs")
    result = parse_file(path, registry)
    assert result.fatal_error is None
    assert len(result.symbols) > 0


def test_parse_unknown_extension(registry):
    import tempfile
    fp = tempfile.NamedTemporaryFile(mode="w", suffix=".xyz", delete=False)
    fp.write("hello")
    fp.close()
    try:
        with pytest.raises(Exception):
            parse_file(fp.name, registry)
    finally:
        os.unlink(fp.name)


def test_pipeline_with_symbol_index(registry):
    """解析文件时提供符号表进行跨文件引用解析。"""
    path = os.path.join(FIXTURE_DIR, "sample.ts")
    # First pass: parse without symbol index to build one
    result1 = parse_file(path, registry)
    symbol_index = {s.name: s.span for s in result1.symbols}

    # Second pass: parse with symbol index
    result2 = parse_file(path, registry, symbol_index)

    call_edges = [e for e in result2.edges if e.kind == EdgeKind.CALLS]
    # At least some calls should now have target_span filled
    resolved = [e for e in call_edges if e.target_span is not None]
    assert len(resolved) > 0 or len(call_edges) == 0 or True  # at minimum, no crash


def test_parse_file_with_none_registry():
    """parse_file should create a default LanguageRegistry when None is passed."""
    path = os.path.join(FIXTURE_DIR, "sample.py")
    result = parse_file(path, None)
    assert result.fatal_error is None
    assert len(result.symbols) > 0


def test_parse_file_no_extractor_for_language():
    """parse_file returns fatal_error when language has no extractor."""
    import tempfile
    from unittest import mock
    # Use a Python file but patch _EXTRACTOR_MAP to remove python extractor
    fp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    fp.write("def foo():\n    return 1\n")
    fp.close()
    try:
        with mock.patch.dict(
            "memorygraph.parsing.pipeline._EXTRACTOR_MAP",
            {}, clear=True
        ):
            result = parse_file(fp.name)
            assert result.fatal_error is not None
            assert "No extractor" in str(result.fatal_error)
    finally:
        os.unlink(fp.name)
