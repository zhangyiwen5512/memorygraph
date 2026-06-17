"""Tests for IR data types."""
import json

from memorygraph.parsing.ir import (
    Edge,
    EdgeKind,
    FileInfo,
    ParseResult,
    Span,
    Symbol,
    SymbolKind,
    to_json_dict,
)


def test_symbol_kind_values():
    assert SymbolKind.FUNCTION.value == "function"
    assert SymbolKind.METHOD.value == "method"
    assert SymbolKind.CLASS.value == "class"
    assert SymbolKind.INTERFACE.value == "interface"
    assert SymbolKind.TYPE_ALIAS.value == "type"
    assert SymbolKind.VARIABLE.value == "variable"


def test_edge_kind_values():
    assert EdgeKind.CALLS.value == "calls"
    assert EdgeKind.IMPORTS.value == "imports"
    assert EdgeKind.EXTENDS.value == "extends"
    assert EdgeKind.IMPLEMENTS.value == "implements"
    assert EdgeKind.TYPE_REFERENCES.value == "type_refs"


def test_span_creation():
    span = Span(
        file="/path/to/file.py",
        start_line=0, start_col=4,
        end_line=0, end_col=10
    )
    assert span.file == "/path/to/file.py"
    assert span.start_line == 0
    assert span.start_col == 4


def test_symbol_creation():
    span = Span(file="test.py", start_line=1, start_col=0, end_line=3, end_col=0)
    sym = Symbol(
        name="my_func",
        kind=SymbolKind.FUNCTION,
        span=span,
        parent_symbol=None,
        signature="def my_func(x: int) -> str",
        is_partial=False
    )
    assert sym.name == "my_func"
    assert sym.kind == SymbolKind.FUNCTION
    assert sym.is_partial is False


def test_symbol_defaults():
    span = Span(file="test.py", start_line=0, start_col=0, end_line=0, end_col=0)
    sym = Symbol(name="x", kind=SymbolKind.VARIABLE, span=span)
    assert sym.parent_symbol is None
    assert sym.signature is None
    assert sym.is_partial is False


def test_edge_creation():
    source_span = Span(file="a.py", start_line=5, start_col=4, end_line=5, end_col=10)
    target_span = Span(file="b.py", start_line=1, start_col=0, end_line=3, end_col=0)
    edge = Edge(
        source="a.my_func",
        target="b.other_func",
        kind=EdgeKind.CALLS,
        source_span=source_span,
        target_span=target_span
    )
    assert edge.source == "a.my_func"
    assert edge.target == "b.other_func"
    assert edge.kind == EdgeKind.CALLS


def test_edge_target_span_optional():
    source_span = Span(file="a.py", start_line=5, start_col=4, end_line=5, end_col=10)
    edge = Edge(
        source="a.my_func",
        target="b.unresolved_func",
        kind=EdgeKind.CALLS,
        source_span=source_span,
        target_span=None
    )
    assert edge.target_span is None


def test_file_info_creation():
    info = FileInfo(
        path="/abs/path/to/file.ts",
        language="typescript",
        content_hash="abc123",
    )
    assert info.language == "typescript"
    assert info.content_hash == "abc123"


def test_parse_result_success():
    info = FileInfo(path="test.py", language="python", content_hash="hash1")
    span = Span(file="test.py", start_line=0, start_col=0, end_line=0, end_col=0)
    sym = Symbol(name="f", kind=SymbolKind.FUNCTION, span=span)
    result = ParseResult(file=info, symbols=[sym], edges=[], errors=[])
    assert result.fatal_error is None
    assert len(result.symbols) == 1


def test_parse_result_fatal_error():
    info = FileInfo(path="bad.xyz", language="unknown", content_hash="")
    result = ParseResult(
        file=info, symbols=[], edges=[], errors=[],
        fatal_error="Unsupported file extension: .xyz"
    )
    assert result.fatal_error is not None


def test_parse_result_json_serializable():
    info = FileInfo(path="test.py", language="python", content_hash="abc")
    span = Span(file="test.py", start_line=0, start_col=0, end_line=0, end_col=0)
    sym = Symbol(name="f", kind=SymbolKind.FUNCTION, span=span)
    edge = Edge(
        source="f", target="g", kind=EdgeKind.CALLS,
        source_span=span, target_span=None
    )
    result = ParseResult(file=info, symbols=[sym], edges=[edge], errors=[])
    d = to_json_dict(result)
    json_str = json.dumps(d)
    parsed = json.loads(json_str)
    assert parsed["symbols"][0]["name"] == "f"
    assert parsed["edges"][0]["kind"] == "calls"


def test_to_json_dict_with_dict():
    """to_json_dict handles dict values recursively."""
    input_dict = {"name": "foo", "meta": {"version": 1}}
    result = to_json_dict(input_dict)
    assert result["name"] == "foo"
    assert result["meta"]["version"] == 1


def test_to_json_dict_with_nested_list():
    """to_json_dict handles list of dicts."""
    input_data = [{"a": 1}, {"b": 2}]
    result = to_json_dict(input_data)
    assert result == [{"a": 1}, {"b": 2}]
