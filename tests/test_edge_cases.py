"""Edge case tests for memorygraph.

Covers empty repos, large files, binary files, concurrency,
corrupt databases, and Unicode paths.
"""

import shutil
import tempfile
import threading
from pathlib import Path

from click.testing import CliRunner

from memorygraph.cli.main import cli
from memorygraph.storage.cache import QueryCache


class TestEmptyRepo:
    """Indexing an empty project should not crash."""

    def test_init_and_index_empty_repo(self):
        tmp = tempfile.mkdtemp()
        try:
            runner = CliRunner()
            r1 = runner.invoke(cli, ["init", "--project-root", tmp])
            assert r1.exit_code == 0
            r2 = runner.invoke(cli, ["index", "--project-root", tmp])
            assert r2.exit_code == 0
            assert "No source files found" in r2.output
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestLargeFile:
    """A ~10000 line Python file should parse without timeout."""

    def test_large_file_parses_without_timeout(self):
        tmp = tempfile.mkdtemp()
        try:
            runner = CliRunner()
            r_init = runner.invoke(cli, ["init", "--project-root", tmp])
            assert r_init.exit_code == 0

            lines = ["# Large auto-generated file\n"]
            for i in range(5000):
                lines.append(f"def func_{i}(x: int) -> int:\n    return x + {i}\n")
            py_file = Path(tmp) / "large_file.py"
            py_file.write_text("\n".join(lines))

            r_idx = runner.invoke(cli, ["index", "--project-root", tmp])
            assert r_idx.exit_code == 0
            assert "Indexed 1 files" in r_idx.output
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestBinarySkip:
    """Binary files (.so, .png) should be skipped; only .py indexed."""

    def test_binary_files_skipped(self):
        tmp = tempfile.mkdtemp()
        try:
            runner = CliRunner()
            r_init = runner.invoke(cli, ["init", "--project-root", tmp])
            assert r_init.exit_code == 0

            (Path(tmp) / "libtest.so").write_bytes(
                b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 100
            )
            (Path(tmp) / "icon.png").write_bytes(
                b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
            )
            (Path(tmp) / "real.py").write_text("def foo():\n    return 1\n")

            r_idx = runner.invoke(cli, ["index", "--project-root", tmp])
            assert r_idx.exit_code == 0
            assert "Indexed 1 files" in r_idx.output
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestConcurrency:
    """QueryCache thread safety + dual index no corruption."""

    def test_concurrent_query_cache_access(self):
        cache = QueryCache(maxsize=100)
        errors = []

        def worker(thread_id):
            try:
                for i in range(200):
                    key = f"t{thread_id}_k{i}"
                    cache.put(key, {"val": i})
                    result = cache.get(key)
                    if result is not None:
                        assert result["val"] == i
            except Exception as e:
                errors.append((thread_id, e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == [], f"Concurrency errors: {errors}"

    def test_dual_index_access_does_not_corrupt(self):
        tmp = tempfile.mkdtemp()
        try:
            runner = CliRunner()
            r_init = runner.invoke(cli, ["init", "--project-root", tmp])
            assert r_init.exit_code == 0

            (Path(tmp) / "mod_a.py").write_text("def a():\n    return 1\n")
            (Path(tmp) / "mod_b.py").write_text("def b():\n    return 2\n")

            r_idx = runner.invoke(cli, ["index", "--project-root", tmp])
            assert r_idx.exit_code == 0

            r_idx2 = runner.invoke(cli, ["index", "--project-root", tmp])
            assert r_idx2.exit_code == 0
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCorruptDB:
    """Zero-byte or corrupt DB file should produce a clear error or recover."""

    def test_corrupt_db_reports_error(self):
        tmp = tempfile.mkdtemp()
        try:
            runner = CliRunner()
            r_init = runner.invoke(cli, ["init", "--project-root", tmp])
            assert r_init.exit_code == 0

            db_path = Path(tmp) / ".memorygraph" / "memorygraph.db"
            assert db_path.exists()
            db_path.write_bytes(b"\x00" * 4096)

            r_idx = runner.invoke(cli, ["index", "--project-root", tmp])
            # The command may exit non-zero on a corrupt DB, or exit zero
            # with an error message. Accept either.
            if r_idx.exit_code == 0:
                output_lower = r_idx.output.lower()
                assert (
                    "error" in output_lower
                    or "corrupt" in output_lower
                    or "skip" in output_lower
                )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_init_recreates_after_corrupt_db_deleted(self):
        """After removing a corrupt DB, init should create a fresh database."""
        tmp = tempfile.mkdtemp()
        try:
            runner = CliRunner()
            r_init = runner.invoke(cli, ["init", "--project-root", tmp])
            assert r_init.exit_code == 0

            db_path = Path(tmp) / ".memorygraph" / "memorygraph.db"
            # Corrupt it
            db_path.write_bytes(b"not a valid sqlite database\xff\xfe")

            # Remove corrupt DB and re-init
            db_path.unlink()
            r_reinit = runner.invoke(cli, ["init", "--project-root", tmp])
            assert r_reinit.exit_code == 0
            assert "Initialized" in r_reinit.output
            assert db_path.exists()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_empty_db_file_recovers(self):
        """A zero-byte DB file should be handled gracefully by init."""
        tmp = tempfile.mkdtemp()
        try:
            # Create empty DB file without init
            db_dir = Path(tmp) / ".memorygraph"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = db_dir / "memorygraph.db"
            db_path.write_text("")

            runner = CliRunner()
            r_init = runner.invoke(cli, ["init", "--project-root", tmp])
            assert r_init.exit_code == 0
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestConcurrencyAdvanced:
    """Concurrent index + query under thread pressure."""

    def test_concurrent_index_and_query(self):
        """Multiple threads indexing and querying without data corruption."""
        import sqlite3

        tmp = tempfile.mkdtemp()
        try:
            runner = CliRunner()
            r_init = runner.invoke(cli, ["init", "--project-root", tmp])
            assert r_init.exit_code == 0

            # Create multiple Python files
            for i in range(10):
                (Path(tmp) / f"mod_{i}.py").write_text(
                    f"def func_{i}(x):\n    return helper_{i}(x)\n\n"
                    f"def helper_{i}(x):\n    return x + {i}\n"
                )

            # First index
            r_idx = runner.invoke(cli, ["index", "--project-root", tmp])
            assert r_idx.exit_code == 0

            errors = []

            def index_worker():
                try:
                    r = runner.invoke(cli, ["index", "--project-root", tmp])
                    if r.exit_code != 0:
                        errors.append(f"index failed: {r.output[:200]}")
                except Exception as e:
                    errors.append(f"index exception: {e}")

            def query_worker():
                try:
                    db_path = str(Path(tmp) / ".memorygraph" / "memorygraph.db")
                    conn = sqlite3.connect(db_path)
                    conn.execute("SELECT COUNT(*) FROM files")
                    conn.execute("SELECT COUNT(*) FROM fts_index")
                    conn.close()
                except Exception as e:
                    errors.append(f"query exception: {e}")

            threads = []
            for _ in range(3):
                threads.append(threading.Thread(target=index_worker))
                threads.append(threading.Thread(target=query_worker))

            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            assert errors == [], f"Concurrency errors: {errors}"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_rapid_reindex_is_idempotent(self):
        """Indexing the same project multiple times should be stable."""
        tmp = tempfile.mkdtemp()
        try:
            runner = CliRunner()
            r_init = runner.invoke(cli, ["init", "--project-root", tmp])
            assert r_init.exit_code == 0

            (Path(tmp) / "mod.py").write_text(
                "def a():\n    return b()\n\ndef b():\n    return 1\n"
            )

            for _ in range(5):
                r = runner.invoke(cli, ["index", "--project-root", tmp])
                assert r.exit_code == 0, f"Re-index failed: {r.output[:200]}"
                assert "Indexed 1 files" in r.output
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestUnicodePaths:
    """Chinese / emoji filenames should work."""

    def test_unicode_filename(self):
        tmp = tempfile.mkdtemp()
        try:
            runner = CliRunner()
            r_init = runner.invoke(cli, ["init", "--project-root", tmp])
            assert r_init.exit_code == 0

            (Path(tmp) / "测试文件.py").write_text(
                "def 你好():\n    return 'hello'\n"
            )
            (Path(tmp) / "🚀_launch.py").write_text("def launch():\n    pass\n")

            r_idx = runner.invoke(cli, ["index", "--project-root", tmp])
            assert r_idx.exit_code == 0
            assert "Indexed 2 files" in r_idx.output
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
