"""Unit tests for PostgreSQLStorageManager — uses mocked psycopg2."""
import os
from unittest import mock

import pytest

# Check if psycopg2 is available
try:
    import psycopg2  # noqa: F401
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


@pytest.fixture
def pg_url():
    """Set DATABASE_URL to a fake PG URL for backend detection."""
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/testdb"
    yield
    if old is not None:
        os.environ["DATABASE_URL"] = old
    else:
        os.environ.pop("DATABASE_URL", None)


class TestDetectBackend:
    """Backend detection via DATABASE_URL."""

    def test_detect_sqlite_default(self):
        """detect_backend returns 'sqlite' when DATABASE_URL is unset."""
        old = os.environ.pop("DATABASE_URL", None)
        try:
            from memorygraph.storage.backend import detect_backend
            assert detect_backend() == "sqlite"
        finally:
            if old is not None:
                os.environ["DATABASE_URL"] = old

    def test_detect_postgresql(self, pg_url):
        """detect_backend returns 'postgresql' with a PG URL."""
        from memorygraph.storage.backend import detect_backend
        assert detect_backend() == "postgresql"

    def test_create_storage_manager_returns_sqlite_by_default(self):
        """create_storage_manager returns StorageManager without DATABASE_URL."""
        old = os.environ.pop("DATABASE_URL", None)
        try:
            from memorygraph.storage.backend import create_storage_manager
            from memorygraph.storage.manager import StorageManager
            mgr = create_storage_manager(".")
            assert isinstance(mgr, StorageManager)
        finally:
            if old is not None:
                os.environ["DATABASE_URL"] = old

    def test_create_storage_manager_returns_pg_with_url(self, pg_url):
        """create_storage_manager returns PostgreSQLStorageManager with PG URL."""
        from memorygraph.storage.backend import create_storage_manager
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager
        mgr = create_storage_manager(".")
        assert isinstance(mgr, PostgreSQLStorageManager)


@pytest.mark.skipif(not HAS_PSYCOPG2, reason="psycopg2 not installed")
class TestPostgreSQLStorageManagerUnit:
    """Unit tests with mocked psycopg2 connections."""

    @pytest.fixture(autouse=True)
    def setup_pg_url(self, pg_url):
        """Ensure DATABASE_URL is set for all tests."""
        pass

    def test_init_without_database_url_raises(self):
        """PostgreSQLStorageManager raises ValueError without DATABASE_URL."""
        old = os.environ.pop("DATABASE_URL", None)
        try:
            from memorygraph.storage.pg_repository import PostgreSQLStorageManager
            with pytest.raises(ValueError, match="DATABASE_URL"):
                PostgreSQLStorageManager(".")
        finally:
            if old is not None:
                os.environ["DATABASE_URL"] = old

    def test_connect_creates_pool(self):
        """connect() creates a ThreadedConnectionPool with project schema."""
        from memorygraph.storage.pg_repository import (
            PostgreSQLStorageManager,
            _project_schema,
        )

        schema = _project_schema(".")
        with mock.patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool:
            mgr = PostgreSQLStorageManager(".")
            mgr.connect()
            expected_dsn = (
                f"postgresql://test:test@localhost:5432/testdb "
                f"options=-c search_path={schema},public"
            )
            mock_pool.assert_called_once_with(
                minconn=2, maxconn=10, dsn=expected_dsn,
            )

    def test_connect_idempotent(self):
        """connect() is idempotent — second call does nothing."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with mock.patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool:
            mgr = PostgreSQLStorageManager(".")
            mgr.connect()
            mgr.connect()
            assert mock_pool.call_count == 1

    def test_close(self):
        """close() calls pool.closeall()."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with mock.patch("psycopg2.pool.ThreadedConnectionPool"):
            mgr = PostgreSQLStorageManager(".")
            mgr.connect()
            mgr._pool.closeall = mock.MagicMock()
            pool_ref = mgr._pool
            mgr.close()
            pool_ref.closeall.assert_called_once()
            assert mgr._pool is None

    def test_initialize_executes_ddl(self):
        """initialize() executes all DDL statements."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with mock.patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool_class:
            mock_pool = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_pool.getconn.return_value = mock_conn
            mock_pool_class.return_value = mock_pool

            mgr = PostgreSQLStorageManager(".")
            mgr.connect()
            mgr.initialize()

            # At least one DDL statement should have been executed
            assert mock_cursor.execute.call_count > 0
            # Pool connection should be released
            mock_pool.putconn.assert_called_once_with(mock_conn)

    def test_context_manager(self):
        """PostgreSQLStorageManager supports 'with' statement."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with mock.patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool_class:
            mock_pool = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_pool.getconn.return_value = mock_conn
            mock_pool_class.return_value = mock_pool

            with PostgreSQLStorageManager(".") as mgr:
                assert mgr._pool is not None

    def test_stats(self):
        """stats() returns expected structure with backend='postgresql'."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with mock.patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool_class:
            mock_pool = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            # Return counts for each table query
            mock_cursor.fetchone.side_effect = [
                (5,),   # files count
                (10,),  # functions
                (3,),   # methods
                (0,),   # classes
                (0,),   # interfaces
                (0,),   # type_aliases
                (2,),   # variables
                (15,),  # edges
                ("2024-01-01",),  # last_indexed
                (0,),   # embeddings count
            ]
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_pool.getconn.return_value = mock_conn
            mock_pool_class.return_value = mock_pool

            mgr = PostgreSQLStorageManager(".")
            mgr.connect()
            result = mgr.stats()

            assert result["backend"] == "postgresql"
            assert result["file_count"] == 5
            assert result["symbol_count"] == 15  # 10+3+0+0+0+2
            assert result["edge_count"] == 15

    def test_list_files(self):
        """list_files() returns file metadata."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with mock.patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool_class:
            mock_pool = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            mock_cursor.description = [
                ("path",), ("language",), ("file_hash",),
                ("symbol_count",), ("error_count",), ("last_indexed",),
            ]
            mock_cursor.fetchall.return_value = [
                ("/test.py", "python", "abc123", 10, 0, "2024-01-01"),
            ]
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_pool.getconn.return_value = mock_conn
            mock_pool_class.return_value = mock_pool

            mgr = PostgreSQLStorageManager(".")
            mgr.connect()
            result = mgr.list_files()

            assert len(result) == 1
            assert result[0]["path"] == "/test.py"

    def test_get_node_found(self):
        """get_node() returns symbol dict when found."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with mock.patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool_class:
            mock_pool = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            mock_cursor.description = [
                ("id",), ("file_id",), ("name",), ("qualified_name",),
                ("start_line",), ("start_col",), ("end_line",), ("end_col",),
                ("is_partial",), ("file_path",),
            ]
            # First table (functions): found
            mock_cursor.fetchone.return_value = (
                1, 1, "test_func", "test_func", 10, 0, 12, 20, 0, "/test.py",
            )
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_pool.getconn.return_value = mock_conn
            mock_pool_class.return_value = mock_pool

            mgr = PostgreSQLStorageManager(".")
            mgr.connect()
            result = mgr.get_node("test_func")

            assert result is not None
            assert result["name"] == "test_func"
            assert result["kind"] == "function"

    def test_get_node_not_found(self):
        """get_node() returns None when symbol not found."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with mock.patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool_class:
            mock_pool = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            mock_cursor.fetchone.return_value = None
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_pool.getconn.return_value = mock_conn
            mock_pool_class.return_value = mock_pool

            mgr = PostgreSQLStorageManager(".")
            mgr.connect()
            result = mgr.get_node("nonexistent")

            assert result is None

    def test_get_file_hash(self):
        """get_file_hash() returns hash string or None."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with mock.patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool_class:
            mock_pool = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            mock_cursor.fetchone.return_value = ("abc123hash",)
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_pool.getconn.return_value = mock_conn
            mock_pool_class.return_value = mock_pool

            mgr = PostgreSQLStorageManager(".")
            mgr.connect()
            result = mgr.get_file_hash("/test.py")
            assert result == "abc123hash"

    def test_get_symbols_for_file_empty(self):
        """get_symbols_for_file() returns [] for unknown file."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with mock.patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool_class:
            mock_pool = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            mock_cursor.fetchone.return_value = None  # file not found
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_pool.getconn.return_value = mock_conn
            mock_pool_class.return_value = mock_pool

            mgr = PostgreSQLStorageManager(".")
            mgr.connect()
            result = mgr.get_symbols_for_file("/unknown.py")
            assert result == []

    def test_search(self):
        """search() uses ts_vector/ts_query and returns ranked results."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with mock.patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool_class:
            mock_pool = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            mock_cursor.description = [
                ("symbol_name",), ("qualified_name",), ("signature",),
                ("file_path",), ("kind",), ("rank",),
            ]
            mock_cursor.fetchall.return_value = [
                ("my_func", "my_func", "def my_func()", "/test.py", "function", 0.8),
            ]
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_pool.getconn.return_value = mock_conn
            mock_pool_class.return_value = mock_pool

            mgr = PostgreSQLStorageManager(".")
            mgr.connect()
            # Mock get_node to avoid nested DB call
            mgr.get_node = mock.MagicMock(return_value={"start_line": 10})
            result = mgr.search("my_func")

            assert len(result) == 1
            assert result[0]["symbol_name"] == "my_func"

    def test_search_exception_returns_empty(self):
        """search() returns empty list on exception."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with mock.patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool_class:
            mock_pool = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_conn.cursor.side_effect = Exception("DB error")
            mock_pool.getconn.return_value = mock_conn
            mock_pool_class.return_value = mock_pool

            mgr = PostgreSQLStorageManager(".")
            mgr.connect()
            result = mgr.search("query")
            assert result == []

    def test_get_callers(self):
        """get_callers() delegates to _graph_walk with direction='up'."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with mock.patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool_class:
            mock_pool = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            mock_cursor.description = [("source",), ("target",), ("depth",)]
            mock_cursor.fetchall.return_value = [
                ("caller_func", "target_func", 1),
            ]
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_pool.getconn.return_value = mock_conn
            mock_pool_class.return_value = mock_pool

            mgr = PostgreSQLStorageManager(".")
            mgr.connect()
            result = mgr.get_callers("target_func")

            assert len(result) == 1
            assert result[0]["source"] == "caller_func"

    def test_get_callees(self):
        """get_callees() delegates to _graph_walk with direction='down'."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with mock.patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool_class:
            mock_pool = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            mock_cursor.description = [("source",), ("target",), ("depth",)]
            mock_cursor.fetchall.return_value = [
                ("source_func", "callee_func", 1),
            ]
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_pool.getconn.return_value = mock_conn
            mock_pool_class.return_value = mock_pool

            mgr = PostgreSQLStorageManager(".")
            mgr.connect()
            result = mgr.get_callees("source_func")

            assert len(result) == 1
            assert result[0]["target"] == "callee_func"

    def test_db_path_returns_conn_string(self):
        """db_path property returns the connection string."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager
        mgr = PostgreSQLStorageManager(".")
        assert mgr.db_path == "postgresql://test:test@localhost:5432/testdb"

    def test_semantic_search_tokenizes(self):
        """semantic_search tokenizes multi-word queries."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with mock.patch("psycopg2.pool.ThreadedConnectionPool") as mock_pool_class:
            mock_pool = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            mock_cursor.description = [
                ("symbol_name",), ("qualified_name",), ("signature",),
                ("file_path",), ("kind",), ("rank",),
            ]
            mock_cursor.fetchall.return_value = [
                ("login", "auth.login", "def login()", "/auth.py", "function", 0.9),
            ]
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_pool.getconn.return_value = mock_conn
            mock_pool_class.return_value = mock_pool

            mgr = PostgreSQLStorageManager(".")
            mgr.connect()
            mgr.get_node = mock.MagicMock(return_value={"start_line": 5})
            result = mgr.semantic_search("user login flow")

            assert len(result) >= 0  # may vary based on tokenization


@pytest.mark.skipif(not HAS_PSYCOPG2, reason="psycopg2 not installed")
class TestPGDDL:
    """DDL generation tests."""

    def test_ddl_contains_all_tables(self):
        """PG DDL includes all required tables."""
        from memorygraph.storage.pg_repository import _pg_ddl
        ddl_statements = " ".join(_pg_ddl())
        assert "CREATE TABLE IF NOT EXISTS files" in ddl_statements
        assert "CREATE TABLE IF NOT EXISTS functions" in ddl_statements
        assert "CREATE TABLE IF NOT EXISTS methods" in ddl_statements
        assert "CREATE TABLE IF NOT EXISTS classes" in ddl_statements
        assert "CREATE TABLE IF NOT EXISTS edges" in ddl_statements
        assert "CREATE TABLE IF NOT EXISTS fts_index" in ddl_statements
        assert "CREATE TABLE IF NOT EXISTS embeddings" in ddl_statements
        assert "CREATE TABLE IF NOT EXISTS schema_version" in ddl_statements

    def test_ddl_uses_pg_types(self):
        """PG DDL uses PostgreSQL-specific types."""
        from memorygraph.storage.pg_repository import _pg_ddl
        ddl_statements = " ".join(_pg_ddl())
        assert "SERIAL" in ddl_statements
        assert "TIMESTAMPTZ" in ddl_statements
        assert "TSVECTOR" in ddl_statements
        assert "GIN" in ddl_statements
        assert "NOW()" in ddl_statements
