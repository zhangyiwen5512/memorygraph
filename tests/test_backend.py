"""Tests for storage backend detection utilities."""
import os
from unittest.mock import patch

from memorygraph.storage.backend import (
    create_storage_manager,
    detect_backend,
    get_connection_string,
)


class TestDetectBackend:
    def test_defaults_to_sqlite(self):
        with patch.dict(os.environ, {}, clear=True):
            assert detect_backend() == "sqlite"

    def test_postgresql_url(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@localhost/db"}):
            assert detect_backend() == "postgresql"

    def test_postgres_url_alt_scheme(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgres://user@host/db"}):
            assert detect_backend() == "postgresql"

    def test_other_url_defaults_to_sqlite(self):
        with patch.dict(os.environ, {"DATABASE_URL": "mysql://localhost/db"}):
            assert detect_backend() == "sqlite"


class TestGetConnectionString:
    def test_from_env(self):
        url = "postgresql://user:pass@localhost/mydb"
        with patch.dict(os.environ, {"DATABASE_URL": url}):
            assert get_connection_string() == url

    def test_default_path(self):
        with patch.dict(os.environ, {}, clear=True):
            result = get_connection_string("/tmp/project")
            assert ".memorygraph" in result
            assert "memorygraph.db" in result


class TestCreateStorageManager:
    """Factory function coverage."""

    def test_returns_sqlite_by_default(self):
        """create_storage_manager returns StorageManager without DATABASE_URL."""
        with patch.dict(os.environ, {}, clear=True):
            from memorygraph.storage.manager import StorageManager
            mgr = create_storage_manager(".")
            assert isinstance(mgr, StorageManager)

    def test_returns_pg_with_postgresql_url(self):
        """create_storage_manager returns PostgreSQLStorageManager with PG URL."""
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@localhost/db"}):
            from memorygraph.storage.pg_repository import PostgreSQLStorageManager
            mgr = create_storage_manager(".")
            assert isinstance(mgr, PostgreSQLStorageManager)
