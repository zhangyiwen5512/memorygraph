"""SQLite schema definitions and initialization."""
import sqlite3
from typing import FrozenSet

SYMBOL_KIND_TO_TABLE = {
    "function": "functions",
    "method": "methods",
    "class": "classes",
    "interface": "interfaces",
    "type": "type_aliases",
    "variable": "variables",
}

SYMBOL_TABLES = [
    "functions", "methods", "classes",
    "interfaces", "type_aliases", "variables",
]

CREATE_FILES = """
CREATE TABLE IF NOT EXISTS files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT NOT NULL UNIQUE,
    language        TEXT NOT NULL,
    file_hash       TEXT NOT NULL,
    last_indexed    TEXT NOT NULL DEFAULT (datetime('now')),
    symbol_count    INTEGER NOT NULL DEFAULT 0,
    edge_count      INTEGER NOT NULL DEFAULT 0,
    error_count     INTEGER NOT NULL DEFAULT 0
);
"""

CREATE_FUNCTIONS = """
CREATE TABLE IF NOT EXISTS functions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    qualified_name  TEXT NOT NULL,
    signature       TEXT,
    start_line      INTEGER NOT NULL,
    start_col       INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    end_col         INTEGER NOT NULL,
    is_partial      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_functions_name ON functions(name);
CREATE INDEX IF NOT EXISTS idx_functions_file ON functions(file_id);
"""

CREATE_METHODS = """
CREATE TABLE IF NOT EXISTS methods (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    qualified_name  TEXT NOT NULL,
    parent_class    TEXT NOT NULL,
    signature       TEXT,
    start_line      INTEGER NOT NULL,
    start_col       INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    end_col         INTEGER NOT NULL,
    is_partial      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_methods_name ON methods(name);
CREATE INDEX IF NOT EXISTS idx_methods_parent ON methods(parent_class);
"""

CREATE_CLASSES = """
CREATE TABLE IF NOT EXISTS classes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    qualified_name  TEXT NOT NULL,
    start_line      INTEGER NOT NULL,
    start_col       INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    end_col         INTEGER NOT NULL,
    is_partial      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_classes_name ON classes(name);
"""

CREATE_INTERFACES = """
CREATE TABLE IF NOT EXISTS interfaces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    qualified_name  TEXT NOT NULL,
    start_line      INTEGER NOT NULL,
    start_col       INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    end_col         INTEGER NOT NULL,
    is_partial      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_interfaces_name ON interfaces(name);
"""

CREATE_TYPE_ALIASES = """
CREATE TABLE IF NOT EXISTS type_aliases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    qualified_name  TEXT NOT NULL,
    start_line      INTEGER NOT NULL,
    start_col       INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    end_col         INTEGER NOT NULL,
    is_partial      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_type_aliases_name ON type_aliases(name);
"""

CREATE_VARIABLES = """
CREATE TABLE IF NOT EXISTS variables (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    qualified_name  TEXT NOT NULL,
    start_line      INTEGER NOT NULL,
    start_col       INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    end_col         INTEGER NOT NULL,
    is_partial      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_variables_name ON variables(name);
"""

CREATE_EDGES = """
CREATE TABLE IF NOT EXISTS edges (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source            TEXT NOT NULL,
    target            TEXT NOT NULL,
    kind              TEXT NOT NULL,
    source_file_id    INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    source_start_line INTEGER NOT NULL,
    source_start_col  INTEGER NOT NULL,
    source_end_line   INTEGER NOT NULL,
    source_end_col    INTEGER NOT NULL,
    target_file_id    INTEGER REFERENCES files(id) ON DELETE SET NULL,
    target_start_line INTEGER,
    target_start_col  INTEGER,
    target_end_line   INTEGER,
    target_end_col    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
CREATE INDEX IF NOT EXISTS idx_edges_source_file ON edges(source_file_id);
CREATE INDEX IF NOT EXISTS idx_edges_target_kind ON edges(target, kind);
CREATE INDEX IF NOT EXISTS idx_edges_source_kind ON edges(source, kind);
"""

CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS fts_index USING fts5(
    symbol_name,
    qualified_name,
    signature,
    file_path UNINDEXED,
    kind,
    tokenize='unicode61'
);
"""

CREATE_EMBEDDINGS = """
CREATE TABLE IF NOT EXISTS embeddings (
    qualified_name  TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    embedding       BLOB,
    model_version   TEXT DEFAULT 'all-MiniLM-L6-v2',
    PRIMARY KEY (qualified_name, file_path)
);
"""

ALL_DDL = [
    CREATE_FILES,
    CREATE_FUNCTIONS,
    CREATE_METHODS,
    CREATE_CLASSES,
    CREATE_INTERFACES,
    CREATE_TYPE_ALIASES,
    CREATE_VARIABLES,
    CREATE_EDGES,
    CREATE_FTS,
    CREATE_EMBEDDINGS,
]


# Frozen set for O(1) whitelist validation — all SQL table names must be
# members of this set before being interpolated into queries.
ALLOWED_TABLE_NAMES: FrozenSet[str] = frozenset(SYMBOL_TABLES)


def validate_table_name(table_name: str) -> str:
    """Return *table_name* unchanged if it is a whitelisted SQL table.

    Raises ``ValueError`` otherwise.  Use this before every f-string or
    format-string that interpolates a table name into a SQL statement so
    that static analysers (bandit B608) can see the whitelist check.
    """
    if table_name not in ALLOWED_TABLE_NAMES:
        raise ValueError(
            f"Table name {table_name!r} is not in the allowed set "
            f"{sorted(ALLOWED_TABLE_NAMES)}"
        )
    return table_name


CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now')),
    description TEXT NOT NULL DEFAULT ''
);
"""

ALL_DDL_WITH_VERSION = ALL_DDL + [CREATE_SCHEMA_VERSION]

# Ordered list of migrations: (version_number, description, ddl_statement)
MIGRATIONS: list[tuple[int, str, str]] = [
    # Example:
    # (2, "Add partial parse column", "ALTER TABLE functions ADD COLUMN is_partial INTEGER DEFAULT 0;"),
]


def init_db(conn: sqlite3.Connection) -> None:
    """初始化数据库 schema。幂等（全部使用 IF NOT EXISTS）。"""
    for ddl in ALL_DDL_WITH_VERSION:
        conn.executescript(ddl)
    conn.commit()
    _apply_migrations(conn)


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply any pending migrations in order."""
    # Ensure schema_version table exists
    conn.execute(CREATE_SCHEMA_VERSION)
    current = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_version"
    ).fetchone()[0]

    for version, description, ddl in sorted(MIGRATIONS):
        if version <= current:
            continue
        conn.executescript(ddl)
        conn.execute(
            "INSERT INTO schema_version (version, description) VALUES (?, ?)",
            (version, description),
        )
        conn.commit()

