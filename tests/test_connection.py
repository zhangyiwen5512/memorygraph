"""Tests for connection module."""
import os
import tempfile
import threading

from memorygraph.storage.connection import get_connection, get_db_path


def test_get_db_path_default():
    path = get_db_path(".")
    assert path.endswith(".memorygraph/memorygraph.db")


def test_get_db_path_custom_root():
    path = get_db_path("/tmp/myproject")
    assert path == "/tmp/myproject/.memorygraph/memorygraph.db"


def test_get_connection_creates_directory():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, ".memorygraph", "test.db")
    try:
        conn = get_connection(db_path)
        assert os.path.exists(db_path)
        conn.close()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_get_connection_wal_mode():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, ".memorygraph", "test.db")
    try:
        conn = get_connection(db_path)
        cur = conn.execute("PRAGMA journal_mode")
        mode = cur.fetchone()[0]
        assert mode.lower() == "wal"
        conn.close()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_get_connection_foreign_keys_on():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, ".memorygraph", "test.db")
    try:
        conn = get_connection(db_path)
        cur = conn.execute("PRAGMA foreign_keys")
        val = cur.fetchone()[0]
        assert val == 1
        conn.close()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_get_connection_row_factory():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, ".memorygraph", "test.db")
    try:
        conn = get_connection(db_path)
        conn.execute("CREATE TABLE t (x)")
        conn.execute("INSERT INTO t VALUES (1)")
        row = conn.execute("SELECT * FROM t").fetchone()
        assert row["x"] == 1
        conn.close()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_get_connection_cross_thread():
    """SQLite connections should be usable from threads other than the creating thread."""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, ".memorygraph", "test.db")
    try:
        conn = get_connection(db_path)
        conn.execute("CREATE TABLE t (x)")
        conn.execute("INSERT INTO t VALUES (42)")

        errors: list[Exception] = []
        def _query():
            try:
                row = conn.execute("SELECT x FROM t").fetchone()
                if row["x"] != 42:
                    errors.append(ValueError(f"Unexpected value: {row['x']}"))
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=_query)
        t.start()
        t.join()
        assert not errors, f"Cross-thread query failed: {errors}"
        conn.close()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
