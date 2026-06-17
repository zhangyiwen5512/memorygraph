"""Tests for LanguageDetector."""
import pytest

from memorygraph.parsing.detector import LanguageDetector, UnknownLanguageError
from memorygraph.parsing.registry import LanguageRegistry


@pytest.fixture
def detector():
    return LanguageDetector(LanguageRegistry())


def test_detect_python(detector):
    config = detector.detect("hello.py")
    assert config.name == "python"


def test_detect_typescript_tsx(detector):
    config = detector.detect("Component.tsx")
    assert config.name == "typescript"


def test_detect_unknown_extension(detector):
    with pytest.raises(UnknownLanguageError) as exc_info:
        detector.detect("notes.txt")
    assert ".txt" in str(exc_info.value)


def test_detect_no_extension(detector):
    with pytest.raises(UnknownLanguageError) as exc_info:
        detector.detect("Dockerfile")
    assert "Dockerfile" in str(exc_info.value)


def test_detect_all_builtin_languages(detector):
    """每种内置语言至少能检测一个扩展名。"""
    tests = {
        "test.ts": "typescript",
        "test.tsx": "typescript",
        "test.js": "javascript",
        "test.py": "python",
        "test.go": "go",
        "test.rs": "rust",
        "test.java": "java",
        "test.cs": "csharp",
    }
    for filepath, expected in tests.items():
        config = detector.detect(filepath)
        assert config.name == expected
