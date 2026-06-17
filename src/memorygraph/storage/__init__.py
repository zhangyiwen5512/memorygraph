"""Storage layer for the code knowledge graph."""
from memorygraph.storage.backend import (
    create_storage_manager,
    detect_backend,
    get_connection_string,
)
from memorygraph.storage.connection import get_connection, get_db_path
from memorygraph.storage.manager import StorageManager  # noqa: F401 — re-export

__all__ = [
    "StorageManager",
    "create_storage_manager",
    "detect_backend",
    "get_connection",
    "get_connection_string",
    "get_db_path",
]
