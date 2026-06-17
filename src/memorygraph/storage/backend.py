"""Storage backend detection — SQLite (default) and PostgreSQL support.

Switch via DATABASE_URL environment variable:
  - unset/empty → SQLite (default, .memorygraph/memorygraph.db)
  - postgresql://user:pass@host/db → PostgreSQL
"""
from __future__ import annotations

import os


def detect_backend(project_root: str = ".") -> str:
    """Detect which storage backend to use based on DATABASE_URL.

    Returns:
        'sqlite' or 'postgresql'
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
        return "postgresql"
    return "sqlite"


def get_connection_string(project_root: str = ".") -> str:
    """Get the database connection string.

    Returns:
        SQLite file path or PostgreSQL connection string
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        return db_url

    from pathlib import Path
    db_path = Path(project_root) / ".memorygraph" / "memorygraph.db"
    return str(db_path)


def create_storage_manager(project_root: str = "."):
    """Create the appropriate storage manager based on DATABASE_URL.

    Returns:
        StorageManager (SQLite) or PostgreSQLStorageManager (PostgreSQL)
    """
    backend = detect_backend(project_root)
    if backend == "postgresql":
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager
        return PostgreSQLStorageManager(project_root)
    from memorygraph.storage.manager import StorageManager
    return StorageManager(project_root)


def create_semantic_store(project_root: str = "."):
    """Create a SemanticStore with the appropriate backend.

    When DATABASE_URL is set, injects a PgSemanticRepository so semantic
    data is stored in PostgreSQL. Otherwise falls back to JSON files.

    Returns:
        SemanticStore
    """
    from memorygraph.semantic.store import SemanticStore

    if detect_backend(project_root) == "postgresql":
        from memorygraph.storage.pg_repository import (
            PostgreSQLStorageManager,
        )

        # Create a temporary PG manager just for the pool + schema.
        # We don't need to initialize (DDL) — that's done by the main
        # storage manager. We just need the connection pool.
        pg_mgr = PostgreSQLStorageManager(project_root)
        pg_mgr.connect()
        repo = _create_pg_semantic_repo(pg_mgr)
        return SemanticStore(project_root, repo=repo)

    return SemanticStore(project_root)


def _create_pg_semantic_repo(pg_mgr):
    """Create a PgSemanticRepository from a PostgreSQLStorageManager.

    Args:
        pg_mgr: An initialized PostgreSQLStorageManager with an active pool.

    Returns:
        PgSemanticRepository
    """
    from memorygraph.storage.pg_repository import _project_schema
    from memorygraph.storage.semantic_repo import PgSemanticRepository

    schema = _project_schema(pg_mgr._project_root)
    return PgSemanticRepository(pool=pg_mgr._pool, schema=schema)
