"""Tests for LanguageRegistry."""
import pytest

from memorygraph.parsing.registry import LanguageConfig, LanguageRegistry


@pytest.fixture
def registry():
    reg = LanguageRegistry()
    yield reg


def test_register_and_detect(registry):
    config = LanguageConfig(
        name="python",
        extensions=[".py"],
        grammar_package="tree-sitter-python",
        grammar_lang_attr="language_python"
    )
    registry.register(config)
    detected = registry.detect("test.py")
    assert detected is not None
    assert detected.name == "python"


def test_detect_by_full_path(registry):
    config = LanguageConfig(
        name="typescript",
        extensions=[".ts", ".tsx"],
        grammar_package="tree-sitter-typescript",
        grammar_lang_attr="language_typescript"
    )
    registry.register(config)
    detected = registry.detect("/home/user/project/src/component.tsx")
    assert detected is not None
    assert detected.name == "typescript"


def test_detect_unknown_extension(registry):
    detected = registry.detect("file.xyz")
    assert detected is None


def test_detect_no_extension(registry):
    detected = registry.detect("Makefile")
    assert detected is None


def test_detect_case_insensitive(registry):
    config = LanguageConfig(
        name="go",
        extensions=[".go"],
        grammar_package="tree-sitter-go",
        grammar_lang_attr="language_go"
    )
    registry.register(config)
    detected = registry.detect("main.GO")
    assert detected is not None
    assert detected.name == "go"


def test_builtin_languages_registered(registry):
    """内置 7 种语言在模块加载时自动注册。"""
    tests = [
        ("test.ts", "typescript"),
        ("test.tsx", "typescript"),
        ("test.js", "javascript"),
        ("test.jsx", "javascript"),
        ("test.py", "python"),
        ("test.go", "go"),
        ("test.rs", "rust"),
        ("test.java", "java"),
        ("test.cs", "csharp"),
    ]
    for filepath, expected_lang in tests:
        detected = registry.detect(filepath)
        assert detected is not None, f"Failed to detect {filepath}"
        assert detected.name == expected_lang, f"Expected {expected_lang} for {filepath}, got {detected.name}"


def test_get_supported_extensions(registry):
    exts = registry.supported_extensions()
    assert ".py" in exts
    assert ".ts" in exts
    assert ".go" in exts


def test_is_available_returns_bool(registry):
    result = registry.is_available("python")
    assert isinstance(result, bool)


def test_is_available_unknown_language(registry):
    """is_available for unknown language should return False."""
    result = registry.is_available("brainfuck")
    assert result is False


def test_is_available_import_error(registry):
    """is_available should return False when module import fails."""
    # Register a fake language that will fail to import
    config = LanguageConfig(
        name="fakelang",
        extensions=[".fake"],
        grammar_package="nonexistent-package-xyz",
        grammar_lang_attr="language"
    )
    registry.register(config)
    result = registry.is_available("fakelang")
    assert result is False


def test_load_grammar_unknown_language(registry):
    """load_grammar for unknown language should raise ValueError."""
    with pytest.raises(ValueError, match="Unknown language"):
        registry.load_grammar("nonexistent_lang")


def test_load_grammar_install_on_import_error(registry):
    """load_grammar should attempt pip install on ImportError."""
    from unittest import mock

    config = LanguageConfig(
        name="fakelang2",
        extensions=[".fk2"],
        grammar_package="fake-pkg-install",
        grammar_lang_attr="language"
    )
    registry.register(config)

    mock_module = mock.MagicMock()
    mock_module.language = mock.MagicMock(return_value="fake_grammar")

    with mock.patch.object(
        registry, "_load_module",
        side_effect=[ImportError("no module"), mock_module]
    ), mock.patch.object(
        registry, "_install_grammar"
    ) as mock_install:
        result = registry.load_grammar("fakelang2")
        mock_install.assert_called_once()
        assert result == "fake_grammar"


def test_load_grammar_fallback_to_language_attr(registry):
    """load_grammar should fallback to 'language' attr when configured attr missing."""
    from unittest import mock

    config = LanguageConfig(
        name="fakelang3",
        extensions=[".fk3"],
        grammar_package="fake-pkg-fallback",
        grammar_lang_attr="nonexistent_attr"
    )
    registry.register(config)

    mock_module = mock.MagicMock()
    del mock_module.nonexistent_attr  # Ensure it doesn't exist
    mock_module.language = mock.MagicMock(return_value="fallback_grammar")

    with mock.patch.object(registry, "_load_module", return_value=mock_module):
        result = registry.load_grammar("fakelang3")
        assert result == "fallback_grammar"


def test_load_grammar_no_language_fn_raises(registry):
    """load_grammar should raise AttributeError when no language function found."""
    from unittest import mock

    config = LanguageConfig(
        name="fakelang4",
        extensions=[".fk4"],
        grammar_package="fake-pkg-nolang",
        grammar_lang_attr="nonexistent_attr"
    )
    registry.register(config)

    mock_module = mock.MagicMock()
    # Remove both the configured attr and 'language' fallback
    del mock_module.nonexistent_attr
    del mock_module.language

    with mock.patch.object(registry, "_load_module", return_value=mock_module):
        with pytest.raises(AttributeError, match="Could not find language function"):
            registry.load_grammar("fakelang4")


def test_install_grammar_calls_subprocess(registry):
    """_install_grammar should call subprocess.check_call with pip install."""
    from unittest import mock
    config = LanguageConfig(
        name="testlang",
        extensions=[".tl"],
        grammar_package="test-grammar-pkg",
        grammar_lang_attr="language",
    )
    registry.register(config)

    with mock.patch("subprocess.check_call") as mock_check_call:
        registry._install_grammar(config)
        mock_check_call.assert_called_once_with(
            [mock.ANY, "-m", "pip", "install", "test-grammar-pkg"],
            timeout=60,
        )
        args = mock_check_call.call_args[0][0]
        assert args == ["python", "-m", "pip", "install", "test-grammar-pkg"] or \
               args[1:] == ["-m", "pip", "install", "test-grammar-pkg"]


def test_load_grammar_class_cache_hit(registry):
    """Second load_grammar call for same language hits class-level cache (covers line 106)."""
    # First call loads and caches the grammar
    grammar1 = registry.load_grammar("python")
    assert grammar1 is not None
    # Second call returns from _loaded_grammars class cache
    grammar2 = registry.load_grammar("python")
    assert grammar2 is grammar1


def test_load_grammar_no_auto_install_raises(registry, monkeypatch):
    """When MEMORYGRAPH_NO_AUTO_INSTALL is set, ImportError should propagate."""
    from unittest import mock
    monkeypatch.setenv("MEMORYGRAPH_NO_AUTO_INSTALL", "1")
    config = LanguageConfig(
        name="noinstall",
        extensions=[".ni"],
        grammar_package="nonexistent-pkg",
        grammar_lang_attr="language",
    )
    registry.register(config)
    with mock.patch.object(registry, "_load_module", side_effect=ImportError):
        with mock.patch.object(registry, "_install_grammar") as mock_install:
            with pytest.raises(ImportError, match="MEMORYGRAPH_NO_AUTO_INSTALL"):
                registry.load_grammar("noinstall")
            mock_install.assert_not_called()
