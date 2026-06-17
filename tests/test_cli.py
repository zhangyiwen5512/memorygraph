"""Tests for CLI commands."""
import os
import tempfile

import pytest
from click.testing import CliRunner

from memorygraph.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_project():
    """Create a temporary project with a Python file."""
    tmpdir = tempfile.mkdtemp()
    src_dir = os.path.join(tmpdir, "src")
    os.makedirs(src_dir)
    with open(os.path.join(src_dir, "hello.py"), "w") as f:
        f.write("def greet():\n    return 'hello'\n")
    yield tmpdir
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


def _invoke(runner, tmp_project, cmd, *args):
    """Invoke CLI with command first, then --project-root."""
    return runner.invoke(cli, [cmd] + list(args) + ["--project-root", tmp_project])


def test_init_creates_db(runner, tmp_project):
    result = _invoke(runner, tmp_project, "init")
    assert result.exit_code == 0
    assert "Initialized" in result.output
    assert os.path.exists(os.path.join(tmp_project, ".memorygraph", "memorygraph.db"))


def test_init_idempotent(runner, tmp_project):
    _invoke(runner, tmp_project, "init")
    result = _invoke(runner, tmp_project, "init")
    assert result.exit_code == 0
    assert "Already initialized" in result.output


def test_status_empty(runner, tmp_project):
    _invoke(runner, tmp_project, "init")
    result = _invoke(runner, tmp_project, "status")
    assert result.exit_code == 0
    assert "Symbols:" in result.output


def test_index_and_status(runner, tmp_project):
    _invoke(runner, tmp_project, "init")
    result = _invoke(runner, tmp_project, "index")
    assert result.exit_code == 0
    stats = _invoke(runner, tmp_project, "status")
    assert "Symbols:" in stats.output


def test_query(runner, tmp_project):
    _invoke(runner, tmp_project, "init")
    _invoke(runner, tmp_project, "index")
    result = _invoke(runner, tmp_project, "query", "greet")
    assert result.exit_code == 0
    assert "greet" in result.output


def test_files(runner, tmp_project):
    _invoke(runner, tmp_project, "init")
    _invoke(runner, tmp_project, "index")
    result = _invoke(runner, tmp_project, "files")
    assert result.exit_code == 0
    assert "hello.py" in result.output


def test_sync_unchanged(runner, tmp_project):
    _invoke(runner, tmp_project, "init")
    _invoke(runner, tmp_project, "index")
    result = _invoke(runner, tmp_project, "sync")
    assert result.exit_code == 0
    assert "up to date" in result.output


def test_sync_detects_change(runner, tmp_project):
    _invoke(runner, tmp_project, "init")
    _invoke(runner, tmp_project, "index")
    # Modify a file
    with open(os.path.join(tmp_project, "src", "hello.py"), "a") as f:
        f.write("def new_func():\n    pass\n")
    result = _invoke(runner, tmp_project, "sync")
    assert result.exit_code == 0
    assert "Changed: 1" in result.output or "1 modified" in result.output


def test_help_shows_commands(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    for cmd in ["init", "index", "sync", "status", "query", "files", "context", "affected"]:
        assert cmd in result.output


def test_main_module_runs_via_cli():
    """Running `python -m memorygraph.cli.main --help` works."""
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "-m", "memorygraph.cli.main", "--help"],
        capture_output=True, text=True,
        cwd="/home/zhangyiwen/Desktop/code-memory-graph",
    )
    assert result.returncode == 0
    assert "init" in result.stdout
    assert "index" in result.stdout


def test_main_module_import_does_not_execute():
    """Importing memorygraph.cli.main should NOT run the CLI."""
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "-c", "import memorygraph.cli.main; print('imported')"],
        capture_output=True, text=True,
        cwd="/home/zhangyiwen/Desktop/code-memory-graph",
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "imported"


def test_cli_main_run_as_main():
    """Running cli.main as __main__ should execute cli() (covers line 34)."""
    import runpy
    import sys
    from unittest import mock

    saved = {}
    to_remove = [k for k in list(sys.modules.keys()) if k == "memorygraph.cli.main"]
    for k in to_remove:
        saved[k] = sys.modules.pop(k)

    try:
        with mock.patch("click.Group.main") as mock_main:
            runpy.run_module(
                "memorygraph.cli.main", run_name="__main__", alter_sys=False
            )
        mock_main.assert_called_once()
    finally:
        for k, v in saved.items():
            sys.modules[k] = v
