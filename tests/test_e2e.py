"""End-to-end integration tests for memorygraph pipeline."""
import os
import tempfile
from pathlib import Path


class TestE2EInitIndexQuery:
    """E2E: init → index → query via StorageManager API."""

    def test_e2e_pipeline_init_index_query(self):
        """Complete pipeline: init, index files, query results."""
        tmpdir = tempfile.mkdtemp()
        try:
            # Create source files
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "main.py").write_text(
                "def helper(x):\n    return x * 2\n\n"
                "def main():\n    result = helper(21)\n    print(result)\n"
            )
            (src_dir / "utils.py").write_text(
                "from src.main import helper\n\n"
                "def wrapper(y):\n    return helper(y) + 1\n"
            )

            from memorygraph.parsing.batch import ParallelParser
            from memorygraph.parsing.registry import LanguageRegistry
            from memorygraph.storage import StorageManager

            # Step 1: Initialize storage
            mgr = StorageManager(tmpdir)
            mgr.initialize()

            # Step 2: Collect and parse files
            from memorygraph.cli.shared import _collect_files
            registry = LanguageRegistry()
            files = _collect_files(tmpdir, registry)
            assert len(files) >= 2, f"Expected ≥2 files, got {len(files)}"

            # Step 3: Index
            parser = ParallelParser(registry)
            results = parser.parse_files(
                [Path(f) for f in files], resolve_symbols=True
            )
            count = mgr.bulk_upsert(results)
            assert count >= 2, f"Expected ≥2 indexed, got {count}"

            # Step 4: Query
            node = mgr.get_node("helper")
            assert node is not None, "helper should be findable"
            assert node["kind"] == "function"

            callers = mgr.get_callers("helper")
            assert len(callers) > 0, "helper should have callers"

            callees = mgr.get_callees("main")
            assert len(callees) > 0, "main should call helper"

            mgr.close()
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_e2e_pipeline_handles_parse_errors(self):
        """Pipeline handles files with parse errors gracefully."""
        tmpdir = tempfile.mkdtemp()
        try:
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "good.py").write_text("def foo(): pass\n")
            (src_dir / "bad.py").write_bytes(b"\x00\x01\x02\xff\xfe\xfd")  # binary garbage

            from memorygraph.parsing.batch import ParallelParser
            from memorygraph.parsing.registry import LanguageRegistry
            from memorygraph.storage import StorageManager

            mgr = StorageManager(tmpdir)
            mgr.initialize()

            registry = LanguageRegistry()
            parser = ParallelParser(registry)
            results = parser.parse_files(
                [src_dir / "good.py", src_dir / "bad.py"],
                resolve_symbols=True
            )

            # good.py should parse successfully
            good_result = results[str(src_dir / "good.py")]
            assert not good_result.fatal_error

            # Tree-sitter is fault-tolerant: binary file parses without crash
            # (produces empty result — no symbols, no fatal error)
            bad_result = results[str(src_dir / "bad.py")]
            assert bad_result is not None  # file was processed
            assert not bad_result.symbols  # binary → no symbols

            good_count = mgr.bulk_upsert({
                str(src_dir / "good.py"): good_result
            })
            assert good_count == 1

            mgr.close()
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_e2e_incremental_index(self):
        """Incremental index: add new file, re-index, verify only new file indexed."""
        import shutil

        tmpdir = tempfile.mkdtemp()
        try:
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir(parents=True)

            # Phase 1: Index initial file
            (src_dir / "module_a.py").write_text(
                "def alpha():\n    return 1\n\ndef beta():\n    return 2\n"
            )

            from memorygraph.cli.shared import _collect_files
            from memorygraph.parsing.batch import ParallelParser
            from memorygraph.parsing.registry import LanguageRegistry
            from memorygraph.storage import StorageManager

            registry = LanguageRegistry()
            mgr = StorageManager(tmpdir)
            mgr.initialize()

            files = _collect_files(tmpdir, registry)
            parser = ParallelParser(registry)
            results = parser.parse_files(
                [Path(f) for f in files], resolve_symbols=True
            )
            count1 = mgr.bulk_upsert(results)
            assert count1 == 1, f"Expected 1 file indexed, got {count1}"
            assert mgr.stats()["file_count"] == 1

            # Phase 2: Add a new file without re-initializing
            (src_dir / "module_b.py").write_text(
                "from src.module_a import alpha\n\n"
                "def gamma():\n    return alpha() + 3\n"
            )

            files2 = _collect_files(tmpdir, registry)
            assert len(files2) >= 2
            new_files = [f for f in files2 if f not in files]
            assert len(new_files) == 1

            results2 = parser.parse_files(
                [Path(f) for f in new_files], resolve_symbols=True
            )
            count2 = mgr.bulk_upsert(results2)
            assert count2 == 1
            assert mgr.stats()["file_count"] == 2

            # Verify cross-file edges exist
            callees = mgr.get_callees("gamma")
            assert len(callees) > 0, "gamma should call alpha"

            mgr.close()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_e2e_empty_project_graceful(self):
        """Empty project (no source files) should not crash."""
        import shutil

        tmpdir = tempfile.mkdtemp()
        try:
            from memorygraph.cli.shared import _collect_files
            from memorygraph.parsing.registry import LanguageRegistry
            from memorygraph.storage import StorageManager

            mgr = StorageManager(tmpdir)
            mgr.initialize()
            registry = LanguageRegistry()
            files = _collect_files(tmpdir, registry)
            assert len(files) == 0, "Empty dir should have no files"

            # Index with no files should succeed with 0
            mgr.close()
            # Re-open and verify stats
            mgr2 = StorageManager(tmpdir)
            mgr2.initialize()
            st = mgr2.stats()
            assert st["file_count"] == 0
            assert st["symbol_count"] == 0
            mgr2.close()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_e2e_mixed_languages(self):
        """Project with Python + TypeScript files — only supported langs indexed."""
        import shutil

        tmpdir = tempfile.mkdtemp()
        try:
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir(parents=True)
            (src_dir / "main.py").write_text("def foo(): pass\n")
            (src_dir / "helper.ts").write_text("function bar() { return 1; }\n")
            (src_dir / "config.yaml").write_text("key: value\n")
            (src_dir / "README.md").write_text("# Project\n")

            from memorygraph.cli.shared import _collect_files
            from memorygraph.parsing.batch import ParallelParser
            from memorygraph.parsing.registry import LanguageRegistry
            from memorygraph.storage import StorageManager

            mgr = StorageManager(tmpdir)
            mgr.initialize()
            registry = LanguageRegistry()
            files = _collect_files(tmpdir, registry)
            assert len(files) >= 1, f"Should find source files, got {files}"

            parser = ParallelParser(registry)
            results = parser.parse_files(
                [Path(f) for f in files], resolve_symbols=True
            )
            count = mgr.bulk_upsert(results)
            assert count >= 1, f"Expected ≥1 indexed, got {count}"
            mgr.close()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_e2e_stats_consistency(self):
        """Verify stats are consistent: re-index same files should not duplicate."""
        import shutil

        tmpdir = tempfile.mkdtemp()
        try:
            (Path(tmpdir) / "a.py").write_text("def f1(): pass\n")
            (Path(tmpdir) / "b.py").write_text("def f2(): pass\n")

            from memorygraph.cli.shared import _collect_files
            from memorygraph.parsing.batch import ParallelParser
            from memorygraph.parsing.registry import LanguageRegistry
            from memorygraph.storage import StorageManager

            registry = LanguageRegistry()
            mgr = StorageManager(tmpdir)
            mgr.initialize()
            files = _collect_files(tmpdir, registry)

            parser = ParallelParser(registry)
            results = parser.parse_files(
                [Path(f) for f in files], resolve_symbols=True
            )
            mgr.bulk_upsert(results)

            st = mgr.stats()
            assert st["file_count"] == 2
            assert st["symbol_count"] >= 2  # f1 + f2
            assert st["edge_count"] == 0  # No cross-file calls

            # Re-index same files (should update, not duplicate)
            results2 = parser.parse_files(
                [Path(f) for f in files], resolve_symbols=True
            )
            mgr.bulk_upsert(results2)
            st2 = mgr.stats()
            assert st2["file_count"] == 2, "Re-index should not duplicate"
            assert st2["symbol_count"] >= 2
            mgr.close()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


def test_collect_files_oserror_graceful(monkeypatch, tmp_path):
    """_collect_files should handle OSError subclasses like FileNotFoundError."""
    from memorygraph.cli.shared import _collect_files
    from memorygraph.parsing.registry import LanguageRegistry

    registry = LanguageRegistry()
    project_root = str(tmp_path)
    (tmp_path / "test.py").write_text("x = 1")

    calls = [0]
    original_scandir = os.scandir

    def _failing_scandir(path):
        calls[0] += 1
        if calls[0] >= 2:
            raise FileNotFoundError(f"Directory vanished: {path}")
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", _failing_scandir)
    files = _collect_files(project_root, registry)
    assert any("test.py" in f for f in files)
