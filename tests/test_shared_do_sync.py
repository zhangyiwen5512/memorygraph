"""Test _do_sync function for coverage."""
import os
import tempfile

import pytest

from memorygraph.cli.shared import _do_sync
from memorygraph.storage import StorageManager


@pytest.fixture
def temp_project_with_code():
    """Create a temp project with source files and initialize DB."""
    tmpdir = tempfile.mkdtemp()
    src_dir = os.path.join(tmpdir, "src")
    os.makedirs(src_dir)

    with open(os.path.join(src_dir, "app.py"), "w") as f:
        f.write("def foo():\n    return 42\n")

    # Initialize the project
    mgr = StorageManager(tmpdir)
    mgr.initialize()
    mgr.close()

    yield tmpdir
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_do_sync_new_project(temp_project_with_code):
    """Sync on a project with code files."""
    result = _do_sync(temp_project_with_code)
    assert "new_count" in result
    assert "synced_count" in result


def test_do_sync_on_empty_dir(tmp_path):
    """Sync on empty directory."""
    mgr = StorageManager(str(tmp_path))
    mgr.initialize()
    mgr.close()
    result = _do_sync(str(tmp_path))
    assert result["synced_count"] == 0


def test_do_sync_analyze_semantic_store_unavailable(temp_project_with_code):
    """Sync with semantic ingest failing → exception handler (shared.py:234-235)."""
    from unittest import mock
    with mock.patch(
        "memorygraph.semantic.store.SemanticStore",
        side_effect=RuntimeError("Semantic store unavailable"),
    ):
        result = _do_sync(temp_project_with_code)
        assert "synced_count" in result
        # The exception should be caught; semantic_ingested may be 0 or absent
        assert result.get("semantic_ingested", 0) == 0
