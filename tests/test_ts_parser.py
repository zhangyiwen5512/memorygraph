"""Tests for TreeSitterParser."""
import os
import tempfile

import pytest

from memorygraph.parsing.detector import LanguageDetector
from memorygraph.parsing.registry import LanguageRegistry
from memorygraph.parsing.ts_parser import ParseError, TreeSitterParser


@pytest.fixture
def registry():
    return LanguageRegistry()


@pytest.fixture
def detector(registry):
    return LanguageDetector(registry)


@pytest.fixture
def ts_parser(registry):
    return TreeSitterParser(registry)


def make_temp_file(content, suffix=".py"):
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    )
    tmp.write(content)
    tmp.close()
    return tmp.name


def test_parse_simple_python_file(ts_parser, detector):
    path = make_temp_file("def hello():\n    pass\n", ".py")
    try:
        config = detector.detect(path)
        tree, source_bytes = ts_parser.parse(path, config)
        assert tree is not None
        assert tree.root_node is not None
        assert b"def hello" in source_bytes
    finally:
        os.unlink(path)


def test_parse_syntax_error_does_not_raise(ts_parser, detector):
    """tree-sitter 容错——有语法错误也应返回部分 AST。"""
    path = make_temp_file("def broken(:\n    pass\n", ".py")
    try:
        config = detector.detect(path)
        tree, source_bytes = ts_parser.parse(path, config)
        assert tree is not None
    finally:
        os.unlink(path)


def test_parse_file_not_found(ts_parser, detector):
    config = detector.detect("test.py")
    with pytest.raises(ParseError) as exc_info:
        ts_parser.parse("/nonexistent/path.py", config)
    assert "nonexistent" in str(exc_info.value)


def test_parse_empty_file(ts_parser, detector):
    path = make_temp_file("", ".py")
    try:
        config = detector.detect(path)
        tree, source_bytes = ts_parser.parse(path, config)
        assert tree is not None
        assert source_bytes == b""
    finally:
        os.unlink(path)


def test_parse_oserror_on_read(ts_parser, detector):
    """OSError on file read should raise ParseError."""
    from unittest import mock
    config = detector.detect("test.py")
    with mock.patch("builtins.open", side_effect=OSError("Permission denied")):
        with pytest.raises(ParseError) as exc_info:
            ts_parser.parse("some_file.py", config)
        assert "Cannot read file" in str(exc_info.value)
        assert "Permission denied" in str(exc_info.value)


def test_parse_grammar_load_exception(ts_parser, detector):
    """Exception during grammar loading should raise ParseError."""
    from unittest import mock
    path = make_temp_file("x = 1\n", ".py")
    try:
        config = detector.detect(path)
        with mock.patch.object(
            ts_parser, "_get_parser",
            side_effect=Exception("Grammar crash")
        ):
            with pytest.raises(ParseError) as exc_info:
                ts_parser.parse(path, config)
            assert "Failed to load grammar" in str(exc_info.value)
    finally:
        os.unlink(path)
