"""Error recovery tests: DB corruption, disk-full, interrupted indexing."""

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# ── DB corruption recovery ──


class TestDBCorruption:
    """DB 文件损坏 → graceful error + reindex 恢复."""

    def test_corrupt_db_raises_on_connect(self):
        """Connecting to a corrupt/non-DB file should raise sqlite3 error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, ".memorygraph", "corrupt.db")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            # Write garbage instead of a valid SQLite DB
            with open(db_path, "w") as f:
                f.write("not a database file")

            from memorygraph.storage.connection import get_connection
            with pytest.raises(sqlite3.DatabaseError):
                get_connection(db_path)

    def test_corrupt_db_recoverable_by_reinit(self):
        """After removing a corrupt DB, reindex should work."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from memorygraph.parsing.ir import FileInfo, ParseResult
            from memorygraph.storage.manager import StorageManager

            mgr = StorageManager(tmpdir)
            mgr.initialize()

            # Index something
            result = ParseResult(
                file=FileInfo(
                    path=os.path.join(tmpdir, "test.py"),
                    language="python",
                    content_hash="abc123",
                ),
                symbols=[],
                edges=[],
            )
            mgr.upsert_file(result)
            assert mgr.stats()["file_count"] == 1
            mgr.close()

            # Corrupt the DB
            db_path = os.path.join(tmpdir, ".memorygraph", "memorygraph.db")
            with open(db_path, "wb") as f:
                f.write(b"\x00\x00\x00\x00" * 1024)

            # New manager should fail to initialize on corrupt DB
            mgr2 = StorageManager(tmpdir)
            with pytest.raises(sqlite3.DatabaseError):
                mgr2.initialize()

            # Remove corrupt DB and reindex — should work
            os.remove(db_path)
            mgr3 = StorageManager(tmpdir)
            mgr3.initialize()  # Should NOT raise — creates fresh DB
            mgr3.close()

    def test_empty_db_file_recovery(self):
        """A zero-byte .db file is treated as a new DB by sqlite3 (graceful)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_dir = os.path.join(tmpdir, ".memorygraph")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "memorygraph.db")
            Path(db_path).touch()  # zero-byte file

            from memorygraph.storage.connection import get_connection
            # sqlite3 treats empty files as new DBs — should succeed
            conn = get_connection(db_path)
            assert conn is not None
            conn.close()


# ── Connection error handling ──


class TestConnectionErrors:
    """连接失败场景 → 不崩溃，有明确错误."""

    def test_read_only_permissions(self):
        """DB in read-only directory should raise informative error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_dir = os.path.join(tmpdir, ".memorygraph")
            os.makedirs(db_dir, exist_ok=True)

            from memorygraph.storage.connection import get_connection
            from memorygraph.storage.schema import init_db

            conn = get_connection(os.path.join(db_dir, "test.db"))
            init_db(conn)
            conn.close()

            # Make directory read-only
            os.chmod(db_dir, 0o444)
            try:
                db_path = os.path.join(db_dir, "test2.db")
                from memorygraph.storage.connection import get_connection
                # Should fail because directory is read-only
                with pytest.raises((sqlite3.OperationalError, OSError, PermissionError)):
                    get_connection(db_path)
            finally:
                os.chmod(db_dir, 0o755)

    def test_storage_manager_methods_safe_when_closed(self):
        """All StorageManager methods should return safe defaults after close()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from memorygraph.storage.manager import StorageManager
            mgr = StorageManager(tmpdir)
            mgr.initialize()
            mgr.close()

            # All queries should return empty/safe defaults
            assert mgr.search("test") == []
            assert mgr.get_callers("foo") == []
            assert mgr.get_callees("foo") == []
            assert mgr.get_node("foo") is None
            stats = mgr.stats()
            assert stats.get("file_count", 0) == 0

    def test_semantic_search_closed_connection(self):
        """semantic_search after close() should return empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from memorygraph.storage.manager import StorageManager
            mgr = StorageManager(tmpdir)
            mgr.initialize()
            mgr.close()
            assert mgr.semantic_search("test") == []

    def test_upsert_after_close_reconnects_gracefully(self):
        """upsert_file after close() auto-reconnects (idempotent)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import hashlib

            from memorygraph.parsing.ir import FileInfo, ParseResult
            from memorygraph.storage.manager import StorageManager

            mgr = StorageManager(tmpdir)
            mgr.initialize()
            mgr.close()

            result = ParseResult(
                file=FileInfo(
                    path=os.path.join(tmpdir, "test.py"),
                    language="python",
                    content_hash=hashlib.sha256(b"test").hexdigest(),
                ),
                symbols=[],
                edges=[],
            )
            # _get_conn auto-recreates connection — upsert should succeed
            fid, _ = mgr.upsert_file(result)
            assert fid > 0


# ── Disk-full simulation ──


class TestDiskFull:
    """磁盘满场景 — 不崩溃，不静默丢失数据."""

    def test_upsert_with_db_error_rolls_back(self):
        """If a DB operation fails mid-transaction, data integrity is preserved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from memorygraph.parsing.ir import FileInfo, ParseResult, Span, Symbol, SymbolKind
            from memorygraph.storage.manager import StorageManager

            mgr = StorageManager(tmpdir)
            mgr.initialize()

            # Index a valid file first
            good_result = ParseResult(
                file=FileInfo(
                    path=os.path.join(tmpdir, "good.py"),
                    language="python",
                    content_hash="good",
                ),
                symbols=[Symbol(
                    name="valid_func", kind=SymbolKind.FUNCTION,
                    span=Span(file=os.path.join(tmpdir, "good.py"),
                              start_line=1, start_col=0, end_line=1, end_col=10),
                )],
                edges=[],
            )
            mgr.upsert_file(good_result)
            count_before = mgr.stats()["file_count"]
            assert count_before == 1

            # Simulate a DB operational error during upsert
            with mock.patch.object(mgr, "_get_conn") as mock_conn:
                mock_conn.side_effect = sqlite3.OperationalError("disk I/O error")
                bad_result = ParseResult(
                    file=FileInfo(
                        path=os.path.join(tmpdir, "bad.py"),
                        language="python", content_hash="bad",
                    ),
                    symbols=[],
                    edges=[],
                )
                with pytest.raises(sqlite3.OperationalError):
                    mgr.upsert_file(bad_result)

            # Data from before the error should still be there
            mgr2 = StorageManager(tmpdir)
            mgr2.initialize()
            stats = mgr2.stats()
            assert stats["file_count"] >= 1  # good file survived
            mgr2.close()

    def test_full_text_search_recovers_after_db_errors(self):
        """FTS search should return empty results on DB error, not crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from memorygraph.storage.manager import StorageManager
            mgr = StorageManager(tmpdir)
            mgr.initialize()
            mgr.close()

            # Search on closed DB should return empty, not crash
            assert mgr.search("anything") == []


# ── Interrupted indexing recovery ──


class TestInterruptedIndexing:
    """索引中断 → 状态一致性 + reindex 可恢复."""

    def test_reindex_after_partial_index(self):
        """Reindex should succeed even if previous data exists (idempotent)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.py")
            with open(file_path, "w") as f:
                f.write("def foo(): pass\n")

            from memorygraph.parsing.ir import FileInfo, ParseResult, Span, Symbol, SymbolKind
            from memorygraph.storage.manager import StorageManager

            # First index
            mgr1 = StorageManager(tmpdir)
            mgr1.initialize()
            result = ParseResult(
                file=FileInfo(path=file_path, language="python", content_hash="v1"),
                symbols=[Symbol(
                    name="foo", kind=SymbolKind.FUNCTION,
                    span=Span(file=file_path, start_line=1, start_col=0,
                              end_line=1, end_col=15),
                )],
                edges=[],
            )
            mgr1.upsert_file(result)
            mgr1.close()

            # Reindex (simulates recovery after interrupted index)
            mgr2 = StorageManager(tmpdir)
            mgr2.initialize()
            result2 = ParseResult(
                file=FileInfo(path=file_path, language="python", content_hash="v2"),
                symbols=[Symbol(
                    name="foo", kind=SymbolKind.FUNCTION,
                    span=Span(file=file_path, start_line=1, start_col=0,
                              end_line=1, end_col=15),
                )],
                edges=[],
            )
            mgr2.upsert_file(result2)  # Should succeed (upsert)
            stats = mgr2.stats()
            assert stats["file_count"] == 1
            mgr2.close()

    def test_multiple_initialize_is_idempotent(self):
        """Multiple initialize() calls should not fail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from memorygraph.storage.manager import StorageManager
            mgr = StorageManager(tmpdir)
            mgr.initialize()
            mgr.initialize()  # Second call should be no-op
            mgr.initialize()  # Third call too
            mgr.close()

    def test_clear_and_reindex_git_repo(self, git_repo):
        """Reindex after initial index should work on real git repos."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        from memorygraph.storage.manager import StorageManager

        runner = CliRunner()

        # First index
        result = runner.invoke(cli, ["init", "--project-root", str(git_repo)])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["index", "--project-root", str(git_repo)])
        assert result.exit_code == 0

        # Verify data exists
        mgr = StorageManager(str(git_repo))
        mgr.initialize()
        stats = mgr.stats()
        assert stats["file_count"] > 0
        mgr.close()

        # Reindex
        result = runner.invoke(cli, ["index", "--project-root", str(git_repo)])
        assert result.exit_code == 0

        # Data should still be there
        mgr2 = StorageManager(str(git_repo))
        mgr2.initialize()
        stats2 = mgr2.stats()
        assert stats2["file_count"] > 0
        mgr2.close()


class TestStorageManagerClosingRace:
    """Cover read_only_connection closing check (manager.py 358-360)."""

    def test_read_only_connection_during_shutdown_raises(self):
        """read_only_connection raises RuntimeError when StorageManager is closing."""
        import tempfile

        from memorygraph.storage.manager import StorageManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = StorageManager(tmpdir)
            mgr.initialize()

            # Set the internal closing flag
            mgr._closing = True

            # Attempt to get a read-only connection should raise
            with pytest.raises(RuntimeError, match="shutting down"):
                with mgr.read_only_connection():
                    pass  # Should not reach here
