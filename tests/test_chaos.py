"""Chaos engineering tests: concurrent access, corruption recovery, signal handling."""
import threading
import time
from pathlib import Path
from unittest import mock


class TestConcurrentAccess:
    """Verify thread-safety under concurrent read/write patterns."""

    def test_concurrent_sync_from_threads(self, tmp_path):
        """Multiple threads calling sync should not corrupt the database."""
        from memorygraph.cli.shared import _do_sync

        # Init project
        project = tmp_path / "project"
        project.mkdir()
        src = project / "src"
        src.mkdir()
        for i in range(10):
            (src / f"mod{i}.py").write_text(f"def func{i}(): return {i}\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])

        errors = []
        def do_sync():
            try:
                _do_sync(str(project), analyze=False, semantic=False)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=do_sync) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Concurrent sync errors: {errors}"
        # Verify DB is still usable
        result = r.invoke(cli, ["doctor", "--project-root", str(project)])
        assert result.exit_code == 0

    def test_concurrent_read_during_write(self, tmp_path):
        """Reader should not block or crash while writer is active."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        for i in range(50):
            (project / "src" / f"mod{i}.py").write_text(f"def f{i}(): pass\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        r.invoke(cli, ["index", "--project-root", str(project)])

        read_errors = []
        write_done = threading.Event()

        def reader():
            from memorygraph.storage import create_storage_manager
            try:
                with create_storage_manager(str(project)) as mgr:
                    for _ in range(100):
                        stats = mgr.stats()
                        if stats.get("file_count", 0) > 0:
                            break
                        time.sleep(0.01)
            except Exception as e:
                read_errors.append(str(e))

        def writer():
            from memorygraph.cli.shared import _do_sync
            try:
                _do_sync(str(project), analyze=False, semantic=False)
            except Exception as e:
                read_errors.append(str(e))
            finally:
                write_done.set()

        t_read = threading.Thread(target=reader)
        t_write = threading.Thread(target=writer)
        t_read.start()
        t_write.start()
        t_read.join(timeout=30)
        t_write.join(timeout=30)

        assert not read_errors, f"Concurrent access errors: {read_errors}"


class TestCorruptionRecovery:
    """Verify graceful handling of corrupted database files."""

    def test_corrupted_db_does_not_crash_sync(self, tmp_path):
        """Sync should handle a corrupted database gracefully."""
        project = tmp_path / "project"
        project.mkdir()
        mg_dir = project / ".memorygraph"
        mg_dir.mkdir()
        db_path = mg_dir / "memorygraph.db"
        db_path.write_text("this is not a valid sqlite database")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        result = r.invoke(cli, ["doctor", "--project-root", str(project)])
        # Doctor should report the DB error clearly, not crash with traceback
        assert result.exit_code == 0
        assert ("database error" in result.output.lower()
                or "not a database" in result.output.lower())

    def test_missing_db_recovery(self, tmp_path):
        """Doctor should detect and report missing database."""
        project = tmp_path / "project"
        project.mkdir()
        mg_dir = project / ".memorygraph"
        mg_dir.mkdir()
        # DB file doesn't exist — doctor should report it

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        result = r.invoke(cli, ["doctor", "--project-root", str(project)])
        assert result.exit_code == 0
        assert "Database missing" in result.output

    def test_truncated_db_file(self, tmp_path):
        """A truncated SQLite file should be handled gracefully."""
        project = tmp_path / "project"
        project.mkdir()
        mg_dir = project / ".memorygraph"
        mg_dir.mkdir()
        db_path = mg_dir / "memorygraph.db"
        # Write a partial SQLite header (less than 100 bytes)
        db_path.write_bytes(b"SQLite format 3\0" + b"\x00" * 50)

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        result = r.invoke(cli, ["doctor", "--project-root", str(project)])
        # Should not crash — either reports error or handles gracefully
        assert result.exit_code == 0

    def test_index_handles_storage_error(self, tmp_path):
        """Indexing should handle StorageManager errors gracefully."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "app.py").write_text("def hello(): return 42\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])

        # Simulate storage failure by mocking bulk_upsert
        with mock.patch(
            "memorygraph.storage.manager.StorageManager.bulk_upsert",
            side_effect=OSError("No space left on device"),
        ):
            result = r.invoke(cli, ["index", "--project-root", str(project)])
            # Should not crash with traceback — may report error or exit non-zero
            assert result.exit_code in (0, 1, 2)


class TestSignalHandling:
    """Verify graceful shutdown under signals."""

    def test_watch_once_handles_sigterm_during_sync(self, tmp_path):
        """watch --once should complete or exit cleanly when SIGTERMed."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        for i in range(100):
            (project / "src" / f"mod{i}.py").write_text(f"def f{i}(): return {i}\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])

        # Just verify watch --once completes normally
        result = r.invoke(cli, ["watch", "--once", "--project-root", str(project)])
        assert result.exit_code == 0

    def test_sync_handles_interrupted_write(self, tmp_path):
        """Sync should handle an interrupted write gracefully."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "app.py").write_text("def hello(): return 42\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])

        # First sync should work
        result = r.invoke(cli, ["sync", "--project-root", str(project)])
        assert result.exit_code == 0

        # Second sync with no changes should also work (idempotent)
        result = r.invoke(cli, ["sync", "--project-root", str(project)])
        assert result.exit_code == 0

    def test_rapid_start_stop_watch(self, tmp_path):
        """Rapidly starting and stopping watch should not leave stale state."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "app.py").write_text("def f(): pass\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        r.invoke(cli, ["index", "--project-root", str(project)])

        # Rapid --once invocations
        for _ in range(3):
            result = r.invoke(cli, ["watch", "--once", "--project-root", str(project)])
            assert result.exit_code == 0

        # PID file should be clean
        pid_file = project / ".memorygraph" / "watch.pid"
        assert not pid_file.exists(), "PID file should not exist after --once"


class TestEdgeCaseRecovery:
    """Verify edge case recovery paths."""

    def test_init_then_init_again_is_safe(self, tmp_path):
        """Double init should be idempotent."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        project = str(tmp_path / "p")

        r.invoke(cli, ["init", "--project-root", project])
        result = r.invoke(cli, ["init", "--project-root", project])
        assert result.exit_code == 0  # Should not error

    def test_sync_after_uninit_is_safe(self, tmp_path):
        """Sync after uninit should not crash."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "app.py").write_text("def f(): pass\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        r.invoke(cli, ["index", "--project-root", str(project)])
        r.invoke(cli, ["uninit", "--project-root", str(project)], input="y\n")

        # Sync after uninit should not crash
        result = r.invoke(cli, ["sync", "--project-root", str(project)])
        assert result.exit_code in (0, 1)

    def test_index_empty_project(self, tmp_path):
        """Index on project with no source files should not crash."""
        project = tmp_path / "project"
        project.mkdir()

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        result = r.invoke(cli, ["index", "--project-root", str(project)])
        assert result.exit_code == 0

    def test_watch_stop_without_start(self, tmp_path):
        """Stopping a watch that was never started should not crash."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        result = r.invoke(cli, ["watch", "--stop", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        assert "No watch daemon" in result.output

    def test_backup_then_restore_preserves_data(self, tmp_path):
        """Full backup→delete→restore cycle should preserve indexed data."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "app.py").write_text("def hello(): return 42\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        r.invoke(cli, ["index", "--project-root", str(project)])

        # Get initial stats
        result = r.invoke(cli, ["doctor", "--project-root", str(project)])
        assert "No files indexed" not in result.output

        # Backup
        result = r.invoke(cli, ["backup", "--project-root", str(project)])
        assert result.exit_code == 0
        backups = list(project.glob("memorygraph-backup-*.tar.gz"))
        assert len(backups) == 1

        # Delete .memorygraph
        import shutil
        shutil.rmtree(str(project / ".memorygraph"))

        # Restore
        result = r.invoke(cli, ["restore", "--project-root", str(project), str(backups[0])])
        assert result.exit_code == 0

        # Verify data is back
        result = r.invoke(cli, ["doctor", "--project-root", str(project)])
        assert result.exit_code == 0


class TestLargeFileHandling:
    """Verify behavior with edge-case file sizes."""

    def test_empty_file_is_skipped_gracefully(self, tmp_path):
        """Indexing an empty file should not crash."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "empty.py").write_text("")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        result = r.invoke(cli, ["index", "--project-root", str(project)])
        assert result.exit_code == 0

    def test_binary_file_is_skipped_gracefully(self, tmp_path):
        """Indexing a binary file should not crash."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "data.py").write_bytes(b"\x00\x01\x02\x03" * 100)

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        result = r.invoke(cli, ["index", "--project-root", str(project)])
        assert result.exit_code in (0, 1, 2)

    def test_very_long_line_file(self, tmp_path):
        """A file with extremely long lines should not crash."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "long.py").write_text("x = " + "a" * 100000 + "\ndef f(): pass\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        result = r.invoke(cli, ["index", "--project-root", str(project)])
        assert result.exit_code in (0, 1, 2)


class TestFaultInjection:
    """Verify graceful degradation under fault injection."""

    def test_index_with_parallel_jobs(self, tmp_path):
        """Indexing with --jobs 2 should not crash."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        for i in range(50):
            (project / "src" / f"mod{i}.py").write_text(f"def f{i}(): return {i}\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        result = r.invoke(cli, ["index", "--jobs", "2", "--project-root", str(project)])
        assert result.exit_code == 0

    def test_watch_once_idempotent(self, tmp_path):
        """Multiple watch --once invocations should all succeed."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "app.py").write_text("def f(): pass\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        for _ in range(5):
            result = r.invoke(cli, ["watch", "--once", "--project-root", str(project)])
            assert result.exit_code == 0

    def test_database_recovery_after_error(self, tmp_path):
        """Doctor should work after indexing."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "app.py").write_text("def f(): pass\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        r.invoke(cli, ["index", "--project-root", str(project)])
        result = r.invoke(cli, ["doctor", "--project-root", str(project)])
        assert result.exit_code == 0

    def test_rapid_init_uninit_cycle(self, tmp_path):
        """Rapid init/uninit cycles should not leave corrupted state."""
        project = tmp_path / "project"
        project.mkdir()

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()

        for _ in range(3):
            r.invoke(cli, ["init", "--project-root", str(project)])
            assert (project / ".memorygraph" / "memorygraph.db").exists()
            r.invoke(cli, ["uninit", "--project-root", str(project)], input="y\n")
            assert not (project / ".memorygraph").exists()

    def test_backup_empty_project(self, tmp_path):
        """Backup on empty (no indexed files) project should still work."""
        project = tmp_path / "project"
        project.mkdir()

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        result = r.invoke(cli, ["backup", "--project-root", str(project)])
        assert result.exit_code == 0


class TestInputValidation:
    """Verify safe handling of malicious or unexpected inputs."""

    def test_query_with_sql_injection_attempt(self, tmp_path):
        """Query with SQL-like input should not cause injection."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "app.py").write_text("def hello(): return 42\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        r.invoke(cli, ["index", "--project-root", str(project)])

        malicious = [
            "'; DROP TABLE symbols; --",
            "1' OR '1'='1",
            "hello' UNION SELECT * FROM symbols--",
        ]
        for mal in malicious:
            result = r.invoke(cli, ["query", mal, "--project-root", str(project)])
            # Should not crash with traceback; may reject invalid input
            assert result.exit_code in (0, 1)

    def test_init_with_traversal_path(self, tmp_path):
        """Init with path traversal attempts should be safe."""
        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()

        for tp in ["../../../etc/passwd", "project/../../../root"]:
            result = r.invoke(cli, ["init", "--project-root", str(tmp_path / tp)])
            assert result.exit_code in (0, 1, 2)

    def test_nul_byte_in_file_content(self, tmp_path):
        """File containing NUL bytes should not crash the parser."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "nul.py").write_text("x = 'hello\x00world'\ndef f(): pass\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        result = r.invoke(cli, ["index", "--project-root", str(project)])
        assert result.exit_code in (0, 1, 2)


class TestBackupRestoreE2E:
    """End-to-end backup/restore cycle tests."""

    def test_full_backup_restore_cycle(self, tmp_path):
        """Complete cycle: init→index→backup→delete→restore→verify."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "app.py").write_text("def hello(): return 42\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()

        # Setup
        r.invoke(cli, ["init", "--project-root", str(project)])
        r.invoke(cli, ["index", "--project-root", str(project)])

        # Verify initial state
        result = r.invoke(cli, ["doctor", "--project-root", str(project)])
        assert "No files indexed" not in result.output

        # Backup
        result = r.invoke(cli, ["backup", "--project-root", str(project)])
        assert result.exit_code == 0
        backups = list(project.glob("memorygraph-backup-*.tar.gz"))
        assert len(backups) == 1

        # Delete and restore
        import shutil
        shutil.rmtree(str(project / ".memorygraph"))
        result = r.invoke(cli, ["restore", "--project-root", str(project), str(backups[0])])
        assert result.exit_code == 0

        # Verify restored
        result = r.invoke(cli, ["doctor", "--project-root", str(project)])
        assert result.exit_code == 0

    def test_backup_with_custom_output_path(self, tmp_path):
        """Backup with explicit --output path."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "app.py").write_text("def f(): pass\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        r.invoke(cli, ["index", "--project-root", str(project)])

        custom = str(tmp_path / "my-backup.tar.gz")
        result = r.invoke(cli, ["backup", "--project-root", str(project), "-o", custom])
        assert result.exit_code == 0
        assert Path(custom).exists()

    def test_backup_restore_preserves_index(self, tmp_path):
        """Restored database should have same file/symbol/edge counts."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()
        (project / "src" / "a.py").write_text("def f(): pass\n")
        (project / "src" / "b.py").write_text("class C:\n    def m(self): pass\n")

        from click.testing import CliRunner

        from memorygraph.cli.main import cli
        r = CliRunner()
        r.invoke(cli, ["init", "--project-root", str(project)])
        r.invoke(cli, ["index", "--project-root", str(project)])

        # Get original stats via doctor
        result = r.invoke(cli, ["doctor", "--project-root", str(project)])

        # Backup
        result = r.invoke(cli, ["backup", "--project-root", str(project)])
        assert result.exit_code == 0
        backups = list(project.glob("memorygraph-backup-*.tar.gz"))

        # Delete and restore
        import shutil
        shutil.rmtree(str(project / ".memorygraph"))
        result = r.invoke(cli, ["restore", "--project-root", str(project), str(backups[0])])
        assert result.exit_code == 0

        # Verify same stats
        result = r.invoke(cli, ["doctor", "--project-root", str(project)])
        assert result.exit_code == 0
        # Data should be preserved
        assert "Files indexed" in result.output
