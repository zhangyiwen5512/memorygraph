"""Database connection management."""
import sqlite3
from pathlib import Path


def get_db_path(project_root: str = ".") -> str:
    """返回 .memorygraph/memorygraph.db 的绝对路径。"""
    return str(Path(project_root).resolve() / ".memorygraph" / "memorygraph.db")


def get_connection(db_path: str) -> sqlite3.Connection:
    """创建并配置 SQLite 连接。

    - 自动创建 .memorygraph/ 目录
    - WAL 模式（并发读）
    - foreign_keys=ON（CASCADE 支持）
    - row_factory=Row（字典式访问）
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-131072")  # 128 MB (up from 64 MB)
    conn.execute("PRAGMA wal_autocheckpoint=10000")  # Less frequent WAL checkpoints
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn
