"""Tests for CLI shared utilities."""
import hashlib
from unittest.mock import MagicMock

from memorygraph.cli.shared import (
    _collect_files,
    _compute_hash,
    _extract_summary,
    _load_gitignore_patterns,
    _node_to_cyto,
    _should_exclude,
)
from memorygraph.parsing.registry import LanguageRegistry


class TestLoadGitignorePatterns:
    def test_no_gitignore_file(self, tmp_path):
        patterns = _load_gitignore_patterns(str(tmp_path))
        assert patterns == []

    def test_reads_gitignore_patterns(self, tmp_path):
        gi = tmp_path / ".gitignore"
        gi.write_text("*.pyc\n# comment\nnode_modules/\n")
        patterns = _load_gitignore_patterns(str(tmp_path))
        assert patterns == ["*.pyc", "node_modules/"]


class TestShouldExclude:
    def test_excludes_always_exclude_dirs(self, tmp_path):
        assert _should_exclude("node_modules/foo/index.js", str(tmp_path), []) is True
        assert _should_exclude(".git/config", str(tmp_path), []) is True
        assert _should_exclude("src/main.py", str(tmp_path), []) is False

    def test_excludes_by_gitignore_pattern(self, tmp_path):
        assert _should_exclude("dist/output.js", str(tmp_path), ["dist/"]) is True
        assert _should_exclude("src/main.py", str(tmp_path), ["*.py"]) is True
        assert _should_exclude("src/main.js", str(tmp_path), ["*.py"]) is False

    def test_excludes_subdirectory_pattern(self, tmp_path):
        assert _should_exclude("build/classes/Main.class", str(tmp_path), ["build/"]) is True


class TestCollectFiles:
    def test_collects_python_files(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "utils.py").write_text("def foo(): pass")
        (tmp_path / "README.md").write_text("# README")
        # Create .git directory that should be excluded
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("...")

        registry = LanguageRegistry()
        files = _collect_files(str(tmp_path), registry)
        py_files = [f for f in files if f.endswith(".py")]
        assert len(py_files) == 2

    def test_respects_gitignore(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "dist").mkdir()
        (tmp_path / "dist" / "bundle.js").write_text("...")
        (tmp_path / ".gitignore").write_text("dist/\n")

        registry = LanguageRegistry()
        files = _collect_files(str(tmp_path), registry)
        assert not any("dist" in f for f in files)


class TestComputeHash:
    def test_computes_sha256(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("hello world")
        h = _compute_hash(str(f))
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert h == expected

    def test_hash_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        h = _compute_hash(str(f))
        expected = hashlib.sha256(b"").hexdigest()
        assert h == expected


class TestExtractSummary:
    def test_python_docstring(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text('"""This is a module docstring."""\ndef foo(): pass\n')
        summary = _extract_summary(f, "python")
        assert "This is a module docstring" in summary

    def test_python_no_docstring(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("import os\ndef foo(): pass\n")
        summary = _extract_summary(f, "python")
        assert summary  # Should return some text

    def test_c_style_block_comment(self, tmp_path):
        f = tmp_path / "main.ts"
        f.write_text("/**\n * TypeScript module\n * description here\n */\nconst x = 1;\n")
        summary = _extract_summary(f, "typescript")
        assert "TypeScript module description here" in summary

    def test_single_line_comment(self, tmp_path):
        f = tmp_path / "main.go"
        f.write_text("// Package main provides entry point\npackage main\n")
        summary = _extract_summary(f, "go")
        assert "Package main provides entry point" in summary

    def test_hash_comment(self, tmp_path):
        f = tmp_path / "script.sh"
        f.write_text("# This script does things\necho hello\n")
        summary = _extract_summary(f, "shell")
        assert "This script does things" in summary

    def test_fallback_to_first_code_line(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("just some text content here\nmore text\n")
        summary = _extract_summary(f, "text")
        assert summary  # Should return something

    def test_missing_file(self, tmp_path):
        f = tmp_path / "nonexistent.py"
        summary = _extract_summary(f, "python")
        assert "python source file" in summary.lower()

    def test_python_syntax_error_fallback(self, tmp_path):
        """SyntaxError in Python source should be caught, fall through to comments."""
        f = tmp_path / "broken.py"
        f.write_text("def broken(:\n    return")
        summary = _extract_summary(f, "python")
        assert summary  # Should still return something (first non-import line)

    def test_import_only_file_fallback(self, tmp_path):
        """File with only import lines should use language fallback string."""
        f = tmp_path / "imports_only.py"
        f.write_text("import os\nfrom sys import path\n")
        summary = _extract_summary(f, "python")
        assert "python source file" in summary.lower()

    def test_gitignore_excludes_matching_files(self, tmp_path):
        """Files matching gitignore patterns are excluded (L57 continue path)."""
        (tmp_path / "test_main.py").write_text("print('hello')")
        (tmp_path / "real_main.py").write_text("print('real')")
        (tmp_path / ".gitignore").write_text("test_*.py\n")
        registry = LanguageRegistry()
        files = _collect_files(str(tmp_path), registry)
        py_files = [f for f in files if f.endswith(".py")]
        assert len(py_files) == 1
        assert "real_main.py" in py_files[0]
        assert not any("test_main" in f for f in py_files)


class TestAnalyzeFilesSyntaxError:
    """Test _analyze_files with SyntaxError in AST parse (shared.py:153-154)."""

    def test_syntax_error_in_ast_parse_fallback(self, tmp_path):
        """Tree-sitter can extract symbols but ast.parse fails → empty tree fallback."""
        from unittest import mock

        from memorygraph.cli.shared import _analyze_files

        f = tmp_path / "broken.py"
        # tree-sitter error-recovery can still find a function def,
        # but ast.parse will fail because the function body is incomplete
        f.write_text("def ok_func():\n    pass\n\ndef broken_func(\n")

        mock_mgr = mock.MagicMock()
        mock_mgr.get_symbols_for_file.return_value = [
            {"qualified_name": "ok_func", "kind": "function",
             "parent_class": None, "start_line": 1},
            {"qualified_name": "broken_func", "kind": "function",
             "parent_class": None, "start_line": 4},
        ]
        mock_mgr.get_callers.return_value = []
        mock_mgr.get_callees.return_value = []

        try:
            results = _analyze_files(str(tmp_path), [str(f)])
        except ImportError:
            import pytest
            pytest.skip("radon or other dependency not available")
        # Should not crash — SyntaxError is caught and replaced with empty tree
        assert isinstance(results, int)


class TestNodeToCyto:
    def test_basic_node(self):
        sem_store = MagicMock()
        sem_store.load_all.return_value = []
        node = {
            "qualified_name": "foo.bar",
            "kind": "function",
            "start_line": 42,
            "file_path": "/src/main.py",
        }
        result = _node_to_cyto(node, sem_store)
        assert result["id"] == "foo.bar"
        assert result["kind"] == "function"
        assert result["line"] == 42
        assert result["file"] == "/src/main.py"

    def test_node_with_role_from_semantic(self):

        doc = MagicMock()
        doc.module_roles = {"foo.bar": "controller"}
        doc.metrics = None
        sem_store = MagicMock()
        sem_store.load_all.return_value = [doc]

        node = {
            "qualified_name": "foo.bar",
            "kind": "function",
            "start_line": 10,
        }
        result = _node_to_cyto(node, sem_store)
        assert result["role"] == "controller"

    def test_node_with_complexity(self):
        doc = MagicMock()
        doc.module_roles = {}
        doc.metrics = {"complexity": [{"name": "bar", "complexity": 15, "rank": "C"}]}
        sem_store = MagicMock()
        sem_store.load_all.return_value = [doc]

        node = {
            "qualified_name": "foo.bar",
            "kind": "method",
            "name": "bar",
            "start_line": 10,
        }
        result = _node_to_cyto(node, sem_store)
        assert result["complexity"] == 15
        assert result["rank"] == "C"
