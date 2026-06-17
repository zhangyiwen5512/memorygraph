"""Tests for TypeScript IRExtractor."""
import os

import pytest

from memorygraph.parsing.detector import LanguageDetector
from memorygraph.parsing.extractor import TypeScriptExtractor
from memorygraph.parsing.ir import EdgeKind, SymbolKind
from memorygraph.parsing.registry import LanguageRegistry
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


def test_ts_extractor_extracts_functions(registry, parser, detector, sample_path):
    config = detector.detect(sample_path)
    tree, source_bytes = parser.parse(sample_path, config)
    extractor = TypeScriptExtractor()
    result = extractor.extract(sample_path, tree, source_bytes, config.name)
    func_names = [s.name for s in result.symbols if s.kind == SymbolKind.FUNCTION]
    assert "makeGreeter" in func_names
    assert "main" in func_names


def test_ts_extractor_extracts_class(registry, parser, detector, sample_path):
    config = detector.detect(sample_path)
    tree, source_bytes = parser.parse(sample_path, config)
    extractor = TypeScriptExtractor()
    result = extractor.extract(sample_path, tree, source_bytes, config.name)
    class_names = [s.name for s in result.symbols if s.kind == SymbolKind.CLASS]
    assert "Person" in class_names


def test_ts_extractor_extracts_interface(registry, parser, detector, sample_path):
    config = detector.detect(sample_path)
    tree, source_bytes = parser.parse(sample_path, config)
    extractor = TypeScriptExtractor()
    result = extractor.extract(sample_path, tree, source_bytes, config.name)
    iface_names = [s.name for s in result.symbols if s.kind == SymbolKind.INTERFACE]
    assert "Greetable" in iface_names


def test_ts_extractor_extracts_methods(registry, parser, detector, sample_path):
    config = detector.detect(sample_path)
    tree, source_bytes = parser.parse(sample_path, config)
    extractor = TypeScriptExtractor()
    result = extractor.extract(sample_path, tree, source_bytes, config.name)
    method_names = [s.name for s in result.symbols if s.kind == SymbolKind.METHOD]
    # Note: method detection depends on parent_symbol matching a class name
    # 'greet' and 'constructor' are methods inside Person
    assert "greet" in method_names


def test_ts_extractor_extracts_call_edges(registry, parser, detector, sample_path):
    config = detector.detect(sample_path)
    tree, source_bytes = parser.parse(sample_path, config)
    extractor = TypeScriptExtractor()
    result = extractor.extract(sample_path, tree, source_bytes, config.name)
    call_edges = [e for e in result.edges if e.kind == EdgeKind.CALLS]
    assert len(call_edges) > 0


def test_ts_extractor_non_empty_result(registry, parser, detector, sample_path):
    config = detector.detect(sample_path)
    tree, source_bytes = parser.parse(sample_path, config)
    extractor = TypeScriptExtractor()
    result = extractor.extract(sample_path, tree, source_bytes, config.name)
    assert len(result.symbols) > 0
    assert result.fatal_error is None
