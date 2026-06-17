"""Tests for the plugin system."""
from unittest.mock import MagicMock, patch

import pytest

from memorygraph.plugins import (
    AnalyzerPlugin,
    LanguagePlugin,
    builtin_languages,
    discover_plugins,
)


class TestBuiltinLanguages:
    def test_returns_list(self):
        langs = builtin_languages()
        assert isinstance(langs, list)

    def test_has_seven_languages(self):
        langs = builtin_languages()
        # Python, TypeScript, JavaScript, Go, Rust, Java, C#
        assert len(langs) == 7

    def test_each_entry_has_name_and_extensions(self):
        langs = builtin_languages()
        for lang in langs:
            assert "name" in lang
            assert "extensions" in lang
            assert isinstance(lang["name"], str)
            assert isinstance(lang["extensions"], list)
            assert len(lang["extensions"]) >= 1

    def test_known_languages_present(self):
        langs = builtin_languages()
        names = {l["name"] for l in langs}
        expected = {"python", "typescript", "javascript", "go", "rust", "java", "csharp"}
        assert names == expected

    def test_python_has_correct_extensions(self):
        langs = builtin_languages()
        python = next(l for l in langs if l["name"] == "python")
        assert ".py" in python["extensions"]
        assert ".pyi" in python["extensions"]

    def test_typescript_has_correct_extensions(self):
        langs = builtin_languages()
        ts = next(l for l in langs if l["name"] == "typescript")
        assert ".ts" in ts["extensions"]
        assert ".tsx" in ts["extensions"]


class TestDiscoverPlugins:
    def test_no_plugins_returns_empty(self):
        mock_entry_points = MagicMock(return_value=[])
        with patch("importlib.metadata.entry_points", mock_entry_points):
            result = discover_plugins()
            assert result == {"language": [], "analyzer": []}

    def test_discovers_language_plugin(self):
        class KotlinPlugin(LanguagePlugin):
            @property
            def language(self):
                return "kotlin"

            @property
            def extensions(self):
                return [".kt"]

            def extract(self, file_path, tree, source_bytes, language):
                return MagicMock()

        mock_ep = MagicMock()
        mock_ep.load.return_value = KotlinPlugin
        mock_entry_points = MagicMock(return_value=[mock_ep])

        with patch("importlib.metadata.entry_points", mock_entry_points):
            result = discover_plugins()
            assert len(result["language"]) >= 1

    def test_discovers_analyzer_plugin(self):
        class TestAnalyzer(AnalyzerPlugin):
            @property
            def name(self):
                return "custom-linter"

            def analyze(self, symbols, callers, callees, source):
                return {}

        mock_ep = MagicMock()
        mock_ep.load.return_value = TestAnalyzer
        mock_entry_points = MagicMock(return_value=[mock_ep])

        with patch("importlib.metadata.entry_points", mock_entry_points):
            result = discover_plugins()
            assert len(result["analyzer"]) >= 1

    def test_load_failure_is_handled_gracefully(self):
        mock_ep = MagicMock()
        mock_ep.load.side_effect = ImportError("No module named 'foo'")
        mock_ep.name = "broken-plugin"
        mock_entry_points = MagicMock(return_value=[mock_ep])

        with patch("importlib.metadata.entry_points", mock_entry_points):
            # Should not raise
            result = discover_plugins()
            assert result == {"language": [], "analyzer": []}

    def test_non_plugin_entry_ignored(self):
        class NotAPlugin:
            pass

        mock_ep = MagicMock()
        mock_ep.load.return_value = lambda: NotAPlugin()
        mock_entry_points = MagicMock(return_value=[mock_ep])

        with patch("importlib.metadata.entry_points", mock_entry_points):
            result = discover_plugins()
            assert result == {"language": [], "analyzer": []}

    def test_typeerror_entry_points_fallback(self):
        """Test Python < 3.12 compatibility path (TypeError on group= kwarg)."""
        call_count = [0]

        def fake_entry_points(group=None):
            call_count[0] += 1
            if call_count[0] == 1:
                raise TypeError("unexpected keyword argument 'group'")
            # Fallback path: return something with .get()
            mock_result = MagicMock()
            mock_result.get.return_value = []
            return mock_result

        with patch("importlib.metadata.entry_points", fake_entry_points):
            result = discover_plugins()
            assert isinstance(result, dict)
            assert "language" in result
            assert "analyzer" in result


class TestLanguagePluginABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            LanguagePlugin()

    def test_concrete_must_implement_language(self):
        class Partial(LanguagePlugin):
            @property
            def extensions(self):
                return [".kt"]

        with pytest.raises(TypeError):
            Partial()

    def test_concrete_must_implement_extensions(self):
        class Partial(LanguagePlugin):
            @property
            def language(self):
                return "kotlin"

        with pytest.raises(TypeError):
            Partial()

    def test_concrete_must_implement_extract(self):
        class Partial(LanguagePlugin):
            @property
            def language(self):
                return "kotlin"

            @property
            def extensions(self):
                return [".kt"]

        with pytest.raises(TypeError):
            Partial()

    def test_valid_concrete_implementation_instantiates(self):
        class FullLanguage(LanguagePlugin):
            @property
            def language(self):
                return "kotlin"

            @property
            def extensions(self):
                return [".kt"]

            def extract(self, file_path, tree, source_bytes, language):
                return MagicMock()

        plugin = FullLanguage()
        assert plugin.language == "kotlin"
        assert plugin.extensions == [".kt"]


class TestAnalyzerPluginABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            AnalyzerPlugin()

    def test_concrete_must_implement_name(self):
        class Partial(AnalyzerPlugin):
            def analyze(self, symbols, callers, callees, source):
                return {}

        with pytest.raises(TypeError):
            Partial()

    def test_concrete_must_implement_analyze(self):
        class Partial(AnalyzerPlugin):
            @property
            def name(self):
                return "test-analyzer"

        with pytest.raises(TypeError):
            Partial()

    def test_valid_concrete_implementation_instantiates(self):
        class FullAnalyzer(AnalyzerPlugin):
            @property
            def name(self):
                return "test-analyzer"

            def analyze(self, symbols, callers, callees, source):
                return {"findings": []}

        plugin = FullAnalyzer()
        assert plugin.name == "test-analyzer"
