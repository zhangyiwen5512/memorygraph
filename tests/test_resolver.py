"""Tests for ReferenceResolver."""
import os

import pytest

from memorygraph.parsing.detector import LanguageDetector
from memorygraph.parsing.extractor import TypeScriptExtractor
from memorygraph.parsing.ir import Edge, EdgeKind, FileInfo, ParseResult, Span
from memorygraph.parsing.registry import LanguageRegistry
from memorygraph.parsing.resolver import ReferenceResolver
from memorygraph.parsing.ts_parser import TreeSitterParser

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def registry():
    return LanguageRegistry()


@pytest.fixture
def parser(registry):
    return TreeSitterParser(registry)


@pytest.fixture
def detector(registry):
    return LanguageDetector(registry)


@pytest.fixture
def sample_path():
    return os.path.join(FIXTURE_DIR, "sample.ts")


def test_resolver_fills_target_span(registry, parser, detector, sample_path):
    """解析 sample.ts 时，内部函数调用的 target_span 被填充。"""
    config = detector.detect(sample_path)
    tree, source_bytes = parser.parse(sample_path, config)
    extractor = TypeScriptExtractor()
    result = extractor.extract(sample_path, tree, source_bytes, config.name)

    # 构建符号表: {symbol_name → Span}
    symbol_index = {}
    for sym in result.symbols:
        symbol_index[sym.name] = sym.span

    # 应用 resolver
    resolver = ReferenceResolver()
    resolved = resolver.resolve(result, symbol_index)

    # 验证：调用已知符号的边的 target_span 被填充
    call_edges = [e for e in resolved.edges if e.kind == EdgeKind.CALLS]
    resolved_edges = [e for e in call_edges if e.target_span is not None]
    assert len(resolved_edges) > 0, "At least some call edges should be resolved"


def test_resolver_unresolved_reference_no_error():
    """引用不存在的符号不报错，target_span 保持 None。"""
    span = Span(file="test.ts", start_line=0, start_col=0, end_line=0, end_col=0)
    edge = Edge(
        source="a.f", target="nonexistent_fn",
        kind=EdgeKind.CALLS, source_span=span
    )
    result = ParseResult(
        file=FileInfo(path="test.ts", language="typescript", content_hash="abc"),
        symbols=[], edges=[edge]
    )
    resolver = ReferenceResolver()
    resolved = resolver.resolve(result, {"some_other": span})
    assert resolved.edges[0].target_span is None


def test_resolver_skips_already_resolved_edge():
    """已有 target_span 的 edge 被跳过，不被覆盖。"""
    span1 = Span(file="a.ts", start_line=1, start_col=0, end_line=1, end_col=10)
    span2 = Span(file="b.ts", start_line=5, start_col=0, end_line=5, end_col=8)
    edge = Edge(
        source="a.f", target="already_resolved",
        kind=EdgeKind.CALLS, source_span=span1, target_span=span2
    )
    result = ParseResult(
        file=FileInfo(path="test.ts", language="typescript", content_hash="abc"),
        symbols=[], edges=[edge]
    )
    resolver = ReferenceResolver()
    # symbol_index has a different span for the same symbol
    different_span = Span(file="c.ts", start_line=0, start_col=0, end_line=0, end_col=0)
    resolved = resolver.resolve(result, {"already_resolved": different_span})
    # target_span should NOT be overwritten
    assert resolved.edges[0].target_span == span2
