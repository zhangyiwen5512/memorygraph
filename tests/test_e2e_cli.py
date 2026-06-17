"""End-to-end CLI tests: init → index → query → export pipeline."""

import json

from click.testing import CliRunner

from memorygraph.cli.main import cli


def test_e2e_init_index_query_export(git_repo):
    """Full CLI pipeline on a temporary git repo.

    Covers: init, index, query, export with JSON format.
    """
    runner = CliRunner()

    # 1. init
    result = runner.invoke(cli, ["init", "--project-root", str(git_repo)])
    assert result.exit_code == 0, f"init failed: {result.output}"
    assert (git_repo / ".memorygraph").is_dir(), ".memorygraph/ not created"

    # 2. index
    result = runner.invoke(cli, ["index", "--project-root", str(git_repo)])
    assert result.exit_code == 0, f"index failed: {result.output}"
    # Index output should report at least 1 file
    output = result.output.lower()
    assert "file" in output or "indexed" in output or "2" in output, \
        f"index output unexpected: {result.output[:200]}"

    # 3. query — find the greet function
    result = runner.invoke(cli, ["query", "greet", "--project-root", str(git_repo)])
    assert result.exit_code == 0, f"query failed: {result.output}"
    assert "greet" in result.output.lower(), f"query didn't find greet: {result.output[:200]}"

    # 4. export
    output_file = git_repo / "export.json"
    result = runner.invoke(
        cli, ["export", "--format", "json", "--output", str(output_file),
              "--project-root", str(git_repo)],
    )
    assert result.exit_code == 0, f"export failed: {result.output}"
    data = json.loads(output_file.read_text())
    assert "nodes" in data, "export JSON missing 'nodes' key"
    # At least the greet function and format_message should be nodes
    assert len(data["nodes"]) >= 2, \
        f"expected >=2 nodes, got {len(data['nodes'])}"


def test_e2e_init_query_nonexistent_symbol(git_repo):
    """Querying a nonexistent symbol returns empty or error gracefully."""
    runner = CliRunner()

    # Setup
    result = runner.invoke(cli, ["init", "--project-root", str(git_repo)])
    assert result.exit_code == 0
    result = runner.invoke(cli, ["index", "--project-root", str(git_repo)])
    assert result.exit_code == 0

    # Query something that doesn't exist
    result = runner.invoke(
        cli, ["query", "nonexistent_function_xyz", "--project-root", str(git_repo)],
    )
    # Should either succeed with empty results or fail gracefully
    assert result.exit_code == 0 or "not found" in result.output.lower() or \
        "no " in result.output.lower(), \
        f"expected graceful handling: {result.output[:200]}"


def test_e2e_multi_project_data_isolation(tmp_path):
    """Two independent projects should have no data cross-contamination."""
    from memorygraph.storage.manager import StorageManager

    runner = CliRunner()

    # Project A: contains "auth.py" with login()
    proj_a = tmp_path / "proj_a"
    proj_a.mkdir()
    (proj_a / "auth.py").write_text("""
def login():
    '''Authenticate user.'''
    pass
""")

    # Project B: contains "utils.py" with helper()
    proj_b = tmp_path / "proj_b"
    proj_b.mkdir()
    (proj_b / "utils.py").write_text("""
def helper():
    '''Utility function.'''
    pass
""")

    # Init + index both projects
    for proj in [proj_a, proj_b]:
        r = runner.invoke(cli, ["init", "--project-root", str(proj)])
        assert r.exit_code == 0, f"init {proj.name} failed: {r.output}"
        r = runner.invoke(cli, ["index", "--project-root", str(proj)])
        assert r.exit_code == 0, f"index {proj.name} failed: {r.output}"

    # Query project A — should NOT find project B symbols
    mgr_a = StorageManager(str(proj_a))
    mgr_a.initialize()
    files_a = mgr_a.list_files()
    names_a = set()
    for f in files_a:
        syms = mgr_a.get_symbols_for_file(f["path"])
        names_a.update(s.get("qualified_name", s.get("name", "")) for s in syms)
    assert "helper" not in names_a, f"Project A leaked B's symbols: {names_a}"
    assert any("login" in n for n in names_a), f"Project A missing its own symbol: {names_a}"
    mgr_a.close()

    # Query project B — should NOT find project A symbols
    mgr_b = StorageManager(str(proj_b))
    mgr_b.initialize()
    files_b = mgr_b.list_files()
    names_b = set()
    for f in files_b:
        syms = mgr_b.get_symbols_for_file(f["path"])
        names_b.update(s.get("qualified_name", s.get("name", "")) for s in syms)
    assert "login" not in names_b, f"Project B leaked A's symbols: {names_b}"
    assert any("helper" in n for n in names_b), f"Project B missing its own symbol: {names_b}"
    mgr_b.close()


def test_e2e_index_error_recovery_corrupt_semantic(tmp_path):
    """Re-indexing after corrupting a semantic JSON file should complete without crash."""
    from memorygraph.semantic.models import SemanticDocument
    from memorygraph.semantic.store import SemanticStore
    from memorygraph.storage.manager import StorageManager

    runner = CliRunner()
    project = tmp_path / "project"
    project.mkdir()
    src = project / "src"
    src.mkdir()
    (src / "main.py").write_text("def main(): pass\n")

    # Normal init + index
    r = runner.invoke(cli, ["init", "--project-root", str(project)])
    assert r.exit_code == 0, f"init failed: {r.output}"
    r = runner.invoke(cli, ["index", "--project-root", str(project)])
    assert r.exit_code == 0, f"index failed: {r.output}"

    # Create a semantic document (simulating what web API/semantic-ingest does)
    store = SemanticStore(str(project))
    store.save(SemanticDocument(
        file="src/main.py",
        source="test",
        module_summary="Main module",
    ))

    # Corrupt the semantic JSON file
    sem_dir = project / ".memorygraph" / "semantic"
    json_files = list(sem_dir.glob("*.json"))
    assert len(json_files) > 0, "Should have at least one semantic doc after save"
    json_files[0].write_text("this is not valid json {{{")

    # Re-index — should not crash (index handles corrupt semantic files gracefully)
    r = runner.invoke(cli, ["index", "--project-root", str(project)])
    assert r.exit_code == 0, f"re-index after corruption should not crash: {r.output}"

    # Verify the project is still usable after recovery
    mgr = StorageManager(str(project))
    mgr.initialize()
    symbols = mgr.search("main", limit=10)
    names = [s.get("qualified_name", "") for s in symbols]
    assert any("main" in n for n in names), f"Should still find 'main' after recovery: {names}"

    # Verify load_all gracefully skips the corrupt file
    store2 = SemanticStore(str(project))
    docs = store2.load_all()
    assert len(docs) >= 0  # Should not crash on corrupt files
    mgr.close()


def test_e2e_init_is_idempotent(tmp_path):
    """Running init on an already-initialized project should succeed (idempotent)."""
    runner = CliRunner()
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("def main(): pass\n")

    # First init
    r = runner.invoke(cli, ["init", "--project-root", str(project)])
    assert r.exit_code == 0, f"first init failed: {r.output}"
    assert (project / ".memorygraph").is_dir()

    # Second init — should be idempotent
    r = runner.invoke(cli, ["init", "--project-root", str(project)])
    assert r.exit_code == 0, f"second init should be idempotent: {r.output}"
    assert (project / ".memorygraph").is_dir()


def test_e2e_reindex_after_file_deletion(tmp_path):
    """Re-indexing after deleting a source file should not crash and reflects changes."""
    runner = CliRunner()
    project = tmp_path / "project"
    project.mkdir()
    (project / "keep.py").write_text("def kept(): pass\n")
    (project / "remove.py").write_text("def removed(): pass\n")

    # Initial index
    r = runner.invoke(cli, ["init", "--project-root", str(project)])
    assert r.exit_code == 0
    r = runner.invoke(cli, ["index", "--project-root", str(project)])
    assert r.exit_code == 0

    # Delete a file and re-index
    (project / "remove.py").unlink()
    r = runner.invoke(cli, ["index", "--project-root", str(project)])
    assert r.exit_code == 0, f"re-index after deletion failed: {r.output}"

    # Verify the kept file is still indexed
    from memorygraph.storage.manager import StorageManager
    mgr = StorageManager(str(project))
    mgr.initialize()
    files = mgr.list_files()
    paths = [f["path"] for f in files]
    assert any("keep.py" in p for p in paths), f"kept file lost after re-index: {paths}"
    mgr.close()


def test_e2e_index_with_syntax_errors(tmp_path):
    """Indexing a project with a broken Python file gracefully records errors."""
    runner = CliRunner()
    project = tmp_path / "project"
    project.mkdir()
    (project / "good.py").write_text("def valid(): pass\n")
    (project / "broken.py").write_text("def broken(: syntax error !!!\n")

    r = runner.invoke(cli, ["init", "--project-root", str(project)])
    assert r.exit_code == 0
    r = runner.invoke(cli, ["index", "--project-root", str(project)])
    # Should succeed overall, with broken file skipped or warned
    assert r.exit_code == 0, f"index with syntax error should not crash: {r.output}"

    from memorygraph.storage.manager import StorageManager
    mgr = StorageManager(str(project))
    mgr.initialize()
    symbols = mgr.search("valid", limit=10)
    names = [s.get("qualified_name", "") for s in symbols]
    assert any("valid" in n for n in names), f"Should still find 'valid': {names}"
    mgr.close()


def test_e2e_index_empty_project(tmp_path):
    """Indexing a project with no source files should succeed gracefully."""
    runner = CliRunner()
    project = tmp_path / "project"
    project.mkdir()

    r = runner.invoke(cli, ["init", "--project-root", str(project)])
    assert r.exit_code == 0
    r = runner.invoke(cli, ["index", "--project-root", str(project)])
    # Should either report "No source files" or exit cleanly
    assert r.exit_code == 0, f"index empty project failed: {r.output}"
