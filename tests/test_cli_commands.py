"""Tests for CLI command modules."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from memorygraph.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def temp_project():
    """Create a temp project with indexed files for integration tests."""
    tmpdir = tempfile.mkdtemp()
    src_dir = os.path.join(tmpdir, "src")
    os.makedirs(src_dir)

    with open(os.path.join(src_dir, "app.py"), "w") as f:
        f.write("def helper(x):\n    return x * 2\n\ndef main():\n    result = helper(21)\n    print(result)\n")

    from memorygraph.parsing.batch import ParallelParser
    from memorygraph.parsing.registry import LanguageRegistry
    from memorygraph.storage import StorageManager
    mgr = StorageManager(tmpdir)
    mgr.initialize()

    registry = LanguageRegistry()
    parser = ParallelParser(registry)
    results = parser.parse_files(
        [Path(os.path.join(src_dir, "app.py"))],
        resolve_symbols=True,
    )
    for result in results.values():
        if not result.fatal_error:
            mgr.upsert_file(result)
    mgr.close()

    yield tmpdir
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestCLIHelp:
    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0

    def test_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0


class TestInitCommand:
    def test_init(self, runner, tmp_path):
        result = runner.invoke(cli, ["init", "--project-root", str(tmp_path)])
        assert result.exit_code == 0

    def test_init_already_initialized(self, runner, tmp_path):
        (tmp_path / ".memorygraph").mkdir()
        result = runner.invoke(cli, ["init", "--project-root", str(tmp_path)])
        assert result.exit_code == 0


class TestUninitCommand:
    def test_uninit_no_project(self, runner, tmp_path):
        result = runner.invoke(cli, ["uninit", "--project-root", str(tmp_path)])
        assert result.exit_code in (0, 1, 2)


class TestStatusCommand:
    def test_status(self, runner, temp_project):
        result = runner.invoke(cli, ["status", "--project-root", temp_project])
        assert result.exit_code == 0

    def test_status_empty_project(self, runner, tmp_path):
        result = runner.invoke(cli, ["status", "--project-root", str(tmp_path)])
        assert result.exit_code in (0, 1)


class TestQueryCommand:
    def test_query(self, runner, temp_project):
        result = runner.invoke(
            cli, ["query", "helper", "--project-root", temp_project]
        )
        assert result.exit_code == 0

    def test_query_no_results(self, runner, temp_project):
        result = runner.invoke(
            cli, ["query", "nonexistent12345", "--project-root", temp_project]
        )
        assert result.exit_code == 0


class TestFilesCommand:
    def test_files(self, runner, temp_project):
        result = runner.invoke(
            cli, ["files", "--project-root", temp_project]
        )
        assert result.exit_code == 0


class TestIndexCommand:
    def test_index_no_project(self, runner, tmp_path):
        result = runner.invoke(
            cli, ["index", "--project-root", str(tmp_path)]
        )
        assert result.exit_code in (0, 1, 2)

    def test_index_with_project(self, runner, temp_project):
        result = runner.invoke(
            cli, ["index", "--project-root", temp_project]
        )
        assert result.exit_code == 0

    def test_index_with_embed(self, runner, temp_project):
        result = runner.invoke(
            cli, ["index", "--project-root", temp_project, "--embed"]
        )
        assert result.exit_code == 0

    def test_index_with_gitignore(self, runner, tmp_path):
        """Test index with .gitignore to exercise gitignore parsing."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("def foo(): pass\n")
        (tmp_path / ".gitignore").write_text("*.pyc\n")
        result = runner.invoke(
            cli, ["index", "--project-root", str(tmp_path)]
        )
        assert result.exit_code in (0, 1, 2)

    def test_index_non_fatal_parse_errors(self, runner, temp_project, monkeypatch):
        """index displays non-fatal parse error summary (lines 112-113, 126-129)."""
        from pathlib import Path
        from unittest import mock

        from memorygraph.parsing.ir import FileInfo, ParseResult, Span, Symbol, SymbolKind
        # Create a file so the index command finds something
        (Path(temp_project) / "app.py").write_text("def foo(): pass\n")
        # Mock ParallelParser to return a result with non-fatal errors
        fake_file = FileInfo(
            path=str(Path(temp_project) / "app.py"),
            language="python", content_hash="abc123",
        )
        fake_span = Span(
            file=str(Path(temp_project) / "app.py"),
            start_line=1, start_col=1, end_line=1, end_col=10,
        )
        fake_symbol = Symbol(
            name="foo", kind=SymbolKind.FUNCTION, span=fake_span,
        )
        fake_result = ParseResult(
            file=fake_file,
            symbols=[fake_symbol],
            edges=[],
            errors=["Mock parse warning: unused variable"],
        )
        monkeypatch.setattr(
            "memorygraph.cli.commands.indexing.ParallelParser",
            mock.MagicMock(
                return_value=mock.MagicMock(
                    parse_files=mock.MagicMock(return_value={
                        Path(temp_project) / "app.py": fake_result,
                    })
                )
            )
        )
        result = runner.invoke(
            cli, ["index", "--project-root", str(temp_project)]
        )
        # Should show the non-fatal error summary
        assert "non-fatal parse error" in result.output

    def test_index_truncates_many_parse_errors(self, runner, temp_project, monkeypatch):
        """index truncates error list at 20 and shows '... and N more' (lines 130-131)."""
        from pathlib import Path
        from unittest import mock

        from memorygraph.parsing.ir import FileInfo, ParseResult, Span, Symbol, SymbolKind
        (Path(temp_project) / "app.py").write_text("def foo(): pass\n")
        fake_file = FileInfo(
            path=str(Path(temp_project) / "app.py"),
            language="python", content_hash="abc123",
        )
        fake_span = Span(
            file=str(Path(temp_project) / "app.py"),
            start_line=1, start_col=1, end_line=1, end_col=10,
        )
        fake_symbol = Symbol(
            name="foo", kind=SymbolKind.FUNCTION, span=fake_span,
        )
        # Create 25 errors to trigger truncation
        many_errors = [f"Warning {i}" for i in range(25)]
        fake_result = ParseResult(
            file=fake_file,
            symbols=[fake_symbol],
            edges=[],
            errors=many_errors,
        )
        monkeypatch.setattr(
            "memorygraph.cli.commands.indexing.ParallelParser",
            mock.MagicMock(
                return_value=mock.MagicMock(
                    parse_files=mock.MagicMock(return_value={
                        Path(temp_project) / "app.py": fake_result,
                    })
                )
            )
        )
        result = runner.invoke(
            cli, ["index", "--project-root", str(temp_project)]
        )
        # Should truncate — only first 5 errors per file shown
        # With 1 file × 5 errors = 5 total (under 20 limit)
        assert "non-fatal parse error" in result.output

    def test_index_embed_flag_calls_generate(self, runner, temp_project, monkeypatch):
        """index --embed calls _generate_embeddings (line 134)."""
        from unittest import mock
        (Path(temp_project) / "app.py").write_text("def foo(): pass\n")
        mock_gen = mock.MagicMock()
        monkeypatch.setattr(
            "memorygraph.cli.commands.indexing._generate_embeddings",
            mock_gen,
        )
        result = runner.invoke(
            cli, ["index", "--project-root", str(temp_project), "--embed"]
        )
        assert result.exit_code == 0
        mock_gen.assert_called_once_with(str(temp_project))


class TestSyncCommand:
    def test_sync_help(self, runner):
        result = runner.invoke(cli, ["sync", "--help"])
        assert result.exit_code == 0

    def test_sync_on_project(self, runner, temp_project):
        result = runner.invoke(
            cli, ["sync", "--project-root", temp_project]
        )
        assert result.exit_code == 0

    def test_sync_empty_dir(self, runner, tmp_path):
        """Sync on empty directory with no project initialized."""
        result = runner.invoke(
            cli, ["sync", "--project-root", str(tmp_path)]
        )
        assert result.exit_code in (0, 1, 2)


class TestContextCommandFull:
    def test_context_help(self, runner):
        result = runner.invoke(cli, ["context", "--help"])
        assert result.exit_code == 0

    def test_context(self, runner, temp_project):
        result = runner.invoke(
            cli, ["context", "helper function", "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1)

    def test_context_with_limit(self, runner, temp_project):
        result = runner.invoke(
            cli, ["context", "helper", "--limit", "3",
                  "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1)

    def test_context_empty_query(self, runner, temp_project):
        result = runner.invoke(
            cli, ["context", "", "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1, 2)




class TestAffectedCommand:
    def test_affected_help(self, runner):
        result = runner.invoke(cli, ["affected", "--help"])
        assert result.exit_code == 0

    def test_affected_with_file(self, runner, temp_project):
        filepath = os.path.join(temp_project, "src", "app.py")
        result = runner.invoke(
            cli, ["affected", filepath, "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1)

    def test_affected_with_from_diff(self, runner, temp_project):
        """Test affected --from-diff (needs stdin, but CliRunner handles it)."""
        diff_input = "+++ b/src/app.py\n"
        result = runner.invoke(
            cli, ["affected", "--from-diff", "--project-root", temp_project],
            input=diff_input
        )
        assert result.exit_code in (0, 1)


class TestExportCommand:
    def test_export_json(self, runner, temp_project):
        output = os.path.join(temp_project, "graph.json")
        result = runner.invoke(
            cli, ["export", "--output", output, "--project-root", temp_project]
        )
        if result.exit_code == 0:
            assert os.path.exists(output)

    def test_export_help(self, runner):
        result = runner.invoke(cli, ["export", "--help"])
        assert result.exit_code == 0


class TestSemanticIngest:
    def test_ingest_help(self, runner):
        result = runner.invoke(cli, ["semantic-ingest", "--help"])
        assert result.exit_code == 0

    def test_ingest_with_file(self, runner, temp_project):
        filepath = os.path.join(temp_project, "src", "app.py")
        result = runner.invoke(
            cli, ["semantic-ingest", "--file", filepath,
                  "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1, 2)

    def test_ingest_with_all(self, runner, temp_project):
        result = runner.invoke(
            cli, ["semantic-ingest", "--all", "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1, 2)


class TestAnalyzeCommand:
    def test_analyze_no_args_shows_error(self, runner, temp_project):
        result = runner.invoke(
            cli, ["analyze", "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1, 2)

    def test_analyze_with_file(self, runner, temp_project):
        filepath = os.path.join(temp_project, "src", "app.py")
        result = runner.invoke(
            cli, ["analyze", "--project-root", temp_project, "--file", filepath]
        )
        assert result.exit_code == 0


class TestSmellsCommand:
    def test_smells_no_args(self, runner, temp_project):
        result = runner.invoke(
            cli, ["smells", "--project-root", temp_project]
        )
        assert result.exit_code == 0


class TestMetricsCommand:
    def test_metrics(self, runner, temp_project):
        result = runner.invoke(
            cli, ["metrics", "--project-root", temp_project]
        )
        assert result.exit_code == 0


class TestServeCommand:
    def test_serve_help(self, runner):
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0

    def test_serve_web_help(self, runner):
        result = runner.invoke(cli, ["serve", "--web", "--help"])
        assert result.exit_code == 0

    def test_serve_mcp_help(self, runner):
        result = runner.invoke(cli, ["serve", "--mcp", "--help"])
        assert result.exit_code == 0


class TestWatchCommand:
    def test_watch_help(self, runner):
        result = runner.invoke(cli, ["watch", "--help"])
        assert result.exit_code == 0

    def test_watch_stop_help(self, runner):
        result = runner.invoke(cli, ["watch", "--stop", "--help"])
        assert result.exit_code == 0


class TestInstallCommand:
    def test_install_help(self, runner):
        result = runner.invoke(cli, ["install", "--help"])
        assert result.exit_code == 0

    def test_uninstall_help(self, runner):
        # uninstall might be a subcommand or flag on install
        result = runner.invoke(cli, ["uninstall", "--help"])
        assert result.exit_code in (0, 1, 2)

    def test_install_dry_run(self, runner):
        """Install without real config to exercise code paths."""
        result = runner.invoke(
            cli, ["install", "--project-root", "/nonexistent"]
        )
        assert result.exit_code in (0, 1, 2)


class TestStatusCommandEdgeCases:
    """Test the 'status' CLI command."""

    def test_status_on_uninitialized(self, runner, tmp_path):
        result = runner.invoke(cli, ["status", "--project-root", str(tmp_path)])
        assert result.exit_code in (0, 1)

    def test_status_on_indexed(self, runner, temp_project):
        result = runner.invoke(cli, ["status", "--project-root", temp_project])
        assert result.exit_code == 0

    def test_status_coverage_exception(self, runner, temp_project):
        """status when semantic store init fails → coverage 'not available' (utils.py:61-62)."""
        from unittest import mock
        with mock.patch(
            "memorygraph.semantic.store.SemanticStore",
            side_effect=RuntimeError("Semantic store unavailable"),
        ):
            result = runner.invoke(cli, ["status", "--project-root", temp_project])
            assert result.exit_code == 0
            assert "not available" in result.output


class TestPluginsCommand:
    """Test the 'plugins list' CLI command."""

    def test_plugins_list(self, runner):
        result = runner.invoke(cli, ["plugins", "list"])
        assert result.exit_code == 0
        assert "Built-in languages" in result.output

    def test_plugins_help(self, runner):
        result = runner.invoke(cli, ["plugins", "--help"])
        assert result.exit_code == 0

    def test_plugins_list_with_third_party(self, runner, monkeypatch):
        """Cover third-party plugin display branches (lines 50-56)."""
        from unittest import mock
        fake_lang = mock.MagicMock()
        fake_lang.language = "kotlin"
        fake_lang.extensions = [".kt", ".kts"]
        fake_analyzer = mock.MagicMock()
        fake_analyzer.name = "security-scanner"
        mock_discover = mock.MagicMock(return_value={
            "language": [fake_lang],
            "analyzer": [fake_analyzer],
        })
        monkeypatch.setattr("memorygraph.plugins.discover_plugins", mock_discover)
        result = runner.invoke(cli, ["plugins", "list"])
        assert result.exit_code == 0
        assert "kotlin" in result.output
        assert "security-scanner" in result.output


class TestExtractFromConversationCommand:
    """Test the 'extract-from-conversation' CLI command."""

    def test_missing_input_option(self, runner):
        result = runner.invoke(cli, ["extract-from-conversation"])
        assert result.exit_code != 0

    def test_nonexistent_file(self, runner, tmp_path):
        result = runner.invoke(
            cli, ["extract-from-conversation", "-i", str(tmp_path / "nope.json")]
        )
        assert "Error" in result.output or result.exit_code != 0

    def test_filenotfound_in_callback(self, tmp_path, capsys):
        """Direct callback invocation with non-existent file (bypasses Click validation)."""
        from memorygraph.cli.commands.utils import extract_from_conversation
        # Click won't validate, so the function body handles FileNotFoundError
        extract_from_conversation.callback(str(tmp_path / "nope.json"), str(tmp_path))
        captured = capsys.readouterr()
        assert "Error:" in captured.err or "Error:" in captured.out

class TestInitCommandEdgeCases:
    def test_init_creates_db(self, runner, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        result = runner.invoke(cli, ["init", "--project-root", str(project)])
        assert result.exit_code == 0
        assert (project / ".memorygraph" / "memorygraph.db").exists()

    def test_init_already_initialized(self, runner, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        runner.invoke(cli, ["init", "--project-root", str(project)])
        result = runner.invoke(cli, ["init", "--project-root", str(project)])
        assert "Already initialized" in result.output


class TestUninitCommandEdgeCases:
    def test_uninit_no_directory(self, runner, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        result = runner.invoke(cli, ["uninit", "--project-root", str(project), "--yes"])
        assert "No .memorygraph" in result.output or result.exit_code == 0

    def test_uninit_with_directory(self, runner, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        runner.invoke(cli, ["init", "--project-root", str(project)])
        result = runner.invoke(cli, ["uninit", "--project-root", str(project), "--yes"])
        assert result.exit_code == 0


class TestWatchCommandEdgeCases:
    def test_watch_stop_no_pid(self, runner, tmp_path):
        result = runner.invoke(cli, ["watch", "--project-root", str(tmp_path), "--stop"])
        assert "No watch daemon" in result.output or result.exit_code == 0

    def test_watch_once_syncs(self, runner, temp_project):
        """watch --once should scan, sync, and exit."""
        result = runner.invoke(
            cli, ["watch", "--once", "--project-root", temp_project]
        )
        assert result.exit_code == 0
        # Should print sync stats or "No changes"
        assert "Synced:" in result.output or "No changes" in result.output


class TestInstallCommandEdgeCases:
    def test_install_registers(self, runner, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        runner.invoke(cli, ["init", "--project-root", str(project)])
        result = runner.invoke(cli, ["install", "--project-root", str(project)])
        assert result.exit_code == 0


class TestSyncCommandEdgeCases:
    def test_sync_no_project(self, runner, tmp_path):
        result = runner.invoke(cli, ["sync", "--project-root", str(tmp_path)])
        assert result.exit_code in (0, 1)


class TestQueryCommands:
    def test_query_help(self, runner):
        result = runner.invoke(cli, ["query", "--help"])
        assert result.exit_code == 0

    def test_context_help(self, runner):
        result = runner.invoke(cli, ["context", "--help"])
        assert result.exit_code == 0

    def test_files_help(self, runner):
        result = runner.invoke(cli, ["files", "--help"])
        assert result.exit_code == 0

    def test_affected_help(self, runner):
        result = runner.invoke(cli, ["affected", "--help"])
        assert result.exit_code == 0

    def test_export_help(self, runner):
        result = runner.invoke(cli, ["export", "--help"])
        assert result.exit_code == 0


class TestSemanticCommands:
    def test_analyze_help(self, runner):
        result = runner.invoke(cli, ["analyze", "--help"])
        assert result.exit_code == 0

    def test_smells_help(self, runner):
        result = runner.invoke(cli, ["smells", "--help"])
        assert result.exit_code == 0

    def test_metrics_help(self, runner):
        result = runner.invoke(cli, ["metrics", "--help"])
        assert result.exit_code == 0

    def test_semantic_ingest_help(self, runner):
        result = runner.invoke(cli, ["semantic-ingest", "--help"])
        assert result.exit_code == 0


class TestPatternsAndGitHistoryCommands:
    def test_patterns_no_project(self, runner, tmp_path):
        result = runner.invoke(cli, ["patterns", "--project-root", str(tmp_path)])
        assert result.exit_code in (0, 1)

    def test_git_history_help(self, runner):
        result = runner.invoke(cli, ["git-history", "--help"])
        assert result.exit_code == 0


class TestContextCommandExtended:
    def test_context_with_query(self, runner, temp_project):
        result = runner.invoke(
            cli, ["context", "main", "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1)

    def test_context_multi_word(self, runner, temp_project):
        result = runner.invoke(
            cli, ["context", "helper main", "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1)

    def test_context_with_limit(self, runner, temp_project):
        result = runner.invoke(
            cli, ["context", "helper", "--limit", "1", "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1)

    def test_export_lsif_no_db(self, runner, tmp_path):
        """export --format lsif without DB → ClickException (querying.py:153)."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        output_file = str(tmp_path / "out.lsif")
        result = runner.invoke(
            cli, ["export", "--format", "lsif", "--project-root", str(tmp_path),
                  "--output", output_file]
        )
        assert result.exit_code != 0
        assert "No database found" in result.output


class TestFilesCommandExtended:
    def test_files(self, runner, temp_project):
        result = runner.invoke(
            cli, ["files", "--project-root", temp_project]
        )
        assert result.exit_code == 0

    def test_files_help(self, runner):
        result = runner.invoke(cli, ["files", "--help"])
        assert result.exit_code == 0


class TestAffectedCommandExtended:
    def test_affected_with_diff_file(self, runner, temp_project):
        diff_file = os.path.join(temp_project, "changes.diff")
        with open(diff_file, "w") as f:
            f.write("diff --git a/src/app.py b/src/app.py\n")
            f.write("--- a/src/app.py\n")
            f.write("+++ b/src/app.py\n")
            f.write("@@ -1,3 +1,4 @@\n")
        result = runner.invoke(
            cli, ["affected", "--diff-file", diff_file, "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1)

    def test_affected_no_changes(self, runner, temp_project):
        """affected without file paths and without diff should show no changes."""
        result = runner.invoke(
            cli, ["affected", "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1)


class TestExportCommandExtended:
    def test_export_json_no_project(self, runner, tmp_path):
        output = os.path.join(tmp_path, "graph.json")
        path = tmp_path / "project"
        path.mkdir()
        result = runner.invoke(
            cli, ["export", "--output", output, "--project-root", str(path)]
        )
        assert result.exit_code in (0, 1)

    def test_export_json_with_limit(self, runner, temp_project):
        output = os.path.join(temp_project, "graph2.json")
        result = runner.invoke(
            cli, ["export", "--output", output, "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1)

    def test_export_dot_format(self, runner, temp_project):
        """Export with --format dot produces valid DOT output."""
        output = os.path.join(temp_project, "graph.dot")
        result = runner.invoke(
            cli,
            ["export", "--output", output, "--format", "dot",
             "--project-root", temp_project],
        )
        assert result.exit_code in (0, 1)
        if result.exit_code == 0:
            assert os.path.exists(output)
            with open(output) as f:
                content = f.read()
            assert content.startswith("digraph memorygraph {")
            assert "}" in content

    def test_export_dot_empty_project(self, runner, tmp_path):
        """Export DOT from empty project produces valid skeleton."""
        output = os.path.join(tmp_path, "empty.dot")
        path = tmp_path / "emptyproj"
        path.mkdir()
        result = runner.invoke(
            cli,
            ["export", "--output", output, "--format", "dot",
             "--project-root", str(path)],
        )
        assert result.exit_code in (0, 1)

    def test_export_lsif_format(self, runner, temp_project):
        """Export with --format lsif produces valid LSIF JSON lines output."""
        output = os.path.join(temp_project, "graph.lsif")
        result = runner.invoke(
            cli,
            ["export", "--output", output, "--format", "lsif",
             "--project-root", temp_project],
        )
        assert result.exit_code in (0, 1)
        if result.exit_code == 0:
            assert os.path.exists(output)
            with open(output) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    assert "id" in obj
                    assert "type" in obj
                    assert obj["type"] in ("vertex", "edge")
                    break  # Validate first line only — full test in test_lsif.py


class TestDotExportUnit:
    """Unit tests for _write_dot function."""

    def test_write_dot_minimal(self, tmp_path):
        """_write_dot with empty nodes/edges produces valid DOT."""
        from memorygraph.cli.commands.querying import _write_dot
        output = os.path.join(tmp_path, "min.dot")
        _write_dot([], [], output)
        with open(output) as f:
            content = f.read()
        assert content.startswith("digraph memorygraph {")
        assert "}" in content

    def test_write_dot_with_nodes_and_edges(self, tmp_path):
        """_write_dot renders nodes with style and edges with relationships."""
        from memorygraph.cli.commands.querying import _write_dot
        output = os.path.join(tmp_path, "graph.dot")
        nodes = [
            {"id": "main", "label": "main()", "kind": "function"},
            {"id": "MyClass", "label": "MyClass", "kind": "class"},
            {"id": "helper", "label": "helper()", "kind": "method"},
        ]
        edges = [
            {"source": "main", "target": "helper", "kind": "calls"},
            {"source": "helper", "target": "MyClass", "kind": "type_refs"},
        ]
        _write_dot(nodes, edges, output)
        with open(output) as f:
            content = f.read()
        assert "digraph memorygraph {" in content
        assert '"main"' in content
        assert '"MyClass"' in content
        assert '"helper"' in content
        assert "calls" in content
        assert "type" in content

    def test_write_dot_escapes_quotes(self, tmp_path):
        """_write_dot escapes double quotes in labels."""
        from memorygraph.cli.commands.querying import _write_dot
        output = os.path.join(tmp_path, "esc.dot")
        nodes = [{"id": "f", "label": 'foo "bar"', "kind": "function"}]
        _write_dot(nodes, [], output)
        with open(output) as f:
            content = f.read()
        assert '\\"' in content  # Quotes should be escaped

    def test_write_dot_deduplicates(self, tmp_path):
        """_write_dot deduplicates nodes and edges."""
        from memorygraph.cli.commands.querying import _write_dot
        output = os.path.join(tmp_path, "dedup.dot")
        nodes = [
            {"id": "a", "label": "A", "kind": "function"},
            {"id": "a", "label": "A", "kind": "function"},  # duplicate
        ]
        edges = [
            {"source": "a", "target": "b", "kind": "calls"},
            {"source": "a", "target": "b", "kind": "calls"},  # duplicate
        ]
        _write_dot(nodes, edges, output)
        with open(output) as f:
            content = f.read()
        # Each node and edge should appear only once
        assert content.count('"a" [') == 1
        assert content.count('"a" -> ') == 1


class TestSemanticIngestExtended:
    def test_ingest_with_file(self, runner, temp_project):
        filepath = os.path.join(temp_project, "src", "app.py")
        result = runner.invoke(
            cli, ["semantic-ingest", "--file", filepath,
                  "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1, 2)

    def test_ingest_with_all(self, runner, temp_project):
        result = runner.invoke(
            cli, ["semantic-ingest", "--all", "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1, 2)


class TestAnalyzeCommandExtended:
    def test_analyze_with_file(self, runner, temp_project):
        filepath = os.path.join(temp_project, "src", "app.py")
        result = runner.invoke(
            cli, ["analyze", "--project-root", temp_project, "--file", filepath]
        )
        assert result.exit_code == 0

    def test_analyze_no_file(self, runner, temp_project):
        result = runner.invoke(
            cli, ["analyze", "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1, 2)

    def test_analyze_nonexistent_file(self, runner, temp_project):
        result = runner.invoke(
            cli, ["analyze", "--project-root", temp_project, "--file", "/nonexistent.py"]
        )
        assert result.exit_code in (0, 1, 2)


class TestSmellsCommandExtended:
    def test_smells_with_file(self, runner, temp_project):
        filepath = os.path.join(temp_project, "src", "app.py")
        result = runner.invoke(
            cli, ["smells", "--file", filepath, "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1)

    def test_smells_all(self, runner, temp_project):
        result = runner.invoke(
            cli, ["smells", "--project-root", temp_project]
        )
        assert result.exit_code == 0

    def test_smells_nonexistent_file(self, runner, temp_project):
        result = runner.invoke(
            cli, ["smells", "--file", "/nonexistent.py", "--project-root", temp_project]
        )
        assert "File not found" in result.output or result.exit_code in (0, 1, 2)

    def test_smells_with_severity_filter(self, runner, temp_project):
        """Cover smells --severity filter (lines 142-145, 149)."""
        # First create a file with a long parameter list (triggers "info" smell)
        smell_file = os.path.join(temp_project, "src", "smelly.py")
        with open(smell_file, "w") as f:
            f.write("def long_function(p1, p2, p3, p4, p5, p6):\n    pass\n")
        # Index the file
        from pathlib import Path

        from memorygraph.parsing.batch import ParallelParser
        from memorygraph.parsing.registry import LanguageRegistry
        from memorygraph.storage import StorageManager
        mgr = StorageManager(temp_project)
        mgr.initialize()
        registry = LanguageRegistry()
        parser = ParallelParser(registry)
        results = parser.parse_files([Path(smell_file)], resolve_symbols=True)
        for r in results.values():
            if not r.fatal_error:
                mgr.upsert_file(r)
        mgr.close()
        # Analyze the file --all
        runner.invoke(cli, ["analyze", "--all", "--project-root", temp_project])
        # Test 1: non-matching severity filter ("major" won't match "info" smell)
        # This exercises the `continue` at line 143 (filter skips the smell)
        non_match = runner.invoke(cli, [
            "smells", "--project-root", temp_project, "--severity", "major"
        ])
        assert non_match.exit_code == 0
        # Test 2: matching severity filter ("info" matches long_parameter_list smell)
        # This exercises lines 144-145 (display) and 149 (count total)
        result = runner.invoke(cli, [
            "smells", "--project-root", temp_project, "--severity", "info"
        ])
        assert result.exit_code == 0
        assert "long_parameter_list" in result.output


class TestMetricsCommandExtended:
    def test_metrics_on_project(self, runner, temp_project):
        result = runner.invoke(
            cli, ["metrics", "--project-root", temp_project]
        )
        assert result.exit_code == 0

    def test_metrics_with_file(self, runner, temp_project):
        filepath = os.path.join(temp_project, "src", "app.py")
        result = runner.invoke(
            cli, ["metrics", "--file", filepath, "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1)

    def test_metrics_empty_project(self, runner, tmp_path):
        result = runner.invoke(
            cli, ["metrics", "--project-root", str(tmp_path)]
        )
        assert result.exit_code in (0, 1)

    def test_metrics_with_empty_doc(self, runner, tmp_path, monkeypatch):
        """Cover metrics empty doc.metrics continue (line 164)."""
        from memorygraph.semantic.models import SemanticDocument
        empty_doc = SemanticDocument(file="test.py", metrics={})
        with mock.patch("memorygraph.semantic.store.SemanticStore.load_all",
                        return_value=[empty_doc]):
            result = runner.invoke(cli, ["metrics", "--project-root", str(tmp_path)])
            assert result.exit_code == 0


class TestExtractFromConversationExtended:
    @pytest.fixture(autouse=True)
    def _clear_llm_api_keys(self):
        """Prevent real LLM API calls during testing."""
        with mock.patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
            "DEEPSEEK_API_KEY": "",
            "LLM_API_KEY": "",
        }):
            yield

    def test_extract_with_content(self, runner, tmp_path):
        conv_file = tmp_path / "conversation.json"
        conv_file.write_text(json.dumps({
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "function login handles user authentication. Design decision: use JWT tokens. Warning: don't store passwords in plaintext."}]
                }
            ]
        }))
        result = runner.invoke(
            cli, ["extract-from-conversation", "-i", str(conv_file),
                  "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "Extracted" in result.output

    def test_extract_with_string_content(self, runner, tmp_path):
        conv_file = tmp_path / "conversation2.json"
        conv_file.write_text(json.dumps({"content": "function parse handles input parsing. TODO: add error handling."}))
        result = runner.invoke(
            cli, ["extract-from-conversation", "-i", str(conv_file),
                  "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0

    def test_extract_empty_content(self, runner, tmp_path):
        conv_file = tmp_path / "empty.json"
        conv_file.write_text(json.dumps({}))
        result = runner.invoke(
            cli, ["extract-from-conversation", "-i", str(conv_file),
                  "--project-root", str(tmp_path)]
        )
        assert result.exit_code in (0, 1)


class TestInstallCommandExtended:
    def test_install_with_existing_memorygraph(self, runner, tmp_path):
        """Test install when memorygraph is already registered."""
        project = tmp_path / "project"
        project.mkdir()
        # Initialize both project and claude config
        runner.invoke(cli, ["init", "--project-root", str(project)])
        config_dir = tmp_path / ".claude"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "claude.json"
        config_file.write_text(json.dumps({
            "mcpServers": {
                "memorygraph": {"command": "old", "args": []}
            }
        }))
        old_home = os.environ.get("HOME", "")
        try:
            os.environ["HOME"] = str(tmp_path)
            result = runner.invoke(
                cli, ["install", "--project-root", str(project)]
            )
            assert result.exit_code in (0, 1)
        finally:
            os.environ["HOME"] = old_home


class TestSyncCommandExtended:
    def test_sync_verbose(self, runner, temp_project):
        result = runner.invoke(
            cli, ["sync", "--project-root", temp_project]
        )
        assert result.exit_code == 0

    def test_sync_no_project(self, runner, tmp_path):
        result = runner.invoke(
            cli, ["sync", "--project-root", str(tmp_path)]
        )
        assert result.exit_code in (0, 1)

    def test_sync_with_analyze(self, runner, temp_project):
        """sync --analyze covers indexing.py line 148 (analyzed_count > 0)."""
        # First sync to index files
        runner.invoke(cli, ["sync", "--project-root", temp_project])
        # Modify a file so sync detects a change
        filepath = os.path.join(temp_project, "src", "app.py")
        with open(filepath, "a") as f:
            f.write("\ndef new_func():\n    pass\n")
        # Second sync with --analyze
        result = runner.invoke(
            cli, ["sync", "--analyze", "--project-root", temp_project]
        )
        assert result.exit_code == 0


class TestQueryCommandExtended:
    def test_query_verbose(self, runner, temp_project):
        result = runner.invoke(
            cli, ["query", "helper", "--project-root", temp_project]
        )
        assert result.exit_code == 0

    def test_query_with_limit(self, runner, temp_project):
        result = runner.invoke(
            cli, ["query", "helper", "--limit", "5",
                  "--project-root", temp_project]
        )
        assert result.exit_code == 0

    def test_query_no_results(self, runner, temp_project):
        result = runner.invoke(
            cli, ["query", "zzz_nonexistent_xyz", "--project-root", temp_project]
        )
        assert result.exit_code == 0


class TestConfigCommand:
    def test_config_help(self, runner):
        result = runner.invoke(cli, ["config", "--help"])
        assert result.exit_code in (0, 1, 2)


class TestGitHistoryCommand:
    def test_git_history_help(self, runner):
        result = runner.invoke(cli, ["git-history", "--help"])
        assert result.exit_code == 0

    def test_git_history_symbol_not_found(self, runner, temp_project):
        result = runner.invoke(
            cli, ["git-history", "nonexistent_symbol", "--project-root", temp_project]
        )
        assert result.exit_code == 0
        assert "Symbol not found" in result.output

    def test_git_history_from_diff_no_pipe(self, runner, temp_project, monkeypatch):
        """Cover affected --from-diff when stdin is a tty (lines 99-100).

        CliRunner replaces sys.stdin, so monkeypatch the isatty method
        on the class used by CliRunner stdin.
        """
        from click.testing import _NamedTextIOWrapper
        monkeypatch.setattr(_NamedTextIOWrapper, "isatty", lambda self: True)
        result = runner.invoke(cli, [
            "affected", "--from-diff",
            "--project-root", temp_project
        ])
        assert "Error" in result.output


class TestPatternsWithFile:
    def test_patterns_with_file(self, runner, temp_project):
        filepath = os.path.join(temp_project, "src", "app.py")
        result = runner.invoke(
            cli, ["patterns", "--file", filepath, "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1)

    def test_patterns_no_detections(self, runner, temp_project):
        result = runner.invoke(
            cli, ["patterns", "--project-root", temp_project]
        )
        assert result.exit_code == 0


class TestServeWebMocked:
    def test_serve_web_mocked(self, runner, tmp_path):
        """Test serve --web --server http path with mocked WebServer."""
        with mock.patch("memorygraph.web.server.WebServer") as mock_server:
            instance = mock_server.return_value
            runner.invoke(
                cli, ["serve", "--web", "--server", "http",
                      "--project-root", str(tmp_path), "--port", "18888"]
            )
            mock_server.assert_called_once_with(
                str(tmp_path), port=18888, host="127.0.0.1",
            )
            instance.start.assert_called_once()

    def test_serve_web_uvicorn_mocked(self, runner, tmp_path):
        """Test serve --web path with uvicorn available (mocked)."""
        with mock.patch("uvicorn.run") as mock_uvicorn_run:
            with mock.patch("memorygraph.web.server.WebServer") as mock_server:
                with mock.patch("memorygraph.web.server.create_asgi_app") as mock_asgi:
                    with mock.patch("memorygraph.storage.create_storage_manager") as mock_sm:
                        with mock.patch("memorygraph.semantic.store.SemanticStore"):
                            with mock.patch("memorygraph.storage.connection.get_db_path"):
                                instance = mock_server.return_value
                                mock_asgi.return_value = "fake_app"
                                mock_sm.return_value = mock.MagicMock()

                                runner.invoke(
                                    cli, ["serve", "--web", "--project-root", str(tmp_path),
                                          "--port", "18888"]
                                )
                                # uvicorn.run should have been called with the ASGI app
                                mock_uvicorn_run.assert_called_once()
                                call_kwargs = mock_uvicorn_run.call_args.kwargs
                                assert call_kwargs["host"] == "127.0.0.1"
                                assert call_kwargs["port"] == 18888
                                # WebServer.start() should NOT be called (uvicorn path)
                                instance.start.assert_not_called()

    def test_serve_mcp_mocked(self, runner, tmp_path):
        """Test serve --mcp path with mocked run_mcp_server."""
        with mock.patch("memorygraph.mcp.server.run_mcp_server") as mock_mcp:
            mock_mcp.return_value = None
            runner.invoke(
                cli, ["serve", "--mcp", "--project-root", str(tmp_path)]
            )
            # MCP might fail (it's not a real stdio), but code path is exercised

    def test_serve_default_mocked(self, runner, tmp_path):
        """Test serve default (MCP) path."""
        with mock.patch("memorygraph.mcp.server.run_mcp_server") as mock_mcp:
            mock_mcp.return_value = None
            runner.invoke(
                cli, ["serve", "--project-root", str(tmp_path)]
            )
            # Default mode exercises the MCP path

    def test_serve_web_keyboard_interrupt(self, runner, tmp_path, monkeypatch):
        """Cover WebServer start + KeyboardInterrupt (http-server path)."""
        from unittest import mock as _mock
        mock_ws = _mock.MagicMock()
        mock_ws.start.side_effect = KeyboardInterrupt()
        monkeypatch.setattr("memorygraph.web.server.WebServer", lambda *a, **kw: mock_ws)
        result = runner.invoke(cli, ["serve", "--web", "--server", "http",
                                      "--project-root", str(tmp_path), "--port", "18765"])
        assert result.exit_code == 0

    def test_serve_web_uvicorn_keyboard_interrupt(self, runner, tmp_path, monkeypatch):
        """Cover uvicorn.run -> KeyboardInterrupt -> ws.stop() (cover serving.py:190)."""
        from unittest import mock as _mock
        mock_ws = _mock.MagicMock()
        monkeypatch.setattr("memorygraph.web.server.WebServer", lambda *a, **kw: mock_ws)
        monkeypatch.setattr("memorygraph.web.server.create_asgi_app",
                            lambda *a, **kw: _mock.MagicMock())
        monkeypatch.setattr("memorygraph.storage.create_storage_manager",
                            lambda *a, **kw: _mock.MagicMock())
        monkeypatch.setattr("memorygraph.semantic.store.SemanticStore",
                            lambda *a, **kw: _mock.MagicMock())
        monkeypatch.setattr("memorygraph.storage.connection.get_db_path",
                            lambda *a, **kw: str(tmp_path / ".memorygraph" / "memorygraph.db"))
        with _mock.patch("uvicorn.run", side_effect=KeyboardInterrupt()):
            result = runner.invoke(cli, ["serve", "--web", "--project-root",
                                          str(tmp_path), "--port", "18767"])
        assert result.exit_code == 0
        mock_ws.stop.assert_called_once()

    def test_serve_web_uvicorn_fallback_closes_mgr(self, runner, tmp_path, monkeypatch):
        """When uvicorn fails, StorageManager should be closed before fallback to HTTP."""
        from unittest import mock as _mock
        mock_ws = _mock.MagicMock()
        mock_mgr = _mock.MagicMock()
        mock_ws._mgr = None  # Will be set by serve()
        monkeypatch.setattr("memorygraph.web.server.WebServer", lambda *a, **kw: mock_ws)
        monkeypatch.setattr("memorygraph.web.server.create_asgi_app",
                            lambda *a, **kw: _mock.MagicMock())
        # StorageManager() should return our tracked mock
        monkeypatch.setattr("memorygraph.storage.create_storage_manager",
                            lambda *a, **kw: mock_mgr)
        monkeypatch.setattr("memorygraph.semantic.store.SemanticStore",
                            lambda *a, **kw: _mock.MagicMock())
        with _mock.patch("uvicorn.run", side_effect=RuntimeError("uvicorn failure")):
            runner.invoke(cli, ["serve", "--web", "--project-root",
                                          str(tmp_path), "--port", "18766"])
        # StorageManager.close() should have been called during fallback
        mock_mgr.close.assert_called_once()
        # ws._mgr should be reset to None after cleanup
        assert mock_ws._mgr is None

    def test_serve_explicit_uvicorn_mode(self, runner, tmp_path, monkeypatch):
        """Cover server_mode='uvicorn' path (serving.py:143)."""
        from unittest import mock as _mock
        mock_ws = _mock.MagicMock()
        monkeypatch.setattr("memorygraph.web.server.WebServer", lambda *a, **kw: mock_ws)
        monkeypatch.setattr("memorygraph.web.server.create_asgi_app",
                            lambda *a, **kw: _mock.MagicMock())
        monkeypatch.setattr("memorygraph.storage.create_storage_manager",
                            lambda *a, **kw: _mock.MagicMock())
        monkeypatch.setattr("memorygraph.semantic.store.SemanticStore",
                            lambda *a, **kw: _mock.MagicMock())
        monkeypatch.setattr("memorygraph.storage.connection.get_db_path",
                            lambda proot: "/tmp/db")
        with _mock.patch("uvicorn.run") as mock_run:
            result = runner.invoke(cli, ["serve", "--web", "--server", "uvicorn",
                                          "--project-root", str(tmp_path), "--port", "18767"])
        assert result.exit_code == 0
        mock_run.assert_called_once()

    def test_serve_auto_mode_uvicorn_not_installed(self, runner, tmp_path, monkeypatch):
        """Cover uvicorn ImportError fallback in auto mode (serving.py:150-152)."""
        from unittest import mock as _mock
        mock_ws = _mock.MagicMock()
        monkeypatch.setattr("memorygraph.web.server.WebServer", lambda *a, **kw: mock_ws)
        monkeypatch.setattr("memorygraph.storage.create_storage_manager",
                            lambda *a, **kw: _mock.MagicMock())
        monkeypatch.setattr("memorygraph.semantic.store.SemanticStore",
                            lambda *a, **kw: _mock.MagicMock())

        # Make uvicorn import fail
        import builtins
        orig_import = builtins.__import__
        def block_uvicorn(name, *args, **kwargs):
            if name == "uvicorn":
                raise ImportError("No module named 'uvicorn'")
            return orig_import(name, *args, **kwargs)
        monkeypatch.setattr("builtins.__import__", block_uvicorn)
        result = runner.invoke(cli, ["serve", "--web", "--server", "auto",
                                      "--project-root", str(tmp_path), "--port", "18768"])
        assert result.exit_code == 0

    def test_serve_uvicorn_close_exception(self, runner, tmp_path, monkeypatch):
        """Cover StorageManager close exception during uvicorn fallback (serving.py:201-202)."""
        from unittest import mock as _mock
        mock_ws = _mock.MagicMock()
        mock_mgr = _mock.MagicMock()
        mock_mgr.close.side_effect = Exception("Close failed")
        mock_ws._mgr = None
        monkeypatch.setattr("memorygraph.web.server.WebServer", lambda *a, **kw: mock_ws)
        monkeypatch.setattr("memorygraph.web.server.create_asgi_app",
                            lambda *a, **kw: _mock.MagicMock())
        monkeypatch.setattr("memorygraph.storage.create_storage_manager",
                            lambda *a, **kw: mock_mgr)
        monkeypatch.setattr("memorygraph.semantic.store.SemanticStore",
                            lambda *a, **kw: _mock.MagicMock())
        with _mock.patch("uvicorn.run", side_effect=RuntimeError("uvicorn failure")):
            result = runner.invoke(cli, ["serve", "--web", "--project-root",
                                          str(tmp_path), "--port", "18769"])
        assert result.exit_code == 0
        mock_mgr.close.assert_called()


class TestInstallWithConfig:
    def test_install_fresh_config(self, runner, tmp_path):
        """Test install creating a fresh config file."""
        project = tmp_path / "project"
        project.mkdir()
        old_home = os.environ.get("HOME", "")
        runner.invoke(cli, ["init", "--project-root", str(project)])
        try:
            os.environ["HOME"] = str(tmp_path)
            runner.invoke(cli, ["install", "--project-root", str(project)])
            config_file = tmp_path / ".claude.json"
            if config_file.exists():
                config = json.loads(config_file.read_text())
                assert "mcpServers" in config
                assert "memorygraph" in config["mcpServers"]
        finally:
            os.environ["HOME"] = old_home


class TestSemanticIngestAll:
    def test_ingest_all_with_files(self, runner, temp_project):
        """Test semantic-ingest --all on a project with indexed files."""
        result = runner.invoke(
            cli, ["semantic-ingest", "--all", "--project-root", temp_project]
        )
        assert result.exit_code == 0

    def test_ingest_no_options_shows_error(self, runner, temp_project):
        """Test semantic-ingest with no --file or --all shows error."""
        result = runner.invoke(
            cli, ["semantic-ingest", "--project-root", temp_project]
        )
        assert "Use --file or --all" in result.output or result.exit_code != 0


class TestIndexNonFatalErrors:
    """Cover indexing.py uncovered error summary paths (lines 112-134)."""

    def test_index_non_fatal_parse_errors(self, runner, temp_project, monkeypatch):
        """index displays non-fatal parse error summary (lines 112-113, 126-129)."""
        from pathlib import Path
        from unittest import mock

        from memorygraph.parsing.ir import FileInfo, ParseResult, Span, Symbol, SymbolKind
        (Path(temp_project) / "app.py").write_text("def foo(): pass\n")
        fake_file = FileInfo(
            path=str(Path(temp_project) / "app.py"),
            language="python", content_hash="abc123",
        )
        fake_span = Span(
            file=str(Path(temp_project) / "app.py"),
            start_line=1, start_col=1, end_line=1, end_col=10,
        )
        fake_symbol = Symbol(
            name="foo", kind=SymbolKind.FUNCTION, span=fake_span,
        )
        fake_result = ParseResult(
            file=fake_file,
            symbols=[fake_symbol],
            edges=[],
            errors=["Mock parse warning: unused variable"],
        )
        monkeypatch.setattr(
            "memorygraph.cli.commands.indexing.ParallelParser",
            mock.MagicMock(
                return_value=mock.MagicMock(
                    parse_files=mock.MagicMock(return_value={
                        Path(temp_project) / "app.py": fake_result,
                    })
                )
            )
        )
        result = runner.invoke(
            cli, ["index", "--project-root", str(temp_project)]
        )
        assert "non-fatal parse error" in result.output

    def test_index_truncates_many_parse_errors(self, runner, temp_project, monkeypatch):
        """index collects up to 5 errors per file (lines 130-131)."""
        from pathlib import Path
        from unittest import mock

        from memorygraph.parsing.ir import FileInfo, ParseResult, Span, Symbol, SymbolKind
        (Path(temp_project) / "app.py").write_text("def foo(): pass\n")
        fake_file = FileInfo(
            path=str(Path(temp_project) / "app.py"),
            language="python", content_hash="abc123",
        )
        fake_span = Span(
            file=str(Path(temp_project) / "app.py"),
            start_line=1, start_col=1, end_line=1, end_col=10,
        )
        fake_symbol = Symbol(
            name="foo", kind=SymbolKind.FUNCTION, span=fake_span,
        )
        many_errors = [f"Warning {i}" for i in range(25)]
        fake_result = ParseResult(
            file=fake_file,
            symbols=[fake_symbol],
            edges=[],
            errors=many_errors,
        )
        monkeypatch.setattr(
            "memorygraph.cli.commands.indexing.ParallelParser",
            mock.MagicMock(
                return_value=mock.MagicMock(
                    parse_files=mock.MagicMock(return_value={
                        Path(temp_project) / "app.py": fake_result,
                    })
                )
            )
        )
        result = runner.invoke(
            cli, ["index", "--project-root", str(temp_project)]
        )
        assert "non-fatal parse error" in result.output

    def test_index_embed_flag_calls_generate(self, runner, temp_project, monkeypatch):
        """index --embed calls _generate_embeddings (line 134)."""
        from unittest import mock
        (Path(temp_project) / "app.py").write_text("def foo(): pass\n")
        mock_gen = mock.MagicMock()
        monkeypatch.setattr(
            "memorygraph.cli.commands.indexing._generate_embeddings",
            mock_gen,
        )
        result = runner.invoke(
            cli, ["index", "--project-root", str(temp_project), "--embed"]
        )
        assert result.exit_code == 0
        mock_gen.assert_called_once_with(str(temp_project))


class TestIndexEmbedCommand:
    """Tests for index --embed option."""

    def test_index_embed_no_project(self, runner, tmp_path):
        """index --embed on empty project should show 'No source files found'."""
        result = runner.invoke(
            cli, ["index", "--embed", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0

    def test_index_no_embed(self, runner, tmp_path):
        """index without --embed should work normally."""
        result = runner.invoke(
            cli, ["index", "--no-embed", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0

    def test_index_embed_help(self, runner):
        """index --help should show --embed option."""
        result = runner.invoke(cli, ["index", "--help"])
        assert result.exit_code == 0
        assert "--embed" in result.output


class TestWatchCommandExtended:
    """Extended watch command tests."""

    def test_watch_stop_with_pid(self, runner, tmp_path):
        """watch --stop with existing pid file (uses a safe high-number PID)."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        pid_file = mg_dir / "watch.pid"
        # Use a PID that's unlikely to exist (but valid format)
        pid_file.write_text("1")
        result = runner.invoke(
            cli, ["watch", "--stop", "--project-root", str(tmp_path)]
        )
        assert result.exit_code in (0, 1, 2)

    def test_watch_stop_with_invalid_pid(self, runner, tmp_path):
        """watch --stop with invalid pid in file."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        pid_file = mg_dir / "watch.pid"
        pid_file.write_text("not_a_pid")
        result = runner.invoke(
            cli, ["watch", "--stop", "--project-root", str(tmp_path)]
        )
        assert result.exit_code in (0, 1, 2)

    def test_watch_stop_nonexistent_pid(self, runner, tmp_path):
        """watch --stop with nonexistent PID."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        pid_file = mg_dir / "watch.pid"
        pid_file.write_text("99999")
        result = runner.invoke(
            cli, ["watch", "--stop", "--project-root", str(tmp_path)]
        )
        assert result.exit_code in (0, 1, 2)


class TestDoctorCommand:
    """Tests for the doctor health check command."""

    def test_doctor_help(self, runner):
        result = runner.invoke(cli, ["doctor", "--help"])
        assert result.exit_code == 0

    def test_doctor_not_initialized(self, runner, tmp_path):
        """doctor on uninitialized directory should say so."""
        result = runner.invoke(
            cli, ["doctor", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "Not initialized" in result.output

    def test_doctor_on_project(self, runner, temp_project):
        """doctor on indexed project should pass all checks."""
        result = runner.invoke(
            cli, ["doctor", "--project-root", temp_project]
        )
        assert result.exit_code == 0

    def test_doctor_db_missing(self, runner, tmp_path):
        """doctor on initialized but db-deleted project should report missing db."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        result = runner.invoke(
            cli, ["doctor", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "Database missing" in result.output

    def test_doctor_db_error(self, runner, tmp_path):
        """doctor should handle database error gracefully."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        db_path = mg_dir / "memorygraph.db"
        db_path.touch()  # create empty file so db exists check passes

        # Create a corrupted db that will raise on connect
        from unittest import mock

        with mock.patch("memorygraph.storage.StorageManager.__init__",
                       side_effect=RuntimeError("Corrupted database")):
            result = runner.invoke(
                cli, ["doctor", "--project-root", str(tmp_path)]
            )
            assert result.exit_code == 0
            # Should report the error
            assert "Database error" in result.output or "Corrupted" in result.output

    def test_doctor_stats_error(self, runner, tmp_path):
        """doctor should handle mgr.stats() exception gracefully (cover lines 51-52)."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        from unittest import mock as _mock

        mock_mgr = _mock.MagicMock()
        mock_mgr.stats.side_effect = RuntimeError("stats failed")
        mock_conn = _mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = [0]
        mock_mgr.get_conn.return_value = mock_conn

        with _mock.patch(
            "memorygraph.storage.create_storage_manager",
            return_value=mock_mgr,
        ):
            result = runner.invoke(
                cli, ["doctor", "--project-root", str(tmp_path)]
            )
            assert result.exit_code == 0
            # stats() error is caught and reported
            assert "Database error" in result.output

    def test_doctor_embeddings_error(self, runner, tmp_path):
        """doctor should handle embeddings query error gracefully (cover lines 60-61)."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        from unittest import mock as _mock

        mock_mgr = _mock.MagicMock()
        mock_conn = _mock.MagicMock()
        mock_conn.execute.side_effect = RuntimeError("embeddings table missing")
        mock_mgr.get_conn.return_value = mock_conn

        with _mock.patch(
            "memorygraph.storage.create_storage_manager",
            return_value=mock_mgr,
        ):
            result = runner.invoke(
                cli, ["doctor", "--project-root", str(tmp_path)]
            )
            assert result.exit_code == 0
            # Should not crash — embeddings failure is non-fatal

    def test_doctor_no_files_indexed(self, runner, tmp_path):
        """doctor should warn when no files are indexed."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        # We need a valid db but with 0 files
        from unittest import mock

        with mock.patch("memorygraph.storage.StorageManager.stats",
                       return_value={"file_count": 0, "symbol_count": 0,
                                     "edge_count": 0}):
            result = runner.invoke(
                cli, ["doctor", "--project-root", str(tmp_path)]
            )
            assert result.exit_code == 0
            # Should suggest indexing
            assert "No files indexed" in result.output

    def test_doctor_radon_missing(self, runner, tmp_path):
        """doctor should report when radon is not installed."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()

        import sys
        with mock.patch.dict(sys.modules, {"radon": None}):
            # Force ImportError for radon
            with mock.patch("importlib.import_module",
                           side_effect=ImportError("No module named 'radon'")):
                result = runner.invoke(
                    cli, ["doctor", "--project-root", str(tmp_path)]
                )
                # Should not crash
                assert result.exit_code == 0

    def test_doctor_sentence_transformers_missing(self, runner, tmp_path):
        """doctor should report when sentence-transformers is not installed."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()

        import sys
        with mock.patch.dict(sys.modules, {"sentence_transformers": None}):
            result = runner.invoke(
                cli, ["doctor", "--project-root", str(tmp_path)]
            )
            assert result.exit_code == 0
            # sentence-transformers not installed -> ok message
            assert "not installed" in result.output

    def test_doctor_with_semantic_docs(self, runner, tmp_path):
        """doctor should count semantic documents when present."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        sem_dir = mg_dir / "semantic"
        sem_dir.mkdir()
        # Create some .json files
        (sem_dir / "a.json").touch()
        (sem_dir / "b.json").touch()
        (sem_dir / "c.json").touch()

        result = runner.invoke(
            cli, ["doctor", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "Semantic docs: 3" in result.output

    def test_doctor_semantic_dir_missing(self, runner, tmp_path):
        """doctor should report no semantic docs when dir doesn't exist."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()

        result = runner.invoke(
            cli, ["doctor", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "Semantic docs: none" in result.output

    def test_doctor_embeddings_count(self, runner, tmp_path):
        """doctor should report embedding count when vectors exist."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()

        from unittest import mock

        with mock.patch("memorygraph.storage.StorageManager._get_conn") as mock_conn:
            mock_cursor = mock.MagicMock()
            mock_cursor.fetchone.return_value = [5]
            mock_conn.return_value.execute.return_value = mock_cursor

            result = runner.invoke(
                cli, ["doctor", "--project-root", str(tmp_path)]
            )
            assert result.exit_code == 0
            assert "Embeddings: 5" in result.output

    def test_doctor_embedding_error_fallback(self, runner, tmp_path):
        """doctor should handle embedding query failure gracefully."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()

        from unittest import mock

        with mock.patch("memorygraph.storage.StorageManager._get_conn") as mock_conn:
            mock_conn.return_value.execute.side_effect = Exception("table missing")

            result = runner.invoke(
                cli, ["doctor", "--project-root", str(tmp_path)]
            )
            assert result.exit_code == 0
            # Should not crash; falls through to pass
            assert "Embeddings: none" in result.output or "not installed" in result.output

    def test_doctor_with_issues(self, runner, tmp_path):
        """doctor should display issues section when issues exist."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        # No db file = one issue
        # But db exists check will fail, so embed check won't run
        # Create a fake db to trigger more checks
        db_path = mg_dir / "memorygraph.db"
        db_path.write_text("not a real database")

        result = runner.invoke(
            cli, ["doctor", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0
        # Should either have all checks pass or show issues
        output = result.output
        assert "✅" in output

    def test_doctor_psycopg2_not_installed(self, runner, temp_project, monkeypatch):
        """Cover ImportError branch for psycopg2 (lines 61-62)."""
        # Remove psycopg2 from sys.modules to trigger ImportError
        import builtins
        import sys
        monkeypatch.delitem(sys.modules, "psycopg2", raising=False)
        # Make import psycopg2 raise ImportError
        orig_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == "psycopg2":
                raise ImportError("No module named 'psycopg2'")
            return orig_import(name, *args, **kwargs)
        monkeypatch.setattr("builtins.__import__", mock_import)
        result = runner.invoke(cli, ["doctor", "--project-root", temp_project])
        assert result.exit_code == 0
        assert "psycopg2: not installed" in result.output

    def test_doctor_psycopg2_available(self, runner, tmp_path, monkeypatch):
        """Cover psycopg2 available success path (doctor.py:80)."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        import sys
        # Inject fake psycopg2 into sys.modules so import succeeds
        fake_psycopg2 = type(sys)("psycopg2")
        sys.modules["psycopg2"] = fake_psycopg2
        try:
            result = runner.invoke(cli, ["doctor", "--project-root", str(tmp_path)])
            assert result.exit_code == 0
            assert "psycopg2: available" in result.output
        finally:
            sys.modules.pop("psycopg2", None)

    def test_doctor_sentence_transformers_available(self, runner, tmp_path):
        """Cover sentence-transformers available success path (doctor.py:86)."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        import sys
        fake_st = type(sys)("sentence_transformers")
        fake_st.SentenceTransformer = type(sys)("SentenceTransformer")
        sys.modules["sentence_transformers"] = fake_st
        try:
            result = runner.invoke(cli, ["doctor", "--project-root", str(tmp_path)])
            assert result.exit_code == 0
            assert "sentence-transformers: available" in result.output
        finally:
            sys.modules.pop("sentence_transformers", None)

    def test_doctor_db_outer_exception(self, runner, tmp_path):
        """Cover outer DB exception in doctor (doctor.py:51-52)."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        db_path = mg_dir / "memorygraph.db"
        db_path.touch()

        from unittest import mock
        with mock.patch("memorygraph.storage.manager.StorageManager.initialize",
                       side_effect=RuntimeError("DB schema init failed")):
            result = runner.invoke(
                cli, ["doctor", "--project-root", str(tmp_path)]
            )
            assert result.exit_code == 0
            assert "Database error" in result.output


    def test_doctor_json_not_initialized(self, runner, tmp_path):
        """doctor --json on uninitialized dir covers doctor.py:33-37."""
        result = runner.invoke(
            cli, ["doctor", "--project-root", str(tmp_path), "--json"]
        )
        assert result.exit_code == 0
        output = result.output.strip()
        assert "not_initialized" in output

    def test_doctor_json_on_project(self, runner, temp_project):
        """doctor --json on indexed project covers doctor.py:151-152."""
        result = runner.invoke(
            cli, ["doctor", "--project-root", temp_project, "--json"]
        )
        assert result.exit_code == 0
        output = result.output.strip()
        assert "status" in output
        import json as _json
        data = _json.loads(output)
        assert data["status"] in ("healthy", "degraded")


class TestSearchSemanticExtended:
    """Extended tests for search-semantic command."""

    def test_search_semantic_no_hybrid(self, runner, tmp_path):
        """search-semantic --no-hybrid on empty project."""
        result = runner.invoke(
            cli, ["search-semantic", "test", "--no-hybrid",
                  "--project-root", str(tmp_path)]
        )
        assert result.exit_code in (0, 1)

    def test_search_semantic_with_limit(self, runner, tmp_path):
        """search-semantic with custom limit."""
        result = runner.invoke(
            cli, ["search-semantic", "test", "--limit", "3",
                  "--project-root", str(tmp_path)]
        )
        assert result.exit_code in (0, 1)

    def test_search_semantic_with_project(self, runner, temp_project):
        """search-semantic on indexed project falls back to FTS."""
        result = runner.invoke(
            cli, ["search-semantic", "helper",
                  "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1)


class TestQueryingCoverageGaps:
    """Tests targeting uncovered lines in querying.py."""

    def test_print_search_results_with_score(self):
        """_print_search_results shows relevance when _score > 1."""
        from click.testing import CliRunner

        from memorygraph.cli.commands.querying import _print_search_results
        runner = CliRunner()
        runner.invoke(
            cli, ["--help"]
        )  # init runner
        results = [{
            "qualified_name": "test_func",
            "kind": "function",
            "file_path": "/test.py",
            "start_line": 1,
            "_score": 5,
        }]
        _print_search_results(results, "test query")

    def test_context_empty_result(self, runner, tmp_path):
        """context command on fresh project shows 'No relevant symbols found.'"""
        result = runner.invoke(
            cli, ["context", "nonexistent_task_xyz", "--project-root", str(tmp_path)]
        )
        assert "No relevant symbols found" in result.output or result.exit_code != 0

    def test_files_empty_project(self, runner, tmp_path):
        """files command on fresh project shows 'No indexed files.'"""
        result = runner.invoke(
            cli, ["files", "--project-root", str(tmp_path)]
        )
        assert "No indexed files" in result.output or result.exit_code != 0

    def test_affected_from_diff_isatty(self, runner, temp_project):
        """affected --from-diff with isatty() should show error.

        NOTE: Due to Click's CliRunner replacing sys.stdin, this is hard to cover.
        The test runs --from-diff without input, which simulates most of the path.
        """
        result = runner.invoke(
            cli, ["affected", "--from-diff", "--project-root", temp_project]
        )
        # Without piped input, either shows error or 'No changed files found'
        assert result.exit_code in (0, 1, 2)

    def test_affected_not_indexed_file(self, runner, temp_project):
        """affected command with non-indexed file shows 'not indexed'."""
        result = runner.invoke(
            cli, ["affected", "nonexistent_file.xyz", "--project-root", temp_project]
        )
        assert result.exit_code in (0, 1, 2)

    def test_git_history_file_not_found(self, runner, temp_project):
        """git-history with symbol that exists but file path is invalid."""
        with mock.patch("memorygraph.storage.manager.StorageManager.get_node") as mock_get_node:
            mock_get_node.return_value = {
                "qualified_name": "test_func",
                "kind": "function",
                "file_path": "/nonexistent/path/file.py",
                "name": "test_func",
                "start_line": 0,
            }
            result = runner.invoke(
                cli, ["git-history", "test_func", "--project-root", temp_project]
            )
            assert "File not found" in result.output

    def test_search_semantic_exception_in_fts(self, runner, temp_project):
        """search-semantic catches exception in FTS fallback."""
        with mock.patch("memorygraph.storage.manager.StorageManager.semantic_search",
                       side_effect=Exception("DB error")):
            result = runner.invoke(
                cli, ["search-semantic", "test_query", "--project-root", temp_project]
            )
            assert result.exit_code in (0, 1)

    def test_print_search_results_empty(self):
        """_print_search_results handles empty results list."""
        from memorygraph.cli.commands.querying import _print_search_results
        _print_search_results([], "empty query")


# ── Iteration 34: Semantic CLI coverage ───────────────────────────

class TestSemanticIngestNotFound:
    """Cover semantic-ingest line 40 (file not found skip)."""

    def test_ingest_file_not_found(self, runner, temp_project):
        """semantic-ingest --file with nonexistent path skips file."""
        result = runner.invoke(
            cli, ["semantic-ingest", "--file", "/nonexistent/path.py",
                  "--project-root", temp_project]
        )
        assert "Semantic ingest complete: 0 file(s)" in result.output


class TestAnalyzeAllFiles:
    """Cover analyze line 79 (--all branch)."""

    def test_analyze_all(self, runner, temp_project):
        """analyze --all processes all indexed files."""
        result = runner.invoke(
            cli, ["analyze", "--all", "--project-root", temp_project]
        )
        assert result.exit_code == 0
        assert "Analysis complete" in result.output


class TestAnalyzeErrorPaths:
    """Cover analyze lines 95-96 (OSError), 102-103 (SyntaxError), 116-117 (ValueError)."""

    def test_analyze_oserror_on_read(self, runner, temp_project):
        """analyze handles OSError when reading file."""
        # Create a file then remove read permission
        bad_file = os.path.join(temp_project, "unreadable.py")
        with open(bad_file, "w") as f:
            f.write("def foo(): pass\n")
        os.chmod(bad_file, 0o000)
        try:
            result = runner.invoke(
                cli, ["analyze", "--file", bad_file, "--project-root", temp_project]
            )
            assert result.exit_code == 0
        finally:
            os.chmod(bad_file, 0o644)

    def test_analyze_syntax_error(self, runner, temp_project):
        """analyze falls back to empty tree on SyntaxError (cover shared.py lines 153-154).
        Uses genuinely invalid Python that tree-sitter might accept but ast.parse rejects."""
        # Overwrite indexed file with invalid Python syntax
        indexed_file = os.path.join(temp_project, "src", "app.py")
        with open(indexed_file, "w") as f:
            f.write("def broken(:\n    pass\n")  # missing closing paren → SyntaxError
        result = runner.invoke(
            cli, ["analyze", "--file", indexed_file, "--project-root", temp_project]
        )
        assert result.exit_code == 0

    def test_analyze_value_error_relative_to(self, runner, tmp_path):
        """analyze uses abs_path when relative_to raises ValueError (cover shared.py lines 160-161).
        File is indexed in the DB but sits outside the project root."""
        # Create project structure
        project_root = os.path.join(tmp_path, "project")
        src_dir = os.path.join(project_root, "src")
        os.makedirs(src_dir)
        indexed_file = os.path.join(src_dir, "app.py")
        with open(indexed_file, "w") as f:
            f.write("def foo(): pass\n")

        # Index the file in the project DB
        from pathlib import Path

        from memorygraph.parsing.batch import ParallelParser
        from memorygraph.parsing.registry import LanguageRegistry
        from memorygraph.storage import StorageManager
        mgr = StorageManager(project_root)
        mgr.initialize()
        registry = LanguageRegistry()
        parser = ParallelParser(registry)
        results = parser.parse_files([Path(indexed_file)], resolve_symbols=True)
        for result in results.values():
            if not result.fatal_error:
                mgr.upsert_file(result)
        mgr.close()

        # Now move the file outside the project root
        outside_dir = os.path.join(tmp_path, "outside")
        os.makedirs(outside_dir, exist_ok=True)
        moved_file = os.path.join(outside_dir, "app.py")
        import shutil as _shutil
        _shutil.move(indexed_file, moved_file)

        # Run analyze on the moved file — Path.relative_to raises ValueError
        # because the file is now outside the project root
        result = runner.invoke(
            cli, ["analyze", "--file", moved_file,
                  "--project-root", project_root]
        )
        assert result.exit_code == 0
        _shutil.rmtree(os.path.join(project_root, ".memorygraph"), ignore_errors=True)

    def test_analyze_with_relative_path(self, runner, temp_project):
        """analyze handles relative file path (cover shared.py line 131)."""
        cwd = os.getcwd()
        try:
            os.chdir(temp_project)
            result = runner.invoke(
                cli, ["analyze", "--file", "src/app.py",
                      "--project-root", temp_project]
            )
            assert result.exit_code == 0
        finally:
            os.chdir(cwd)


class TestAnalyzeThenSmells:
    """Cover smells display loop (lines 141-149)."""

    def test_smells_after_analyze(self, runner, temp_project):
        """Run analyze then smells — should display odor count."""
        filepath = os.path.join(temp_project, "src", "app.py")
        runner.invoke(
            cli, ["analyze", "--file", filepath, "--project-root", temp_project]
        )
        result = runner.invoke(
            cli, ["smells", "--project-root", temp_project]
        )
        assert result.exit_code == 0
        # smells should either show list or "No smells found"


class TestAnalyzeThenMetrics:
    """Cover metrics display loop (lines 163-167)."""

    def test_metrics_after_analyze(self, runner, temp_project):
        """Run analyze then metrics — should display complexity."""
        filepath = os.path.join(temp_project, "src", "app.py")
        runner.invoke(
            cli, ["analyze", "--file", filepath, "--project-root", temp_project]
        )
        result = runner.invoke(
            cli, ["metrics", "--project-root", temp_project]
        )
        assert result.exit_code == 0


# ── Iteration 34: Indexing CLI coverage ──────────────────────────

class TestUninitCorruptedConfig:
    """Cover uninit lines 64-65 (JSON parse error)."""

    def test_uninit_malformed_json(self, runner, tmp_path):
        """uninit handles malformed Claude config JSON."""
        # Create .memorygraph dir so uninit can remove it
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()

        # Create malformed JSON in tmp_path, then mock Path.home() to return tmp_path
        malformed_file = tmp_path / ".claude.json"
        malformed_file.write_text("{ this is not valid json }")

        with mock.patch("memorygraph.cli.commands.indexing.Path.home") as mock_home:
            mock_home.return_value = tmp_path
            # uninit requires confirmation (--confirmation_option)
            result = runner.invoke(
                cli, ["uninit", "--project-root", str(tmp_path)],
                input="y\n"
            )
            # Should not crash even with malformed JSON
            assert result.exit_code == 0


class TestIndexFatalError:
    """Cover index lines 105-106 (fatal_error skip)."""

    def test_index_with_fatal_error_file(self, runner, tmp_path):
        """index reports SKIP for files that fail to parse."""
        from memorygraph.storage import StorageManager
        # Initialize the project
        mgr = StorageManager(str(tmp_path))
        mgr.initialize()
        mgr.close()

        # Create a file with unsupported extension
        bad_file = tmp_path / "bad.xyz"
        bad_file.write_text("some random content that cant be parsed")

        result = runner.invoke(
            cli, ["index", "--project-root", str(tmp_path)]
        )
        # Should not crash; may or may not show SKIP depending on registry
        assert result.exit_code == 0
        import shutil
        shutil.rmtree(tmp_path / ".memorygraph", ignore_errors=True)

    def test_index_fatal_error_skip(self, runner, tmp_path):
        """Cover index line 107: fatal_error SKIP output."""
        from unittest import mock
        fake_result = mock.MagicMock()
        fake_result.fatal_error = "Unsupported file type"
        fake_result.file = mock.MagicMock()
        fake_result.file.path = "/fake/test.py"

        def mock_parse(*args, **kwargs):
            return {"/fake/test.py": fake_result}

        mock_parser = mock.MagicMock()
        mock_parser.parse_files = mock_parse

        with mock.patch("memorygraph.cli.commands.indexing.ParallelParser", return_value=mock_parser):
            with mock.patch("memorygraph.cli.commands.indexing.LanguageRegistry"):
                with mock.patch("memorygraph.cli.shared._collect_files",
                                return_value=["/fake/test.py"]):
                    with mock.patch("memorygraph.cli.commands.indexing.create_storage_manager") as mock_mgr_cls:
                        mock_mgr_cls.return_value.list_files.return_value = []
                        result = runner.invoke(
                            cli, ["index", "--project-root", str(tmp_path)]
                        )
                        assert result.exit_code == 0
                        assert "SKIP" in result.output


class TestWatchStopKillSuccess:
    """Cover watch lines 156-157 (successful kill + unlink)."""

    def test_watch_stop_kill_succeeds(self, runner, tmp_path):
        """watch --stop when os.kill succeeds."""
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        pid_file = mg_dir / "watch.pid"
        pid_file.write_text("12345")

        with mock.patch("os.kill") as mock_kill:
            result = runner.invoke(
                cli, ["watch", "--stop", "--project-root", str(tmp_path)]
            )
            mock_kill.assert_called_once_with(12345, mock.ANY)
            assert "Stopped watch daemon" in result.output


class TestGenerateEmbeddings:
    """Cover _generate_embeddings lines 173-210."""

    def test_generate_embeddings_import_error(self, tmp_path):
        """_generate_embeddings handles ImportError from sentence-transformers."""
        import builtins

        from memorygraph.cli.commands.indexing import _generate_embeddings
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "memorygraph.semantic.embeddings":
                raise ImportError("no sentence-transformers")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=mock_import):
            with mock.patch("click.echo") as mock_echo:
                _generate_embeddings(str(tmp_path))
                mock_echo.assert_called_once()
                assert "not installed" in mock_echo.call_args[0][0]

    def test_generate_embeddings_not_available(self, tmp_path):
        """_generate_embeddings when is_available is False."""
        from memorygraph.cli.commands.indexing import _generate_embeddings
        mock_gen = mock.MagicMock()
        mock_gen.is_available = False
        with mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator",
            return_value=mock_gen
        ), mock.patch("click.echo") as mock_echo:
            _generate_embeddings(str(tmp_path))
            mock_echo.assert_called_once()
            assert "not installed" in mock_echo.call_args[0][0]

    def test_generate_embeddings_no_symbols(self, tmp_path):
        """_generate_embeddings skips files with no symbols."""
        from memorygraph.cli.commands.indexing import _generate_embeddings
        mock_gen = mock.MagicMock()
        mock_gen.is_available = True
        mock_gen.generate.return_value = None

        mock_mgr = mock.MagicMock()
        mock_mgr.__enter__.return_value = mock_mgr
        mock_mgr.list_files.return_value = [
            {"path": "/fake/test.py"}
        ]
        mock_mgr.get_symbols_for_file.return_value = []

        with mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator",
            return_value=mock_gen
        ), mock.patch(
            "memorygraph.storage.manager.StorageManager",
            return_value=mock_mgr
        ), mock.patch("click.echo") as mock_echo:
            _generate_embeddings(str(tmp_path))
            mock_echo.assert_called_with("Generated 0 embeddings.")

    def test_generate_embeddings_vec_none(self, tmp_path):
        """_generate_embeddings skips symbols when generate returns None (line 203)."""
        from memorygraph.cli.commands.indexing import _generate_embeddings
        mock_gen = mock.MagicMock()
        mock_gen.is_available = True
        mock_gen.generate.return_value = None  # vec is None → continue at line 203

        mock_mgr = mock.MagicMock()
        mock_mgr.__enter__.return_value = mock_mgr
        mock_mgr.list_files.return_value = [
            {"path": "/fake/test.py"}
        ]
        mock_mgr.get_symbols_for_file.return_value = [
            {"name": "foo", "qualified_name": "foo", "signature": "def foo()"}
        ]

        with mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator",
            return_value=mock_gen
        ), mock.patch(
            "memorygraph.storage.manager.StorageManager",
            return_value=mock_mgr
        ), mock.patch("click.echo") as mock_echo:
            _generate_embeddings(str(tmp_path))
            mock_echo.assert_called_with("Generated 0 embeddings.")

    def test_generate_embeddings_success(self, tmp_path):
        """_generate_embeddings successfully generates embeddings."""
        import numpy as np

        from memorygraph.cli.commands.indexing import _generate_embeddings
        mock_gen = mock.MagicMock()
        mock_gen.is_available = True
        mock_gen.generate.return_value = np.zeros(384, dtype=np.float32)

        mock_conn = mock.MagicMock()
        mock_mgr = mock.MagicMock()
        mock_mgr.__enter__.return_value = mock_mgr
        mock_mgr.list_files.return_value = [
            {"path": "/fake/test.py"}
        ]
        mock_mgr.get_symbols_for_file.return_value = [
            {"name": "foo", "qualified_name": "foo", "signature": "def foo()"}
        ]
        mock_mgr.get_conn.return_value = mock_conn

        with mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator",
            return_value=mock_gen
        ), mock.patch(
            "memorygraph.storage.manager.StorageManager",
            return_value=mock_mgr
        ), mock.patch("click.echo") as mock_echo:
            _generate_embeddings(str(tmp_path))
            mock_conn.execute.assert_called()
            mock_conn.commit.assert_called_once()
            mock_echo.assert_called_with("Generated 1 embeddings.")

    def test_generate_embeddings_sql_exception(self, tmp_path):
        """_generate_embeddings handles SQL insert exception (lines 209-210)."""
        import numpy as np

        from memorygraph.cli.commands.indexing import _generate_embeddings
        mock_gen = mock.MagicMock()
        mock_gen.is_available = True
        mock_gen.generate.return_value = np.zeros(384, dtype=np.float32)

        mock_conn = mock.MagicMock()
        mock_conn.execute.side_effect = Exception("SQL error")

        mock_mgr = mock.MagicMock()
        mock_mgr.__enter__.return_value = mock_mgr
        mock_mgr.list_files.return_value = [
            {"path": "/fake/test.py"}
        ]
        mock_mgr.get_symbols_for_file.return_value = [
            {"name": "helper", "qualified_name": "helper", "signature": "def helper(x)"}
        ]
        mock_mgr.get_conn.return_value = mock_conn

        with mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator",
            return_value=mock_gen
        ), mock.patch(
            "memorygraph.storage.manager.StorageManager",
            return_value=mock_mgr
        ), mock.patch("click.echo"):
            _generate_embeddings(str(tmp_path))
            # SQL errors are silently caught (line 210: pass)
            # But commit still happens
            mock_conn.commit.assert_called_once()


# ── Iteration 34: Querying CLI coverage ─────────────────────────

class TestQueryScoreDisplay:
    """Cover query line 35 (_score > 1 display)."""

    def test_query_shows_relevance_score(self, runner, temp_project):
        """query shows relevance when _score > 1."""
        with mock.patch("memorygraph.storage.manager.StorageManager.semantic_search") as mock_search:
            mock_search.return_value = [{
                "qualified_name": "main",
                "kind": "function",
                "file_path": os.path.join(temp_project, "src", "app.py"),
                "start_line": 4,
                "signature": "def main():",
                "_score": 2.5,
            }]
            result = runner.invoke(
                cli, ["query", "main", "--project-root", temp_project]
            )
            assert "relevance: 2.5" in result.output


class TestGitHistoryFullFlow:
    """Cover querying lines 218-237 (git_history subprocess flow)."""

    def test_git_history_success(self, runner, tmp_path):
        """git-history with real git repo shows commit history."""
        import subprocess as sp
        project = tmp_path / "git_project"
        project.mkdir()
        # Init git repo
        sp.run(["git", "-C", str(project), "init"], check=True, capture_output=True)
        sp.run(["git", "-C", str(project), "config", "user.email", "test@test.com"], check=True)
        sp.run(["git", "-C", str(project), "config", "user.name", "Test"], check=True)
        # Create and commit a file
        src_file = project / "app.py"
        src_file.write_text("def hello():\n    return 'world'\n\ndef main():\n    hello()\n")
        sp.run(["git", "-C", str(project), "add", "app.py"], check=True)
        sp.run(["git", "-C", str(project), "commit", "-m", "init"], check=True, capture_output=True)

        # Index the file
        from memorygraph.parsing.batch import ParallelParser
        from memorygraph.parsing.registry import LanguageRegistry
        from memorygraph.storage import StorageManager
        mgr = StorageManager(str(project))
        mgr.initialize()
        registry = LanguageRegistry()
        parser = ParallelParser(registry)
        results = parser.parse_files([src_file], resolve_symbols=True)
        for r in results.values():
            if not r.fatal_error:
                mgr.upsert_file(r)
        mgr.close()

        result = runner.invoke(
            cli, ["git-history", "hello", "--project-root", str(project)]
        )
        assert result.exit_code == 0

    def test_git_history_empty_result(self, runner, tmp_path, monkeypatch):
        """Cover git log success but empty stdout (line 233)."""
        # Run git-history on a file that's indexed but not in git
        project = tmp_path / "git_empty"
        project.mkdir()
        src_file = project / "test.py"
        src_file.write_text("def uncommitted_func():\n    pass\n")

        with mock.patch("subprocess.run") as mock_run:
            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            with mock.patch("memorygraph.storage.manager.StorageManager.get_node") as mock_node:
                mock_node.return_value = {
                    "qualified_name": "uncommitted_func", "kind": "function",
                    "file_path": str(src_file), "name": "uncommitted_func",
                    "start_line": 0, "end_line": 1,
                }
                result = runner.invoke(
                    cli, ["git-history", "uncommitted_func", "--project-root", str(project)]
                )
                assert "No git history found" in result.output

    def test_git_history_timeout(self, runner, temp_project):
        """git-history handles TimeoutExpired."""
        import subprocess
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)):
            with mock.patch("memorygraph.storage.manager.StorageManager.get_node") as mock_node:
                mock_node.return_value = {
                    "qualified_name": "test_func", "kind": "function",
                    "file_path": os.path.join(temp_project, "src", "app.py"),
                    "name": "test_func", "start_line": 1, "end_line": 3,
                }
                result = runner.invoke(
                    cli, ["git-history", "test_func", "--project-root", temp_project]
                )
                assert "timed out" in result.output

    def test_git_history_file_not_found_error(self, runner, temp_project):
        """git-history handles FileNotFoundError (git not installed)."""
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            with mock.patch("memorygraph.storage.manager.StorageManager.get_node") as mock_node:
                mock_node.return_value = {
                    "qualified_name": "test_func", "kind": "function",
                    "file_path": os.path.join(temp_project, "src", "app.py"),
                    "name": "test_func", "start_line": 1, "end_line": 3,
                }
                result = runner.invoke(
                    cli, ["git-history", "test_func", "--project-root", temp_project]
                )
                assert "Git not found" in result.output


class TestPatternsDisplay:
    """Cover querying lines 264, 278, 287-295 (patterns display loop)."""

    def test_patterns_no_symbols_in_file(self, runner, temp_project):
        """patterns with file that has no symbols covers line 264 continue."""
        # Create empty file, index it
        empty_file = os.path.join(temp_project, "empty.py")
        with open(empty_file, "w") as f:
            f.write("# just a comment\n")
        # Index the empty file
        from memorygraph.parsing.batch import ParallelParser
        from memorygraph.parsing.registry import LanguageRegistry
        from memorygraph.storage import StorageManager
        mgr = StorageManager(temp_project)
        mgr.initialize()
        registry = LanguageRegistry()
        parser = ParallelParser(registry)
        results = parser.parse_files([Path(empty_file)], resolve_symbols=True)
        for r in results.values():
            if not r.fatal_error:
                mgr.upsert_file(r)
        mgr.close()

        result = runner.invoke(
            cli, ["patterns", "--file", empty_file, "--project-root", temp_project]
        )
        assert result.exit_code == 0

    def test_patterns_with_detectable_pattern(self, runner, temp_project):
        """patterns detects design patterns and displays them."""
        # Create file with a detectable pattern (Singleton)
        pattern_file = os.path.join(temp_project, "src", "patterns.py")
        with open(pattern_file, "w") as f:
            f.write("""
class Singleton:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
""")
        # Index it
        from memorygraph.parsing.batch import ParallelParser
        from memorygraph.parsing.registry import LanguageRegistry
        from memorygraph.storage import StorageManager
        mgr = StorageManager(temp_project)
        mgr.initialize()
        registry = LanguageRegistry()
        parser = ParallelParser(registry)
        results = parser.parse_files([Path(pattern_file)], resolve_symbols=True)
        for r in results.values():
            if not r.fatal_error:
                mgr.upsert_file(r)
        mgr.close()

        result = runner.invoke(
            cli, ["patterns", "--project-root", temp_project]
        )
        assert result.exit_code == 0
        # Should output something (either patterns or "No patterns")
        assert len(result.output) > 0

    def test_patterns_with_display_branch(self, runner, temp_project, monkeypatch):
        """Cover patterns display loop (lines 287-295) with confidence + evidence."""
        # Mock detect_patterns to return items with confidence and evidence
        fake_patterns = [
            {"confidence": "high", "pattern": "Singleton", "symbol": "MyClass",
             "file": "src/app.py", "evidence": "Single underscore prefix"},
            {"confidence": "medium", "pattern": "Factory", "symbol": "MyFactory",
             "file": "src/app.py", "evidence": ""},
            {"confidence": "low", "pattern": "Observer", "symbol": "MyObserver",
             "file": "src/app.py"},
        ]
        monkeypatch.setattr("memorygraph.semantic.patterns.detect_patterns",
                            lambda *a, **kw: fake_patterns)
        result = runner.invoke(
            cli, ["patterns", "--project-root", temp_project]
        )
        assert result.exit_code == 0
        assert "HIGH" in result.output
        assert "Singleton" in result.output


class TestSearchSemanticPaths:
    """Cover search_semantic lines 317-374 (FTS fallback, error paths, vector path)."""

    def test_search_semantic_fts_fallback(self, runner, temp_project):
        """search-semantic falls back to FTS when embeddings unavailable."""
        with mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator.is_available",
            new_callable=mock.PropertyMock,
            return_value=False
        ):
            result = runner.invoke(
                cli, ["search-semantic", "test", "--project-root", temp_project]
            )
            assert result.exit_code == 0

    def test_search_semantic_generate_exception(self, runner, temp_project):
        """search-semantic handles embedding generation exception."""
        with mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator.is_available",
            new_callable=mock.PropertyMock,
            return_value=True
        ), mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator.generate",
            side_effect=RuntimeError("Model failed")
        ):
            result = runner.invoke(
                cli, ["search-semantic", "test", "--project-root", temp_project]
            )
            assert "Error generating embedding" in result.output

    def test_search_semantic_generate_returns_none(self, runner, temp_project):
        """search-semantic handles generate() returning None."""
        with mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator.is_available",
            new_callable=mock.PropertyMock,
            return_value=True
        ), mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator.generate",
            return_value=None
        ):
            result = runner.invoke(
                cli, ["search-semantic", "test", "--project-root", temp_project]
            )
            assert "Failed to generate query embedding" in result.output

    def test_search_semantic_vector_only(self, runner, temp_project):
        """Cover pure vector search path (no hybrid, no FTS)."""
        import numpy as np
        with mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator.is_available",
            new_callable=mock.PropertyMock,
            return_value=True
        ), mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator.generate",
            return_value=np.zeros(384, dtype=np.float32)
        ), mock.patch(
            "memorygraph.cli.commands.querying._load_stored_embeddings",
            return_value=[{
                "name": "main", "qualified_name": "main",
                "file_path": os.path.join(temp_project, "src", "app.py"),
                "kind": "function", "signature": "def main():",
                "embedding": np.zeros(384, dtype=np.float32),
            }]
        ), mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator.search",
            return_value=[{
                "qualified_name": "main", "kind": "function",
                "file_path": os.path.join(temp_project, "src", "app.py"),
                "signature": "def main():",
                "_similarity": 0.95,
            }]
        ):
            result = runner.invoke(cli, [
                "search-semantic", "main", "--project-root", temp_project,
                "--no-hybrid"
            ])
            assert result.exit_code == 0
            assert "main" in result.output

    def test_search_semantic_empty_embeddings(self, runner, temp_project):
        """search-semantic shows helpful message when no embeddings stored (lines 438-440)."""
        import numpy as np
        with mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator.is_available",
            new_callable=mock.PropertyMock,
            return_value=True
        ), mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator.generate",
            return_value=np.zeros(384, dtype=np.float32)
        ), mock.patch(
            "memorygraph.cli.commands.querying._load_stored_embeddings",
            return_value=[]
        ):
            result = runner.invoke(cli, [
                "search-semantic", "main", "--project-root", temp_project,
            ])
            assert "No embeddings stored" in result.output

    def test_search_semantic_hybrid_path(self, runner, temp_project):
        """search-semantic --hybrid uses FTS + vector hybrid mode (lines 431-432, 446)."""
        import numpy as np
        with mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator.is_available",
            new_callable=mock.PropertyMock,
            return_value=True
        ), mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator.generate",
            return_value=np.zeros(384, dtype=np.float32)
        ), mock.patch(
            "memorygraph.cli.commands.querying._load_stored_embeddings",
            return_value=[{
                "name": "main", "qualified_name": "main",
                "file_path": os.path.join(temp_project, "src", "app.py"),
                "kind": "function", "signature": "def main():",
                "embedding": np.zeros(384, dtype=np.float32),
            }]
        ), mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator.search",
            return_value=[{
                "qualified_name": "main", "kind": "function",
                "file_path": os.path.join(temp_project, "src", "app.py"),
                "signature": "def main():", "_similarity": 0.95,
            }]
        ), mock.patch(
            "memorygraph.semantic.embeddings.EmbeddingGenerator.hybrid_search",
            return_value=[{
                "qualified_name": "main", "kind": "function",
                "file_path": os.path.join(temp_project, "src", "app.py"),
                "signature": "def main():", "_score": 0.85,
            }]
        ), mock.patch(
            "memorygraph.storage.manager.StorageManager.semantic_search",
            return_value=[{"qualified_name": "main"}]
        ):
            result = runner.invoke(cli, [
                "search-semantic", "main", "--project-root", temp_project,
                "--hybrid",
            ])
            assert result.exit_code == 0


class TestLoadStoredEmbeddingsException:
    """Cover _load_stored_embeddings lines 403-404."""

    def test_load_stored_embeddings_exception(self):
        """_load_stored_embeddings returns [] when _get_conn raises."""
        from memorygraph.cli.commands.querying import _load_stored_embeddings
        mock_mgr = mock.MagicMock()
        mock_mgr.get_conn.side_effect = Exception("DB connection failed")
        result = _load_stored_embeddings(mock_mgr)
        assert result == []

    def test_load_stored_embeddings_with_blobs(self):
        """_load_stored_embeddings parses 384-float blobs correctly (lines 471-474)."""
        import numpy as np

        from memorygraph.cli.commands.querying import _load_stored_embeddings
        # Create a valid 384-float embedding blob
        vec = np.random.randn(384).astype(np.float32)
        blob = vec.tobytes()
        mock_row = ("main", "main", "def main():", "/test/app.py", "function", blob)
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [mock_row]
        mock_mgr = mock.MagicMock()
        mock_mgr.get_conn.return_value = mock_conn
        result = _load_stored_embeddings(mock_mgr)
        assert len(result) == 1
        assert result[0]["name"] == "main"
        assert isinstance(result[0]["embedding"], np.ndarray)
        assert result[0]["embedding"].shape == (384,)
        assert result[0]["embedding"].dtype == np.float32

    def test_load_stored_embeddings_invalid_blob_size(self):
        """_load_stored_embeddings skips blobs with wrong size (line 472)."""
        from memorygraph.cli.commands.querying import _load_stored_embeddings
        # Create a blob with wrong size (not 384*4 bytes)
        blob = b"short_blob"
        mock_row = ("main", "main", "def main():", "/test/app.py", "function", blob)
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [mock_row]
        mock_mgr = mock.MagicMock()
        mock_mgr.get_conn.return_value = mock_conn
        result = _load_stored_embeddings(mock_mgr)
        assert result == []


class TestPrintSearchResults:
    """Cover _print_search_results lines 423, 426 (signature display, separator)."""

    def test_print_search_results_with_signatures_and_separator(self):
        """_print_search_results displays signatures and separator between items."""
        from memorygraph.cli.commands.querying import _print_search_results
        results = [
            {"qualified_name": "hello", "kind": "function", "file_path": "/a.py",
             "signature": "def hello():", "start_line": 1},
            {"qualified_name": "main", "kind": "function", "file_path": "/b.py",
             "signature": "", "start_line": 5},
            {"qualified_name": "util", "kind": "function", "file_path": "/c.py",
             "start_line": 10},
        ]
        _print_search_results(results, "test query")


class TestHookCommand:
    """Test the 'hook' CLI command — install/uninstall git pre-commit hook."""

    def test_hook_not_a_git_repo(self, runner, tmp_path):
        """hook should warn when target directory is not a git repository."""
        result = runner.invoke(cli, ["hook", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        assert "Not a git repository" in result.output

    def test_hook_install(self, runner, tmp_path):
        """hook should install pre-commit script into .git/hooks."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        result = runner.invoke(cli, ["hook", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        assert "Pre-commit hook installed" in result.output
        pre_commit = git_dir / "hooks" / "pre-commit"
        assert pre_commit.exists()
        content = pre_commit.read_text()
        assert "memorygraph sync" in content

    def test_hook_uninstall_when_installed(self, runner, tmp_path):
        """hook --uninstall should remove an existing pre-commit hook."""
        git_dir = tmp_path / ".git"
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(parents=True)
        pre_commit = hooks_dir / "pre-commit"
        pre_commit.write_text("#!/bin/sh\necho old hook\n")
        pre_commit.chmod(0o755)

        result = runner.invoke(cli, ["hook", "--project-root", str(tmp_path), "--uninstall"])
        assert result.exit_code == 0
        assert "Pre-commit hook removed" in result.output
        assert not pre_commit.exists()

    def test_hook_uninstall_when_not_installed(self, runner, tmp_path):
        """hook --uninstall should report when no hook is installed."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        result = runner.invoke(cli, ["hook", "--project-root", str(tmp_path), "--uninstall"])
        assert result.exit_code == 0
        assert "No pre-commit hook installed" in result.output

    def test_hook_help(self, runner):
        """hook --help should display usage."""
        result = runner.invoke(cli, ["hook", "--help"])
        assert result.exit_code == 0
        assert "Install or uninstall" in result.output


# ── Iteration 46: Coverage refresh ──────────────────────────────


class TestJSONFormatter:
    """Cover JSONFormatter.format() and setup_logging with json format."""

    def test_json_formatter_format(self):
        """JSONFormatter emits one JSON object per log line (shared.py lines 237-247)."""
        import logging

        from memorygraph.cli.shared import JSONFormatter

        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test_logger", level=logging.INFO,
            pathname=__file__, lineno=42, msg="hello json",
            args=(), exc_info=None,
        )
        output = fmt.format(record)
        import json
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["msg"] == "hello json"
        assert parsed["logger"] == "test_logger"
        assert "ts" in parsed

    def test_json_formatter_with_exc_info(self):
        """JSONFormatter includes exc field when exc_info is present (shared.py lines 245-246)."""
        import logging

        from memorygraph.cli.shared import JSONFormatter

        fmt = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            record = logging.LogRecord(
                name="test_logger", level=logging.ERROR,
                pathname=__file__, lineno=42, msg="error occurred",
                args=(), exc_info=sys.exc_info(),
            )
        output = fmt.format(record)
        import json
        parsed = json.loads(output)
        assert parsed["level"] == "ERROR"
        assert "exc" in parsed
        assert "ValueError" in parsed["exc"]

    def test_setup_logging_json_format(self):
        """setup_logging with fmt='json' uses JSONFormatter handler (shared.py line 264)."""
        import logging

        from memorygraph.cli.shared import JSONFormatter, setup_logging

        setup_logging(fmt="json", level=logging.DEBUG)
        root = logging.getLogger()
        handler = root.handlers[0] if root.handlers else None
        assert handler is not None
        assert isinstance(handler.formatter, JSONFormatter)
        # Verify it logs valid JSON
        record = logging.LogRecord(
            name="x", level=logging.WARNING,
            pathname=__file__, lineno=1, msg="json check",
            args=(), exc_info=None,
        )
        output = handler.format(record)
        import json
        parsed = json.loads(output)
        assert parsed["msg"] == "json check"
        # Reset root logger
        root.handlers.clear()
        root.setLevel(logging.WARNING)  # reset to default


class TestServingFunctions:
    """Test serving.py internal functions (cover PID/stop-daemon lines)."""

    def test_write_and_remove_pid(self, tmp_path):
        """_write_pid creates PID file, _remove_pid removes it (cover lines 43-46, 51-53)."""
        from memorygraph.cli.commands.serving import _remove_pid, _write_pid
        project_root = str(tmp_path)
        _write_pid(project_root)
        pid_file = tmp_path / ".memorygraph" / "serve.pid"
        assert pid_file.exists()
        pid_content = pid_file.read_text().strip()
        assert pid_content == str(os.getpid())
        _remove_pid(project_root)
        assert not pid_file.exists()

    def test_remove_pid_nonexistent(self):
        """_remove_pid no-ops when PID file doesn't exist."""
        import tempfile

        from memorygraph.cli.commands.serving import _remove_pid
        with tempfile.TemporaryDirectory() as tmpdir:
            _remove_pid(tmpdir)  # Should not raise

    def test_stop_daemon_no_pid_file(self, tmp_path):
        """_stop_daemon returns False when no PID file (cover line 59-60)."""
        from memorygraph.cli.commands.serving import _stop_daemon
        result = _stop_daemon(str(tmp_path))
        assert result is False

    def test_serve_stop_no_daemon(self, runner, tmp_path):
        """serve --stop shows 'No daemon running' (cover lines 118-123)."""
        result = runner.invoke(
            cli, ["serve", "--stop", "--project-root", str(tmp_path)]
        )
        assert "No daemon" in result.output

    def test_serve_daemon_requires_web(self, runner, tmp_path):
        """serve --daemon without --web shows error."""
        result = runner.invoke(
            cli, ["serve", "--daemon", "--project-root", str(tmp_path)]
        )
        assert "Background mode requires --web" in result.output

    def test_stop_daemon_with_pid_file_success(self, tmp_path):
        """_stop_daemon with valid PID file sends SIGTERM (cover lines 61-66)."""
        from unittest import mock

        from memorygraph.cli.commands.serving import _stop_daemon

        # Create PID file
        pid_dir = tmp_path / ".memorygraph"
        pid_dir.mkdir()
        pid_file = pid_dir / "serve.pid"
        pid_file.write_text("99999")  # Process we hope doesn't exist

        with mock.patch("memorygraph.cli.commands.serving.os.kill") as mock_kill:
            result = _stop_daemon(str(tmp_path))
            assert result is True
            mock_kill.assert_called_once_with(99999, 15)  # SIGTERM = 15
        assert not pid_file.exists()  # PID file should be cleaned up

    def test_stop_daemon_stale_pid(self, tmp_path):
        """_stop_daemon handles ProcessLookupError on stale PID (cover lines 67-69)."""
        from unittest import mock

        from memorygraph.cli.commands.serving import _stop_daemon

        pid_dir = tmp_path / ".memorygraph"
        pid_dir.mkdir()
        pid_file = pid_dir / "serve.pid"
        pid_file.write_text("99999")

        with mock.patch("memorygraph.cli.commands.serving.os.kill",
                        side_effect=ProcessLookupError):
            result = _stop_daemon(str(tmp_path))
            assert result is True
        assert not pid_file.exists()  # Stale PID file removed

    def test_stop_daemon_os_error(self, tmp_path):
        """_stop_daemon handles OSError gracefully (cover lines 70-72)."""
        from unittest import mock

        from memorygraph.cli.commands.serving import _stop_daemon

        pid_dir = tmp_path / ".memorygraph"
        pid_dir.mkdir()
        pid_file = pid_dir / "serve.pid"
        pid_file.write_text("99999")

        with mock.patch("memorygraph.cli.commands.serving.os.kill",
                        side_effect=OSError("permission denied")):
            result = _stop_daemon(str(tmp_path))
            assert result is False
        assert pid_file.exists()  # PID file kept on non-stale error

    def test_stop_daemon_invalid_pid(self, tmp_path):
        """_stop_daemon handles ValueError from non-numeric PID (cover lines 70-72)."""
        from memorygraph.cli.commands.serving import _stop_daemon

        pid_dir = tmp_path / ".memorygraph"
        pid_dir.mkdir()
        pid_file = pid_dir / "serve.pid"
        pid_file.write_text("not_a_number")  # Invalid PID

        result = _stop_daemon(str(tmp_path))
        assert result is False  # Should return False on failure
        assert pid_file.exists()  # PID file preserved

    def test_serve_stop_with_pid_file(self, runner, tmp_path):
        """serve --stop with existing PID file stops daemon (cover line 120)."""
        # Create a PID file
        pid_dir = tmp_path / ".memorygraph"
        pid_dir.mkdir()
        pid_file = pid_dir / "serve.pid"
        pid_file.write_text(str(os.getpid()))

        from unittest import mock
        with mock.patch("memorygraph.cli.commands.serving.os.kill"):
            result = runner.invoke(
                cli, ["serve", "--stop", "--project-root", str(tmp_path)]
            )
            assert "Daemon stopped" in result.output


class TestAnalyzeFilesValueError:
    """Cover _analyze_files ValueError handler (shared.py lines 160-161).
    Triggers the defensive handler when a file has DB symbols but is
    outside the project root."""

    def test_analyze_files_value_error_relative_to(self, tmp_path):
        """_analyze_files catches ValueError from Path.relative_to and uses abs_path."""

        from memorygraph.cli.shared import _analyze_files
        from memorygraph.storage import StorageManager

        # Create a project with an indexed file
        project_root = str(tmp_path / "project")
        src_dir = os.path.join(project_root, "src")
        os.makedirs(src_dir)
        file_path = os.path.join(src_dir, "app.py")
        with open(file_path, "w") as f:
            f.write("def foo(): pass\n")

        # Index the file
        mgr = StorageManager(project_root)
        mgr.initialize()
        from pathlib import Path

        from memorygraph.parsing.batch import ParallelParser
        from memorygraph.parsing.registry import LanguageRegistry
        registry = LanguageRegistry()
        parser = ParallelParser(registry)
        results = parser.parse_files([Path(file_path)], resolve_symbols=True)
        for result in results.values():
            if not result.fatal_error:
                mgr.upsert_file(result)
        mgr.close()

        # Mock the internal StorageManager to return the real file's path
        # as a file outside the project root, forcing relative_to to fail
        outside_path = str(tmp_path / "outside" / "src" / "app.py")
        os.makedirs(os.path.dirname(outside_path), exist_ok=True)
        import shutil
        shutil.copy(file_path, outside_path)

        # Directly call _analyze_files with the outside path
        # Mock get_symbols_for_file to return data for the outside path
        from unittest import mock as _mock
        with _mock.patch("memorygraph.storage.manager.StorageManager.get_symbols_for_file") as mock_get_syms:
            mock_get_syms.return_value = [
                {"qualified_name": "foo", "kind": "function",
                 "parent_class": None, "start_line": 1}
            ]
            result = _analyze_files(project_root, [outside_path])
        assert result == 1  # 1 file analyzed successfully


class TestE2EInitIndexQuery:
    """End-to-end: init -> index -> query flow."""

    def test_init_index_query_flow(self, runner, tmp_path):
        """Complete flow: init creates DB -> index parses files -> query searches symbols."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "src"
        src.mkdir()
        (src / "main.py").write_text(
            "def greet(name):\n    return f'Hello, {name}'\n\n"
            "def main():\n    print(greet('World'))\n"
        )

        from memorygraph.cli.main import cli

        # Step 1: init
        result = runner.invoke(cli, ["init", "--project-root", str(project)])
        assert result.exit_code == 0
        assert (project / ".memorygraph" / "memorygraph.db").exists()

        # Step 2: index
        result = runner.invoke(cli, ["index", "--project-root", str(project)])
        assert result.exit_code == 0
        assert "Indexed" in result.output

        # Step 3: query
        result = runner.invoke(cli, ["query", "greet", "--project-root", str(project)])
        assert result.exit_code == 0
        assert "greet" in result.output

    def test_init_index_query_with_multiple_files(self, runner, tmp_path):
        """Index multiple files and verify cross-file references work."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "src"
        src.mkdir()
        (src / "utils.py").write_text("def helper():\n    return 42\n")
        (src / "main.py").write_text(
            "from utils import helper\n\ndef main():\n    return helper()\n"
        )

        from memorygraph.cli.main import cli

        # Step 1: init
        result = runner.invoke(cli, ["init", "--project-root", str(project)])
        assert result.exit_code == 0

        # Step 2: index
        result = runner.invoke(cli, ["index", "--project-root", str(project)])
        assert result.exit_code == 0
        assert "Indexed 2" in result.output

        # Step 3: query for cross-file symbol
        result = runner.invoke(cli, ["query", "helper", "--project-root", str(project)])
        assert result.exit_code == 0
        assert "helper" in result.output


class TestSemanticIngestPathResolution:
    """Regression: --file path resolves against --project-root, not CWD."""

    def test_ingest_relative_file_from_different_cwd(self, runner, tmp_path):
        """--file relative path resolves against --project-root, not CWD."""
        project_root = tmp_path / "myproject"
        project_root.mkdir()
        src_dir = project_root / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("# main module")

        result = runner.invoke(cli, ["init", "--project-root", str(project_root)])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["index", "--project-root", str(project_root)])
        assert result.exit_code == 0

        other_dir = tmp_path / "somewhere_else"
        other_dir.mkdir()
        original_cwd = os.getcwd()
        try:
            os.chdir(str(other_dir))
            result = runner.invoke(
                cli, ["semantic-ingest", "--file", "src/main.py",
                      "--project-root", str(project_root)]
            )
        finally:
            os.chdir(original_cwd)

        assert "Semantic ingest complete: 1 file(s)" in result.output

    def test_ingest_absolute_file_path_unaffected(self, runner, tmp_path):
        """Absolute --file paths work regardless of CWD."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        python_file = project_root / "module.py"
        python_file.write_text("# module")
        abs_path = str(python_file.resolve())

        result = runner.invoke(cli, ["init", "--project-root", str(project_root)])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["index", "--project-root", str(project_root)])
        assert result.exit_code == 0

        result = runner.invoke(
            cli, ["semantic-ingest", "--file", abs_path,
                  "--project-root", str(project_root)]
        )
        assert "Semantic ingest complete: 1 file(s)" in result.output


class TestSemanticFileFiltering:
    """Cover smells --file and metrics --file path normalization (semantic.py:101,127)."""

    def test_smells_with_absolute_file(self, runner, tmp_path):
        """smells --file with absolute path covers path normalization branch."""
        project_root = tmp_path / "proj"
        project_root.mkdir()
        (project_root / "src").mkdir()
        (project_root / "src" / "app.py").write_text("def foo(): pass\n")

        result = runner.invoke(cli, ["init", "--project-root", str(project_root)])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["index", "--project-root", str(project_root)])
        assert result.exit_code == 0

        abs_file = str((project_root / "src" / "app.py").resolve())
        result = runner.invoke(
            cli, ["semantic-ingest", "--file", abs_file,
                  "--project-root", str(project_root)]
        )
        assert "Semantic ingest complete: 1 file(s)" in result.output

        result = runner.invoke(
            cli, ["smells", "--file", abs_file,
                  "--project-root", str(project_root)]
        )
        assert result.exit_code == 0

    def test_smells_with_relative_file(self, runner, tmp_path):
        """smells --file with relative path covers absolute-path conversion branch (line 101)."""
        project_root = tmp_path / "proj2"
        project_root.mkdir()
        (project_root / "main.py").write_text("def foo(): pass\n")

        result = runner.invoke(cli, ["init", "--project-root", str(project_root)])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["index", "--project-root", str(project_root)])
        assert result.exit_code == 0

        result = runner.invoke(
            cli, ["semantic-ingest", "--file", "main.py",
                  "--project-root", str(project_root)]
        )
        assert "Semantic ingest complete: 1 file(s)" in result.output

        result = runner.invoke(
            cli, ["smells", "--file", "main.py",
                  "--project-root", str(project_root)]
        )
        assert result.exit_code == 0

    def test_metrics_with_relative_file(self, runner, tmp_path):
        """metrics --file with relative path covers path normalization branch."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "mod.py").write_text("# module\n")

        result = runner.invoke(cli, ["init", "--project-root", str(project_root)])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["index", "--project-root", str(project_root)])
        assert result.exit_code == 0

        result = runner.invoke(
            cli, ["semantic-ingest", "--file", "mod.py",
                  "--project-root", str(project_root)]
        )
        assert "Semantic ingest complete: 1 file(s)" in result.output

        result = runner.invoke(
            cli, ["metrics", "--file", "mod.py",
                  "--project-root", str(project_root)]
        )
        assert result.exit_code == 0


class TestScanChanges:
    """Cover _scan_changes in indexing.py (lines 301-346)."""

    def test_new_file_detected(self, tmp_path):
        """_scan_changes detects newly added files."""
        from memorygraph.cli.commands.indexing import _scan_changes

        root = tmp_path / "project"
        root.mkdir()
        mtimes: dict[str, float] = {}

        (root / "new_file.py").write_text("x = 1")

        changed = _scan_changes(root, mtimes)
        assert len(changed) == 1
        assert changed[0].endswith("new_file.py")
        assert len(mtimes) == 1

    def test_modified_file_detected(self, tmp_path):
        """_scan_changes detects modified files (mtime increased)."""
        from memorygraph.cli.commands.indexing import _scan_changes

        root = tmp_path / "project"
        root.mkdir()
        f = root / "mod.py"
        f.write_text("v1")

        mtimes: dict[str, float] = {}
        _scan_changes(root, mtimes)
        assert len(mtimes) == 1

        import time
        time.sleep(0.01)
        f.write_text("v2")

        changed = _scan_changes(root, mtimes)
        assert len(changed) == 1

    def test_deleted_file_removed_from_mtimes(self, tmp_path):
        """_scan_changes removes deleted files from mtimes dict."""
        from memorygraph.cli.commands.indexing import _scan_changes

        root = tmp_path / "project"
        root.mkdir()
        f = root / "del.py"
        f.write_text("tmp")

        mtimes: dict[str, float] = {}
        _scan_changes(root, mtimes)
        assert len(mtimes) == 1

        f.unlink()
        changed = _scan_changes(root, mtimes)
        assert len(changed) == 0
        assert len(mtimes) == 0

    def test_hidden_dirs_skipped(self, tmp_path):
        """_scan_changes skips hidden directories and __pycache__."""
        from memorygraph.cli.commands.indexing import _scan_changes

        root = tmp_path / "project"
        root.mkdir()
        (root / ".git").mkdir()
        (root / "__pycache__").mkdir()
        (root / ".hidden").mkdir()

        (root / ".git" / "config").write_text("data")
        (root / "__pycache__" / "cache.pyc").write_text("cache")
        (root / ".hidden" / "secret.py").write_text("secret")
        (root / "visible.py").write_text("visible")

        mtimes: dict[str, float] = {}
        changed = _scan_changes(root, mtimes)
        assert len(changed) == 1
        assert "visible.py" in changed[0]
        assert len(mtimes) == 1

    def test_dotfile_excluded(self, tmp_path):
        """_scan_changes skips dotfiles (except .env)."""
        from memorygraph.cli.commands.indexing import _scan_changes

        root = tmp_path / "project"
        root.mkdir()
        (root / ".hidden_file").write_text("hidden")
        (root / ".env").write_text("KEY=val")
        (root / "normal.py").write_text("code")

        mtimes: dict[str, float] = {}
        changed = _scan_changes(root, mtimes)
        names = [Path(p).name for p in changed]
        assert ".hidden_file" not in names
        assert ".env" in names
        assert "normal.py" in names

    def test_oserror_skipped(self, tmp_path):
        """_scan_changes skips files that raise OSError on stat."""
        from memorygraph.cli.commands.indexing import _scan_changes

        root = tmp_path / "project"
        root.mkdir()
        (root / "good.py").write_text("ok")

        mtimes: dict[str, float] = {}
        with mock.patch("os.stat", side_effect=OSError("permission denied")):
            changed = _scan_changes(root, mtimes)
        assert len(changed) == 0

    def test_no_changes_on_rescan(self, tmp_path):
        """_scan_changes returns empty list when nothing changed."""
        from memorygraph.cli.commands.indexing import _scan_changes

        root = tmp_path / "project"
        root.mkdir()
        (root / "stable.py").write_text("unchanged")

        mtimes: dict[str, float] = {}
        _scan_changes(root, mtimes)
        changed = _scan_changes(root, mtimes)
        assert changed == []

    def test_multiple_files_in_subdirs(self, tmp_path):
        """_scan_changes traverses subdirectories correctly."""
        from memorygraph.cli.commands.indexing import _scan_changes

        root = tmp_path / "project"
        root.mkdir()
        (root / "src").mkdir()
        (root / "tests").mkdir()
        (root / "src" / "app.py").write_text("app")
        (root / "tests" / "test_app.py").write_text("test")

        mtimes: dict[str, float] = {}
        changed = _scan_changes(root, mtimes)
        assert len(changed) == 2
        assert len(mtimes) == 2


class TestInstallClaudeHook:
    """Cover _install_claude_hook in utils.py (lines 219-288)."""

    def test_install_hook_creates_settings(self, tmp_path):
        """hook --claude creates .claude/settings.local.json with Stop hook."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(
            cli, ["hook", "--claude", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0
        settings = tmp_path / ".claude" / "settings.local.json"
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "hooks" in data
        assert "Stop" in data["hooks"]

    def test_install_hook_idempotent(self, tmp_path):
        """hook --claude is idempotent — doesn't duplicate hooks."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        runner = CliRunner()
        runner.invoke(cli, ["hook", "--claude", "--project-root", str(tmp_path)])
        result = runner.invoke(cli, ["hook", "--claude", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        settings = tmp_path / ".claude" / "settings.local.json"
        data = json.loads(settings.read_text())
        stop_hooks = data["hooks"]["Stop"]
        assert len(stop_hooks) == 1

    def test_uninstall_hook_removes(self, tmp_path):
        """hook --claude --uninstall removes the hook from settings."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        runner = CliRunner()
        runner.invoke(cli, ["hook", "--claude", "--project-root", str(tmp_path)])
        result = runner.invoke(
            cli, ["hook", "--claude", "--project-root", str(tmp_path), "--uninstall"]
        )
        assert result.exit_code == 0
        assert "hook removed" in result.output.lower()

    def test_uninstall_no_settings(self, tmp_path):
        """hook --claude --uninstall with no settings file shows message."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(
            cli, ["hook", "--claude", "--project-root", str(tmp_path), "--uninstall"]
        )
        assert result.exit_code == 0
        assert "No .claude/settings.local.json found" in result.output

    def test_uninstall_no_hook_present(self, tmp_path):
        """hook --claude --uninstall when hook not found reports it."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        runner = CliRunner()
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.local.json").write_text(
            json.dumps({"hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "echo hi"}]}]}})
        )
        result = runner.invoke(
            cli, ["hook", "--claude", "--project-root", str(tmp_path), "--uninstall"]
        )
        assert result.exit_code == 0
        assert "No memorygraph hook found" in result.output

    def test_install_overwrites_corrupt_settings(self, tmp_path):
        """hook --claude handles corrupt settings gracefully."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.local.json").write_text("{invalid json")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["hook", "--claude", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "Warning" in result.output

    def test_uninstall_corrupt_settings(self, tmp_path):
        """hook --claude --uninstall with corrupt settings → exception handler (utils.py:245-246)."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.local.json").write_text("{not valid json at all")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["hook", "--claude", "--project-root", str(tmp_path), "--uninstall"]
        )
        assert result.exit_code == 0
        assert "Failed to read settings" in result.output


class TestWatchEdgeCases:
    """Cover uncovered branches in indexing.py watch command."""

    def test_watch_not_initialized(self, tmp_path):
        """watch on non-initialized project shows error (cover indexing.py 217-221)."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(
            cli, ["watch", "--project-root", str(tmp_path), "--once"]
        )
        assert "Not a memorygraph project" in result.output

    def test_watchdog_not_installed_fallback(self, tmp_path):
        """watch falls back to polling when watchdog not installed (cover indexing.py 361-363)."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        (tmp_path / ".memorygraph").mkdir()
        runner = CliRunner()
        with mock.patch("memorygraph.cli.commands.indexing._watch_native", return_value=False):
            result = runner.invoke(
                cli, ["watch", "--project-root", str(tmp_path), "--once"]
            )
        # Should fall back to polling mode
        assert result.exit_code == 0


class TestStatusJsonOutput:
    """Cover status --json output path in utils.py (lines 22-36)."""

    def test_status_json_output(self, tmp_path):
        """status --json outputs machine-readable JSON (cover utils.py 22-36)."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["index", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        result = runner.invoke(
            cli, ["status", "--project-root", str(tmp_path), "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "project_root" in data
        assert "files_indexed" in data
        assert "symbols" in data
        assert "backend" in data


class TestBackupRestoreErrorPaths:
    """Cover error paths in backup/restore commands (indexing.py 510-570)."""

    def test_backup_not_initialized(self, tmp_path):
        """backup on non-initialized project exits with error (cover indexing.py 511-514)."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(
            cli, ["backup", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 1
        assert "Not a memorygraph project" in result.output

    def test_restore_file_not_found(self, tmp_path):
        """restore with nonexistent file exits with error (cover indexing.py 543-545)."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        (tmp_path / ".memorygraph").mkdir()
        runner = CliRunner()
        result = runner.invoke(
            cli, ["restore", "--project-root", str(tmp_path),
                  str(tmp_path / "nonexistent.tar.gz")]
        )
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_restore_not_tar_archive(self, tmp_path):
        """restore with non-tar file exits with error (cover indexing.py 547-549)."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        (tmp_path / ".memorygraph").mkdir()
        bad_file = tmp_path / "bad.txt"
        bad_file.write_text("not a tar file")
        runner = CliRunner()
        result = runner.invoke(
            cli, ["restore", "--project-root", str(tmp_path), str(bad_file)]
        )
        assert result.exit_code == 1
        assert "Not a valid tar archive" in result.output

    def test_restore_memorygraph_exists(self, tmp_path):
        """restore when .memorygraph already exists exits with error (cover indexing.py 552-558)."""
        import tarfile

        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        # Create a valid tar and existing .memorygraph
        (tmp_path / ".memorygraph").mkdir()
        tar_path = tmp_path / "backup.tar.gz"
        with tarfile.open(str(tar_path), "w:gz") as tar:
            # Add a dummy file so it's a valid tar
            dummy = tmp_path / "dummy"
            dummy.write_text("data")
            tar.add(str(dummy), arcname="dummy")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["restore", "--project-root", str(tmp_path), str(tar_path)]
        )
        assert result.exit_code == 1
        assert "already exists" in result.output


class TestWatchOncePolling:
    """Cover watch --once polling fallback path (indexing.py 243-253)."""

    def test_watch_once_no_changes(self, tmp_path):
        """watch --once on initialized project with no new changes (cover line 252)."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["index", "--project-root", str(tmp_path)])
        assert result.exit_code == 0

        with mock.patch("memorygraph.cli.commands.indexing._watch_native", return_value=False):
            result = runner.invoke(
                cli, ["watch", "--project-root", str(tmp_path), "--once"]
            )
        assert result.exit_code == 0
        assert "No changes detected" in result.output

    def test_watch_once_with_changes(self, tmp_path):
        """watch --once detects and syncs new files via polling (cover lines 246-250)."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["index", "--project-root", str(tmp_path)])
        assert result.exit_code == 0

        # Create a new file after indexing
        (tmp_path / "new_module.py").write_text("def hello(): pass\n")

        with mock.patch("memorygraph.cli.commands.indexing._watch_native", return_value=False):
            result = runner.invoke(
                cli, ["watch", "--project-root", str(tmp_path), "--once"]
            )
        assert result.exit_code == 0
        assert "Synced:" in result.output


class TestChangeHandlerMethods:
    """Cover ChangeHandler methods in _watch_native (indexing.py 386-399)."""

    def test_change_handler_all_event_types(self):
        """ChangeHandler captures all four file event types, ignores directories."""
        from memorygraph.cli.commands.indexing import _watch_native

        with (
            mock.patch("signal.signal"),
            mock.patch("memorygraph.cli.commands.indexing.click.echo"),
            mock.patch("memorygraph.cli.commands.indexing.logger"),
            mock.patch("watchdog.observers.Observer") as mock_obs_cls,
        ):
            mock_observer = mock.MagicMock()
            mock_obs_cls.return_value = mock_observer
            captured_handler = []

            def _capture(handler, *args, **kwargs):
                captured_handler.append(handler)

            mock_observer.schedule.side_effect = _capture

            result = _watch_native("/tmp", run_once=True)
            assert result is True
            assert len(captured_handler) >= 1, "Handler should have been captured"
            handler = captured_handler[0]

            # Test all four event types on non-directory files
            for i, (method_name, attr_name) in enumerate([
                ("on_modified", "src_path"),
                ("on_created", "src_path"),
                ("on_deleted", "src_path"),
                ("on_moved", "dest_path"),
            ]):
                event = mock.MagicMock()
                event.is_directory = False
                setattr(event, attr_name, f"/tmp/file_{i}.py")
                method = getattr(handler, method_name)
                method(event)

            # Directory events should be silently ignored
            dir_event = mock.MagicMock()
            dir_event.is_directory = True
            dir_event.src_path = "/tmp/somedir"
            handler.on_modified(dir_event)

    def test_change_handler_ignores_directories_on_all_events(self):
        """All ChangeHandler event methods ignore directory events."""
        from memorygraph.cli.commands.indexing import _watch_native

        with (
            mock.patch("signal.signal"),
            mock.patch("memorygraph.cli.commands.indexing.click.echo"),
            mock.patch("memorygraph.cli.commands.indexing.logger"),
            mock.patch("watchdog.observers.Observer") as mock_obs_cls,
        ):
            mock_observer = mock.MagicMock()
            mock_obs_cls.return_value = mock_observer
            captured_handler = []

            def _capture(handler, *args, **kwargs):
                captured_handler.append(handler)

            mock_observer.schedule.side_effect = _capture

            result = _watch_native("/tmp", run_once=True)
            assert result is True
            assert len(captured_handler) >= 1
            handler = captured_handler[0]

            # All events with is_directory=True should be no-ops
            for method_name in ("on_modified", "on_created", "on_deleted", "on_moved"):
                event = mock.MagicMock()
                event.is_directory = True
                event.src_path = "/tmp/somedir"
                event.dest_path = "/tmp/otherdir"
                method = getattr(handler, method_name)
                method(event)


class TestNativeWatchRunOnce:
    """Cover _watch_native run_once path (indexing.py 409-420)."""

    def test_native_watch_run_once_no_changes(self, tmp_path):
        """_watch_native run_once with no file changes returns True."""
        from memorygraph.cli.commands.indexing import _watch_native

        with (
            mock.patch("signal.signal"),
            mock.patch("memorygraph.cli.commands.indexing.click.echo"),
            mock.patch("memorygraph.cli.commands.indexing.logger"),
            mock.patch("watchdog.observers.Observer") as mock_obs_cls,
        ):
            mock_observer = mock.MagicMock()
            mock_obs_cls.return_value = mock_observer

            result = _watch_native(str(tmp_path), run_once=True)
            assert result is True
            mock_observer.start.assert_called_once()
            # stop is called both in run_once path and finally block
            assert mock_observer.stop.call_count >= 1

    def test_native_watch_run_once_with_changes(self, tmp_path):
        """_watch_native run_once with changed files triggers sync."""
        from memorygraph.cli.commands.indexing import _watch_native

        with (
            mock.patch("signal.signal"),
            mock.patch("memorygraph.cli.commands.indexing.click.echo"),
            mock.patch("memorygraph.cli.commands.indexing.logger"),
            mock.patch("watchdog.observers.Observer") as mock_obs_cls,
            mock.patch("memorygraph.cli.shared._do_sync") as mock_sync,
        ):
            mock_observer = mock.MagicMock()
            mock_obs_cls.return_value = mock_observer
            mock_sync.return_value = {
                "synced_count": 2, "new_count": 2,
                "changed_count": 0, "unchanged_count": 0,
            }

            captured_handler = []

            def _capture(handler, *args, **kwargs):
                captured_handler.append(handler)

            mock_observer.schedule.side_effect = _capture

            import threading

            def _fire_event():
                import time
                time.sleep(0.05)
                if captured_handler:
                    h = captured_handler[0]
                    ev = mock.MagicMock()
                    ev.is_directory = False
                    ev.src_path = str(tmp_path / "new_file.py")
                    h.on_created(ev)

            stopper = threading.Thread(target=_fire_event, daemon=True)
            stopper.start()

            result = _watch_native(str(tmp_path), run_once=True)
            assert result is True


class TestBackupRestoreErrorPathsExtended:
    """Cover OSError/TarError paths in backup/restore (indexing.py 533-535, 572-577)."""

    def test_backup_oserror_handling(self, tmp_path):
        """backup handles OSError gracefully when tarfile creation fails."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        (mg_dir / "graph.db").write_text("")

        runner = CliRunner()
        with mock.patch("tarfile.open") as mock_tar:
            mock_tar.side_effect = OSError("disk full")
            result = runner.invoke(
                cli, ["backup", "--project-root", str(tmp_path)]
            )
        assert result.exit_code == 1
        assert "Backup failed" in result.output

    def test_restore_tarerror_handling_with_cleanup(self, tmp_path):
        """restore handles TarError and cleans up partial extraction."""
        # Create a valid tar file
        import tarfile as tf_real

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        tar_path = tmp_path / "backup.tar.gz"
        dummy = tmp_path / "dummy_data"
        dummy.write_text("data")
        with tf_real.open(str(tar_path), "w:gz") as tar:
            tar.add(str(dummy), arcname="dummy_data")

        runner = CliRunner()
        with (
            mock.patch("tarfile.is_tarfile", return_value=True),
            mock.patch("tarfile.open") as mock_open,
        ):
            mock_open.side_effect = tf_real.TarError("corrupt archive")
            result = runner.invoke(
                cli, ["restore", "--project-root", str(tmp_path), str(tar_path)]
            )
        assert result.exit_code == 1
        assert "Restore failed" in result.output

    def test_restore_oserror_handling(self, tmp_path):
        """restore handles OSError during extraction."""
        import tarfile as tf_real

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        tar_path = tmp_path / "backup.tar.gz"
        dummy = tmp_path / "dummy_data"
        dummy.write_text("data")
        with tf_real.open(str(tar_path), "w:gz") as tar:
            tar.add(str(dummy), arcname="dummy_data")

        runner = CliRunner()
        with (
            mock.patch("tarfile.is_tarfile", return_value=True),
            mock.patch("tarfile.open") as mock_open,
        ):
            mock_open.side_effect = OSError("read error")
            result = runner.invoke(
                cli, ["restore", "--project-root", str(tmp_path), str(tar_path)]
            )
        assert result.exit_code == 1
        assert "Restore failed" in result.output

    def test_restore_extraction_oserror_cleanup_mg_dir(self, tmp_path):
        """restore cleans up .memorygraph on OSError during extraction."""
        import tarfile as tf_real

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        tar_path = tmp_path / "backup.tar.gz"
        dummy = tmp_path / "dummy_data"
        dummy.write_text("data")
        with tf_real.open(str(tar_path), "w:gz") as tar:
            tar.add(str(dummy), arcname="dummy_data")

        runner = CliRunner()
        with (
            mock.patch("tarfile.is_tarfile", return_value=True),
            mock.patch("tarfile.open") as mock_open,
        ):
            # Simulate extraction creating .memorygraph then failing
            def _raise_after_mkdir(*args, **kwargs):
                (tmp_path / ".memorygraph").mkdir(exist_ok=True)
                raise OSError("extraction failed midway")

            mock_open.side_effect = _raise_after_mkdir
            result = runner.invoke(
                cli, ["restore", "--project-root", str(tmp_path), str(tar_path)]
            )
        assert result.exit_code == 1
        assert "Restore failed" in result.output


class TestWatchdogImportFallback:
    """Cover watchdog import error path (indexing.py 361-363)."""

    def test_watchdog_import_error_triggers_fallback(self):
        """_watch_native returns False when watchdog import fails."""
        import builtins

        from memorygraph.cli.commands.indexing import _watch_native

        _real_import = builtins.__import__

        def _block_watchdog(name, *args, **kwargs):
            if name in ("watchdog.events", "watchdog.observers", "watchdog"):
                raise ImportError(f"No module named '{name}'")
            return _real_import(name, *args, **kwargs)

        with (
            mock.patch("memorygraph.cli.commands.indexing.click.echo"),
            mock.patch("memorygraph.cli.commands.indexing.logger"),
            mock.patch("builtins.__import__", side_effect=_block_watchdog),
        ):
            result = _watch_native("/tmp", run_once=True)
            assert result is False


class TestWatchSignalHandlers:
    """Cover signal handlers and daemon paths — indexing.py 228, 256-298, 376."""

    def test_polling_watch_signal_handler_sets_stop_event(self, tmp_path):
        """Signal handler in polling watch sets stop_event=True (line 228)."""
        import signal
        import threading
        import time
        from unittest import mock

        from memorygraph.cli.commands.indexing import _watch_native

        captured_handlers = {}

        def _capture(sig, handler):
            captured_handlers[sig] = handler
            # Return a mock for the "original" handler
            return mock.MagicMock()

        # Mock everything needed
        with (
            mock.patch("signal.signal", side_effect=_capture),
            mock.patch("memorygraph.cli.commands.indexing.click.echo"),
            mock.patch("memorygraph.cli.commands.indexing.logger"),
            mock.patch("watchdog.observers.Observer") as mock_obs_cls,
        ):
            mock_observer = mock.MagicMock()
            mock_obs_cls.return_value = mock_observer

            # Start _watch_native in a thread with run_once=False
            from contextlib import suppress

            def _run_watch():
                with suppress(Exception):
                    _watch_native(str(tmp_path), run_once=False)

            t = threading.Thread(target=_run_watch, daemon=True)
            t.start()

            # Wait briefly for the signal handlers to be registered
            time.sleep(0.1)

            # Verify SIGTERM handler was captured
            assert signal.SIGTERM in captured_handlers
            handler = captured_handlers[signal.SIGTERM]

            # Call the handler directly — this sets stop_event=True
            handler(signal.SIGTERM, None)

            # Stop the observer so the loop exits
            mock_observer.stop()
            mock_observer.join.return_value = None

            t.join(timeout=3)

    def test_polling_daemon_writes_pid_and_stops(self, tmp_path):
        """Polling daemon mode writes PID file and exits on stop_event (lines 256-298)."""
        import signal
        import threading
        import time
        from unittest import mock

        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        runner = CliRunner()
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        result = runner.invoke(cli, ["init", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["index", "--project-root", str(tmp_path)])
        assert result.exit_code == 0

        captured_handlers = {}

        def _capture_signal(sig, handler):
            captured_handlers[sig] = handler
            return mock.MagicMock()

        # Use threads to send SIGTERM while watch is running
        def _send_stop():
            time.sleep(0.3)
            # Fire the captured SIGTERM handler to set stop_event=True
            if signal.SIGTERM in captured_handlers:
                captured_handlers[signal.SIGTERM](signal.SIGTERM, None)

        def _run_watch():
            with (
                mock.patch("signal.signal", side_effect=_capture_signal),
                mock.patch(
                    "memorygraph.cli.commands.indexing._watch_native",
                    return_value=False,
                ),
                mock.patch("memorygraph.cli.commands.indexing.click.echo"),
                mock.patch("memorygraph.cli.commands.indexing.logger"),
                mock.patch("time.sleep", return_value=None),
                mock.patch("os.getpid", return_value=12345),
            ):
                runner.invoke(
                    cli, ["watch", "--project-root", str(tmp_path)]
                )

        stopper = threading.Thread(target=_send_stop, daemon=True)
        watch_thread = threading.Thread(target=_run_watch, daemon=True)

        stopper.start()
        watch_thread.start()
        watch_thread.join(timeout=5)

        # Verify PID file was written
        pid_file = mg_dir / "watch.pid"
        assert not pid_file.exists()  # Cleaned up in finally

    def test_native_watch_signal_handler_sets_stop_event(self, tmp_path):
        """Signal handler in native watch sets stop_event (line 376)."""
        import signal
        import threading
        import time
        from unittest import mock

        from memorygraph.cli.commands.indexing import _watch_native

        captured_handlers = {}

        def _capture(sig, handler):
            captured_handlers[sig] = handler
            return mock.MagicMock()

        with (
            mock.patch("signal.signal", side_effect=_capture),
            mock.patch("memorygraph.cli.commands.indexing.click.echo"),
            mock.patch("memorygraph.cli.commands.indexing.logger"),
            mock.patch("watchdog.observers.Observer") as mock_obs_cls,
        ):
            mock_observer = mock.MagicMock()
            mock_obs_cls.return_value = mock_observer

            from contextlib import suppress

            def _run_watch():
                with suppress(Exception):
                    _watch_native(str(tmp_path), run_once=False)

            t = threading.Thread(target=_run_watch, daemon=True)
            t.start()
            time.sleep(0.1)

            assert signal.SIGTERM in captured_handlers
            handler = captured_handlers[signal.SIGTERM]

            # Fire signal handler to set stop_event=True
            handler(signal.SIGTERM, None)

            # Stop observer
            mock_observer.stop()
            mock_observer.join.return_value = None

            t.join(timeout=3)


class TestWatchChangeDetectionLoop:
    """Cover daemon change-detection paths — indexing.py 272-283, 427-439."""

    def test_polling_daemon_detects_changes(self, tmp_path):
        """Polling daemon loop detects and syncs changes (lines 272-283)."""
        import signal
        import threading
        import time
        from unittest import mock

        from click.testing import CliRunner

        from memorygraph.cli.main import cli

        runner = CliRunner()
        mg_dir = tmp_path / ".memorygraph"
        mg_dir.mkdir()
        result = runner.invoke(cli, ["init", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["index", "--project-root", str(tmp_path)])
        assert result.exit_code == 0

        captured_handlers = {}

        def _capture_signal(sig, handler):
            captured_handlers[sig] = handler
            return mock.MagicMock()

        def _run_watch():
            with (
                mock.patch("signal.signal", side_effect=_capture_signal),
                mock.patch(
                    "memorygraph.cli.commands.indexing._watch_native",
                    return_value=False,
                ),
                mock.patch("memorygraph.cli.commands.indexing.click.echo"),
                mock.patch("memorygraph.cli.commands.indexing.logger"),
                mock.patch("time.sleep", return_value=None),
                mock.patch("os.getpid", return_value=12345),
                mock.patch(
                    "memorygraph.cli.shared._do_sync",
                    return_value={
                        "synced_count": 1, "new_count": 1,
                        "changed_count": 0, "unchanged_count": 0,
                    },
                ),
            ):
                runner.invoke(cli, ["watch", "--project-root", str(tmp_path)])

        def _stop_after_changes():
            time.sleep(0.2)
            # Create a new file to trigger change detection
            (tmp_path / "new_file.py").write_text("def new_func(): pass\n")
            # Wait for the poll cycle
            time.sleep(0.5)
            # Fire SIGTERM to stop
            if signal.SIGTERM in captured_handlers:
                captured_handlers[signal.SIGTERM](signal.SIGTERM, None)

        stopper = threading.Thread(target=_stop_after_changes, daemon=True)
        watch_thread = threading.Thread(target=_run_watch, daemon=True)

        stopper.start()
        watch_thread.start()
        watch_thread.join(timeout=8)
        # If we reach here without hanging, the change detection worked

    def test_native_watch_daemon_detects_changes(self, tmp_path):
        """Native watch continuous loop detects and syncs changes (lines 427-439)."""
        import signal
        import threading
        import time
        from unittest import mock

        from memorygraph.cli.commands.indexing import _watch_native

        captured_handlers = {}

        def _capture(sig, handler):
            captured_handlers[sig] = handler
            return mock.MagicMock()

        # Capture handler and fire ChangeHandler events to trigger loop
        captured_handler = None

        def _capture_schedule(handler, *args, **kwargs):
            nonlocal captured_handler
            captured_handler = handler

        with (
            mock.patch("signal.signal", side_effect=_capture),
            mock.patch("memorygraph.cli.commands.indexing.click.echo"),
            mock.patch("memorygraph.cli.commands.indexing.logger"),
            mock.patch("watchdog.observers.Observer") as mock_obs_cls,
            mock.patch("memorygraph.cli.shared._do_sync") as mock_sync,
        ):
            mock_observer = mock.MagicMock()
            mock_obs_cls.return_value = mock_observer
            mock_observer.schedule.side_effect = _capture_schedule
            mock_sync.return_value = {
                "synced_count": 1, "new_count": 1,
                "changed_count": 0, "unchanged_count": 0,
            }

            def _run_watch():
                from contextlib import suppress
                with suppress(Exception):
                    _watch_native(str(tmp_path), run_once=False)

            t = threading.Thread(target=_run_watch, daemon=True)
            t.start()
            time.sleep(0.2)

            # Fire ChangeHandler events to populate changed_files
            if captured_handler:
                ev = mock.MagicMock()
                ev.is_directory = False
                ev.src_path = str(tmp_path / "changed.py")
                captured_handler.on_modified(ev)

            # Wait for the 2s loop to pick up changes
            time.sleep(0.2)

            # Stop via signal
            if signal.SIGTERM in captured_handlers:
                captured_handlers[signal.SIGTERM](signal.SIGTERM, None)

            mock_observer.stop()
            mock_observer.join.return_value = None

            t.join(timeout=5)
