"""PostgreSQL storage backend.

Switch via DATABASE_URL environment variable:
  - unset/empty → SQLite (default, StorageManager)
  - postgresql://user:pass@host/db → PostgreSQL (PostgreSQLStorageManager)
"""
from __future__ import annotations

import hashlib
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from memorygraph.storage.cache import QueryCache  # pragma: no cover

from memorygraph.storage.helpers import qualified_name, symbol_to_row
from memorygraph.storage.schema import SYMBOL_KIND_TO_TABLE, validate_table_name

logger = logging.getLogger(__name__)


def _project_schema(project_root: str) -> str:
    """Derive a stable schema name from the project directory path.

    Each project gets its own PostgreSQL schema, so multiple projects
    can share a single PG database without table conflicts.
    """
    abs_path = str(Path(project_root).resolve())
    suffix = hashlib.sha256(abs_path.encode()).hexdigest()[:8]
    # Schema names must start with a letter or underscore
    return f"memorygraph_{suffix}"

# Reverse mapping: table name → kind string (e.g. "functions" → "function")
_TABLE_TO_KIND: dict[str, str] = {v: k for k, v in SYMBOL_KIND_TO_TABLE.items()}


def _get_psycopg2():
    """Lazy import psycopg2 — optional dependency."""
    try:
        import psycopg2  # nosec B611
        import psycopg2.extras  # nosec B611
        import psycopg2.pool  # nosec B611
        return psycopg2
    except ImportError as exc:
        raise ImportError(
            "psycopg2 is required for PostgreSQL support. "
            "Install it with: pip install psycopg2-binary"
        ) from exc


def _pg_ddl() -> list[str]:
    """Generate PostgreSQL-compatible DDL from schema definitions.

    Translates SQLite-specific syntax (AUTOINCREMENT, datetime('now'))
    to PostgreSQL equivalents (SERIAL, TIMESTAMPTZ DEFAULT NOW()).
    """
    return [
        # Files table
        """CREATE TABLE IF NOT EXISTS files (
            id              SERIAL PRIMARY KEY,
            path            TEXT NOT NULL UNIQUE,
            language        TEXT NOT NULL,
            file_hash       TEXT NOT NULL,
            last_indexed    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            symbol_count    INTEGER NOT NULL DEFAULT 0,
            edge_count      INTEGER NOT NULL DEFAULT 0,
            error_count     INTEGER NOT NULL DEFAULT 0
        )""",
        # Functions
        """CREATE TABLE IF NOT EXISTS functions (
            id              SERIAL PRIMARY KEY,
            file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            qualified_name  TEXT NOT NULL,
            signature       TEXT,
            start_line      INTEGER NOT NULL,
            start_col       INTEGER NOT NULL,
            end_line        INTEGER NOT NULL,
            end_col         INTEGER NOT NULL,
            is_partial      INTEGER NOT NULL DEFAULT 0
        )""",
        "CREATE INDEX IF NOT EXISTS idx_functions_name ON functions(name)",
        "CREATE INDEX IF NOT EXISTS idx_functions_file ON functions(file_id)",
        # Methods
        """CREATE TABLE IF NOT EXISTS methods (
            id              SERIAL PRIMARY KEY,
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
        )""",
        "CREATE INDEX IF NOT EXISTS idx_methods_name ON methods(name)",
        "CREATE INDEX IF NOT EXISTS idx_methods_parent ON methods(parent_class)",
        # Classes
        """CREATE TABLE IF NOT EXISTS classes (
            id              SERIAL PRIMARY KEY,
            file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            qualified_name  TEXT NOT NULL,
            start_line      INTEGER NOT NULL,
            start_col       INTEGER NOT NULL,
            end_line        INTEGER NOT NULL,
            end_col         INTEGER NOT NULL,
            is_partial      INTEGER NOT NULL DEFAULT 0
        )""",
        "CREATE INDEX IF NOT EXISTS idx_classes_name ON classes(name)",
        # Interfaces
        """CREATE TABLE IF NOT EXISTS interfaces (
            id              SERIAL PRIMARY KEY,
            file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            qualified_name  TEXT NOT NULL,
            start_line      INTEGER NOT NULL,
            start_col       INTEGER NOT NULL,
            end_line        INTEGER NOT NULL,
            end_col         INTEGER NOT NULL,
            is_partial      INTEGER NOT NULL DEFAULT 0
        )""",
        "CREATE INDEX IF NOT EXISTS idx_interfaces_name ON interfaces(name)",
        # Type aliases
        """CREATE TABLE IF NOT EXISTS type_aliases (
            id              SERIAL PRIMARY KEY,
            file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            qualified_name  TEXT NOT NULL,
            start_line      INTEGER NOT NULL,
            start_col       INTEGER NOT NULL,
            end_line        INTEGER NOT NULL,
            end_col         INTEGER NOT NULL,
            is_partial      INTEGER NOT NULL DEFAULT 0
        )""",
        "CREATE INDEX IF NOT EXISTS idx_type_aliases_name ON type_aliases(name)",
        # Variables
        """CREATE TABLE IF NOT EXISTS variables (
            id              SERIAL PRIMARY KEY,
            file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            qualified_name  TEXT NOT NULL,
            start_line      INTEGER NOT NULL,
            start_col       INTEGER NOT NULL,
            end_line        INTEGER NOT NULL,
            end_col         INTEGER NOT NULL,
            is_partial      INTEGER NOT NULL DEFAULT 0
        )""",
        "CREATE INDEX IF NOT EXISTS idx_variables_name ON variables(name)",
        # Edges
        """CREATE TABLE IF NOT EXISTS edges (
            id                SERIAL PRIMARY KEY,
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
        )""",
        "CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source)",
        "CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target)",
        "CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind)",
        "CREATE INDEX IF NOT EXISTS idx_edges_source_file ON edges(source_file_id)",
        "CREATE INDEX IF NOT EXISTS idx_edges_target_kind ON edges(target, kind)",
        "CREATE INDEX IF NOT EXISTS idx_edges_source_kind ON edges(source, kind)",
        # FTS via tsvector
        """CREATE TABLE IF NOT EXISTS fts_index (
            symbol_name     TEXT NOT NULL,
            qualified_name  TEXT NOT NULL,
            signature       TEXT,
            file_path       TEXT NOT NULL,
            kind            TEXT NOT NULL,
            search_vector   TSVECTOR
        )""",
        "CREATE INDEX IF NOT EXISTS idx_fts_search ON fts_index USING GIN(search_vector)",
        "CREATE INDEX IF NOT EXISTS idx_fts_file_path ON fts_index(file_path)",
        # Embeddings
        """CREATE TABLE IF NOT EXISTS embeddings (
            qualified_name  TEXT NOT NULL,
            file_path       TEXT NOT NULL,
            embedding       BYTEA,
            model_version   TEXT DEFAULT 'all-MiniLM-L6-v2',
            PRIMARY KEY (qualified_name, file_path)
        )""",
        # Schema version
        """CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            description TEXT NOT NULL DEFAULT ''
        )""",
        # Semantic store tables (P0: replaces JSON-file storage)
        """CREATE TABLE IF NOT EXISTS semantic_annotations (
            id              SERIAL PRIMARY KEY,
            file_path       TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            kind            TEXT NOT NULL DEFAULT 'unknown',
            summary         TEXT NOT NULL DEFAULT '',
            design_intent   TEXT NOT NULL DEFAULT '',
            pitfalls        TEXT NOT NULL DEFAULT '',
            source          TEXT NOT NULL DEFAULT 'manual',
            ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(file_path, symbol)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_sa_file ON semantic_annotations(file_path)",
        "CREATE INDEX IF NOT EXISTS idx_sa_symbol ON semantic_annotations(symbol)",
        """CREATE TABLE IF NOT EXISTS semantic_unknowns (
            id              SERIAL PRIMARY KEY,
            file_path       TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            question        TEXT NOT NULL,
            context         TEXT NOT NULL DEFAULT '',
            source          TEXT NOT NULL DEFAULT 'manual',
            ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(file_path, symbol, question)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_su_file ON semantic_unknowns(file_path)",
        """CREATE TABLE IF NOT EXISTS semantic_insights (
            id              SERIAL PRIMARY KEY,
            file_path       TEXT NOT NULL,
            insight         TEXT NOT NULL,
            related_symbols TEXT[] NOT NULL DEFAULT '{}',
            source          TEXT NOT NULL DEFAULT 'manual',
            ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_si_file ON semantic_insights(file_path)",
        """CREATE TABLE IF NOT EXISTS semantic_modules (
            id              SERIAL PRIMARY KEY,
            file_path       TEXT NOT NULL UNIQUE,
            module_summary  TEXT NOT NULL DEFAULT '',
            module_roles    JSONB NOT NULL DEFAULT '{}',
            metrics         JSONB NOT NULL DEFAULT '{}',
            odors           JSONB NOT NULL DEFAULT '[]',
            source          TEXT NOT NULL DEFAULT 'manual',
            ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_sm_file ON semantic_modules(file_path)",
    ]


class PostgreSQLStorageManager:
    """PostgreSQL-backed storage manager.

    Public API mirrors :class:`memorygraph.storage.manager.StorageManager`
    so callers can use either backend transparently.

    Connection pooling via ``psycopg2.pool.ThreadedConnectionPool``.
    """

    def __init__(self, project_root: str = "."):
        self._project_root = project_root
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            raise ValueError(
                "DATABASE_URL must be set to a PostgreSQL connection string "
                "(e.g. postgresql://user:pass@host/db)"
            )
        self._conn_string: str = db_url
        self._schema: str = _project_schema(project_root)
        self._pool: Any = None
        self._query_cache: QueryCache | None = None
        logger.info(
            "PostgreSQL backend: schema=%s (db=%s)", self._schema, db_url
        )

    @property
    def query_cache(self) -> "QueryCache":
        if self._query_cache is None:
            from memorygraph.storage.cache import QueryCache
            self._query_cache = QueryCache()
        return self._query_cache

    # === Connection management ===

    def connect(self) -> None:
        """Establish the connection pool (idempotent).

        Every connection automatically uses the project-specific schema
        via ``search_path``, so multiple projects sharing one PG database
        are fully isolated.
        """
        if self._pool is not None:
            return
        psycopg2 = _get_psycopg2()
        minconn = int(os.environ.get("MEMORYGRAPH_PG_MIN_CONN", "2"))
        maxconn = int(os.environ.get("MEMORYGRAPH_PG_MAX_CONN", "10"))
        # Inject search_path via DSN options so every pooled connection
        # automatically uses the correct schema.
        dsn = f"{self._conn_string} options=-c search_path={self._schema},public"
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=minconn,
            maxconn=maxconn,
            dsn=dsn,
        )

    def close(self) -> None:
        """Close all pooled connections."""
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None
        if self._query_cache:
            self._query_cache.clear()

    def initialize(self) -> None:
        """Initialize database schema (idempotent).

        Creates the project-specific PG schema, then all tables inside it.
        Two projects sharing a single PostgreSQL database each get their own
        schema and never interfere.
        """
        self.connect()
        conn = self._pool.getconn()
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                # Project-specific schema for automatic isolation.
                # Schema name is derived from SHA256 of the project path
                # (only hex chars — safe to embed directly).
                cur.execute(
                    f"CREATE SCHEMA IF NOT EXISTS {self._schema}"
                )
                for ddl in _pg_ddl():
                    cur.execute(ddl)
        finally:
            conn.autocommit = False
            self._pool.putconn(conn)

    def __enter__(self) -> "PostgreSQLStorageManager":
        self.initialize()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        self.close()
        return None

    # === Public accessors ===

    @property
    def db_path(self) -> str:
        """Return the connection string (for API compatibility)."""
        return self._conn_string

    def get_conn(self):
        """Return a raw connection from the pool.

        Caller MUST return it via ``putconn()``.
        """
        self.connect()
        return self._pool.getconn()

    def get_read_only_conn(self):
        """Return a read-only connection for concurrent queries."""
        self.connect()
        conn = self._pool.getconn()
        with conn.cursor() as cur:
            cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        return conn

    @contextmanager
    def read_only_connection(self) -> Iterator[Any]:
        """Context manager yielding a read-only PG connection."""
        self.connect()
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            yield conn
        finally:
            self._pool.putconn(conn)

    # === Data operations ===

    def upsert_file(self, result, batch: bool = False) -> tuple[int, list[tuple]]:
        """Insert or update a file's parse results in a single transaction.

        Returns:
            (file_id, fts_rows) — fts_rows for deferred FTS insertion.
        """
        self.connect()
        _get_psycopg2()  # ensure psycopg2 is installed
        conn = self._pool.getconn()
        try:
            path = result.file.path
            with conn.cursor() as cur:
                # Check existing file
                cur.execute("SELECT id FROM files WHERE path = %s", (path,))
                row = cur.fetchone()
                if row:
                    fid = row[0]
                    # Delete existing data for re-index
                    cur.execute(
                        "DELETE FROM edges WHERE source_file_id = %s", (fid,)
                    )
                    for table in SYMBOL_KIND_TO_TABLE.values():
                        cur.execute(
                            f"DELETE FROM {validate_table_name(table)} WHERE file_id = %s",  # nosec B608
                            (fid,),
                        )
                    cur.execute(
                        "DELETE FROM fts_index WHERE file_path = %s", (path,)
                    )

                # Upsert file record
                cur.execute(
                    """INSERT INTO files (path, language, file_hash, symbol_count, edge_count, error_count)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (path) DO UPDATE SET
                       language = EXCLUDED.language,
                       file_hash = EXCLUDED.file_hash,
                       symbol_count = EXCLUDED.symbol_count,
                       edge_count = EXCLUDED.edge_count,
                       error_count = EXCLUDED.error_count,
                       last_indexed = NOW()
                       RETURNING id""",
                    (path, result.file.language, result.file.content_hash,
                     len(result.symbols), len(result.edges), len(result.errors)),
                )
                fid = cur.fetchone()[0]

                # Group symbols by kind
                by_kind: dict[str, list] = {}
                fts_rows: list[tuple] = []
                for sym in result.symbols:
                    qn = self._qualified_name(sym)
                    sym_table = SYMBOL_KIND_TO_TABLE.get(sym.kind.value)
                    if sym_table is None:
                        continue
                    if sym_table not in by_kind:
                        by_kind[sym_table] = []
                    by_kind[sym_table].append(self._symbol_to_row(sym, qn))
                    fts_rows.append((
                        sym.name, qn, sym.signature or "", path, sym.kind.value
                    ))

                # Insert FTS rows immediately (non-batch) or defer (batch)
                if not batch and fts_rows:
                    self._insert_fts_rows(cur, fts_rows)

                # Bulk insert symbols
                for table, rows in by_kind.items():
                    self._insert_symbols(cur, table, rows, fid)

                # Insert edges
                self._insert_edges(cur, result, fid)

                if not batch:
                    conn.commit()
                return (fid, fts_rows)
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def delete_file(self, file_path: str) -> None:
        """Remove an indexed file and all associated data."""
        self.connect()
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM edges WHERE source_file_id = "
                    "(SELECT id FROM files WHERE path = %s)",
                    (file_path,),
                )
                cur.execute(
                    "DELETE FROM fts_index WHERE file_path = %s", (file_path,)
                )
                cur.execute(
                    "DELETE FROM files WHERE path = %s", (file_path,)
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def get_file_hash(self, file_path: str) -> str | None:
        self.connect()
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT file_hash FROM files WHERE path = %s", (file_path,)
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            self._pool.putconn(conn)

    def get_symbols_for_file(self, file_path: str) -> list[dict]:
        self.connect()
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM files WHERE path = %s", (file_path,))
                row = cur.fetchone()
                if not row:
                    return []
                fid = row[0]
                results: list[dict] = []
                for table in SYMBOL_KIND_TO_TABLE.values():
                    cur.execute(
                        f"SELECT * FROM {validate_table_name(table)} WHERE file_id = %s",  # nosec B608
                        (fid,),
                    )
                    columns = [desc[0] for desc in cur.description]
                    for r in cur.fetchall():
                        results.append(dict(zip(columns, r, strict=True)))
                return results
        finally:
            self._pool.putconn(conn)

    def search(self, query: str, limit: int = 20,
               file_path: str | None = None) -> list[dict]:
        """Full-text search via PostgreSQL tsvector/tsquery."""
        self.connect()
        conn = self._pool.getconn()
        try:
            cache_key = f"search:{query}:{limit}:{file_path or ''}"
            cached = self.query_cache.get(cache_key)
            if isinstance(cached, list):
                return cached

            with conn.cursor() as cur:
                if file_path:
                    cur.execute(
                        """SELECT symbol_name, qualified_name, signature, file_path, kind,
                                  ts_rank(search_vector, plainto_tsquery('english', %s)) AS rank
                           FROM fts_index
                           WHERE search_vector @@ plainto_tsquery('english', %s)
                             AND file_path = %s
                           ORDER BY rank DESC
                           LIMIT %s""",
                        (query, query, file_path, max(limit * 3, 60)),
                    )
                else:
                    cur.execute(
                        """SELECT symbol_name, qualified_name, signature, file_path, kind,
                                  ts_rank(search_vector, plainto_tsquery('english', %s)) AS rank
                           FROM fts_index
                           WHERE search_vector @@ plainto_tsquery('english', %s)
                           ORDER BY rank DESC
                           LIMIT %s""",
                        (query, query, max(limit * 3, 60)),
                    )
                columns = [desc[0] for desc in cur.description]
                results = [dict(zip(columns, r, strict=True)) for r in cur.fetchall()]

            for r in results:
                node = self.get_node(r["qualified_name"])
                if node:
                    r["start_line"] = node.get("start_line")
            self.query_cache.put(cache_key, results)
            return results[:limit]
        except Exception:
            conn.rollback()
            logger.warning("PG FTS search failed for query %r", query)
            return []
        finally:
            self._pool.putconn(conn)

    def bulk_upsert(self, results: dict) -> int:
        """Insert multiple parse results in a single transaction."""
        self.connect()
        _get_psycopg2()  # ensure psycopg2 is installed
        conn = self._pool.getconn()
        try:
            count = 0
            all_fts_rows: list[tuple] = []
            for _path, result in results.items():
                if result.fatal_error:
                    continue
                fid, fts_rows = self.upsert_file(result, batch=True)
                all_fts_rows.extend(fts_rows)
                count += 1

            if all_fts_rows:
                with conn.cursor() as cur:
                    self._insert_fts_rows(cur, all_fts_rows)

            conn.commit()
            if self._query_cache:
                self._query_cache.clear()
            return count
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def semantic_search(self, task: str, limit: int = 10,
                        file_path: str | None = None) -> list[dict]:
        """Multi-word semantic search via tokenized FTS."""
        import re
        words = [w for w in re.findall(r'\w+', task.lower()) if len(w) >= 3]
        if not words:
            return self.search(task, limit=limit, file_path=file_path)

        all_results: dict[str, dict] = {}
        for word in words:
            try:
                results = self.search(word, limit=limit * 3, file_path=file_path)
            except Exception:
                logger.debug("Word search failed for %r, skipping", word)
                continue
            for r in results:
                key = r["qualified_name"]
                if key in all_results:
                    all_results[key]["_score"] = all_results[key].get("_score", 1) + 1
                else:
                    r["_score"] = 1
                    all_results[key] = r

        sorted_results = sorted(
            all_results.values(), key=lambda r: r["_score"], reverse=True
        )

        if not sorted_results and len(words) > 1:
            try:
                results = self.search(task, limit=limit)
                for r in results:
                    r["_score"] = 1
                sorted_results = results
            except Exception:
                logger.debug("Fallback phrase search failed for %r", task)

        return sorted_results[:limit]

    def get_callers(self, qualified_name: str, depth: int = 1,
                    file_path: str | None = None) -> list[dict]:
        cache_key = f"callers:{qualified_name}:{file_path}:{depth}"
        cached = self.query_cache.get(cache_key)
        if isinstance(cached, list):
            return cached
        result = self._graph_walk(qualified_name, depth, file_path, "up")
        self.query_cache.put(cache_key, result)
        return result

    def get_callees(self, qualified_name: str, depth: int = 1,
                    file_path: str | None = None) -> list[dict]:
        cache_key = f"callees:{qualified_name}:{file_path}:{depth}"
        cached = self.query_cache.get(cache_key)
        if isinstance(cached, list):
            return cached
        result = self._graph_walk(qualified_name, depth, file_path, "down")
        self.query_cache.put(cache_key, result)
        return result

    def get_impact(self, qualified_name: str, max_depth: int = 5) -> list[dict]:
        return self.get_callees(qualified_name, max_depth)

    def get_node(self, qualified_name: str,
                 file_path: str | None = None) -> dict | None:
        self.connect()
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                for kind_value, table in SYMBOL_KIND_TO_TABLE.items():
                    if file_path:
                        cur.execute(
                            f"SELECT s.*, f.path AS file_path "  # nosec B608
                            f"FROM {validate_table_name(table)} s "
                            f"JOIN files f ON f.id = s.file_id "
                            f"WHERE s.qualified_name = %s AND f.path = %s",
                            (qualified_name, file_path),
                        )
                    else:
                        cur.execute(
                            f"SELECT s.*, f.path AS file_path "  # nosec B608
                            f"FROM {validate_table_name(table)} s "
                            f"JOIN files f ON f.id = s.file_id "
                            f"WHERE s.qualified_name = %s",
                            (qualified_name,),
                        )
                    row = cur.fetchone()
                    if row:
                        columns = [desc[0] for desc in cur.description]
                        result = dict(zip(columns, row, strict=True))
                        result["kind"] = kind_value
                        return result
                return None
        finally:
            self._pool.putconn(conn)

    def stats(self) -> dict:
        self.connect()
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM files")
                file_count = cur.fetchone()[0]
                sym_count = 0
                for t in SYMBOL_KIND_TO_TABLE.values():
                    cur.execute(
                        f"SELECT COUNT(*) FROM {validate_table_name(t)}"  # nosec B608
                    )
                    sym_count += cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM edges")
                edge_count = cur.fetchone()[0]
                cur.execute("SELECT MAX(last_indexed) FROM files")
                last = cur.fetchone()[0]
                # Embeddings
                emb_available = False
                try:
                    cur.execute("SELECT COUNT(*) FROM embeddings")
                    emb_available = cur.fetchone()[0] > 0
                except Exception:
                    logger.warning(
                        "Failed to query embeddings table (may not exist yet)",
                        exc_info=True,
                    )
                return {
                    "file_count": file_count,
                    "symbol_count": sym_count,
                    "edge_count": edge_count,
                    "last_updated": str(last) if last else "never",
                    "semantic_coverage": "0%",
                    "embeddings_available": emb_available,
                    "backend": "postgresql",
                }
        finally:
            self._pool.putconn(conn)

    def list_files(self) -> list[dict]:
        self.connect()
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT path, language, file_hash, symbol_count, "
                    "error_count, last_indexed FROM files ORDER BY path"
                )
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, r, strict=True)) for r in cur.fetchall()]
        finally:
            self._pool.putconn(conn)

    # === Internal helpers ===

    def _qualified_name(self, sym) -> str:
        return qualified_name(sym)

    def _symbol_to_row(self, sym, qn: str) -> tuple:
        return symbol_to_row(sym, qn)

    def _insert_symbols(self, cur, table: str,
                        rows: list, file_id: int) -> None:
        """Insert symbol rows into the appropriate PG table."""
        psycopg2 = _get_psycopg2()  # noqa: F841 — used via psycopg2.extras.execute_values

        if table == "methods":
            sql = (
                "INSERT INTO methods (file_id, name, qualified_name, parent_class, "
                "signature, start_line, start_col, end_line, end_col, is_partial) "
                "VALUES %s"
            )
        elif table == "functions":
            sql = (
                "INSERT INTO functions (file_id, name, qualified_name, signature, "
                "start_line, start_col, end_line, end_col, is_partial) "
                "VALUES %s"
            )
        else:
            sql = (
                f"INSERT INTO {validate_table_name(table)} "  # nosec B608
                "(file_id, name, qualified_name, start_line, start_col, "
                "end_line, end_col, is_partial) VALUES %s"
            )
        values = [(file_id, *row) for row in rows]
        psycopg2.extras.execute_values(cur, sql, values)

    def _insert_edges(self, cur, result, fid: int) -> None:
        """Insert edge rows using execute_values for batch efficiency."""
        psycopg2 = _get_psycopg2()
        edge_rows = []
        for edge in result.edges:
            tgt_fid = None
            tgt_line = tgt_col = tgt_end_line = tgt_end_col = None
            if edge.target_span is not None:
                tgt_fid = self._find_file_id(cur, edge.target_span.file)
                tgt_line = edge.target_span.start_line
                tgt_col = edge.target_span.start_col
                tgt_end_line = edge.target_span.end_line
                tgt_end_col = edge.target_span.end_col
            edge_rows.append((
                edge.source, edge.target, edge.kind.value, fid,
                edge.source_span.start_line, edge.source_span.start_col,
                edge.source_span.end_line, edge.source_span.end_col,
                tgt_fid, tgt_line, tgt_col, tgt_end_line, tgt_end_col,
            ))
        if edge_rows:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO edges
                   (source, target, kind, source_file_id,
                    source_start_line, source_start_col, source_end_line, source_end_col,
                    target_file_id, target_start_line, target_start_col, target_end_line, target_end_col)
                   VALUES %s""",
                edge_rows,
            )

    def _insert_fts_rows(self, cur, fts_rows: list[tuple]) -> None:
        """Insert FTS rows with tsvector generation from name + signature."""
        from psycopg2.extras import execute_values  # nosec B611
        execute_values(
            cur,
            """INSERT INTO fts_index (symbol_name, qualified_name, signature, file_path, kind, search_vector)
               VALUES %s""",
            [
                (name, qn, sig, fpath, kind, None)
                for name, qn, sig, fpath, kind in fts_rows
            ],
        )
        # Update search_vector from the text columns (PG function, not app-level)
        cur.execute(
            """UPDATE fts_index
               SET search_vector = to_tsvector('english', coalesce(symbol_name, '') || ' ' || coalesce(signature, ''))
               WHERE search_vector IS NULL"""
        )

    def _graph_walk(self, qualified_name: str, depth: int,
                    file_path: str | None, direction: str) -> list[dict]:
        """PostgreSQL recursive CTE for callers/callees traversal."""
        self.connect()
        conn = self._pool.getconn()
        try:
            is_up = direction == "up"
            anchor_col = "target" if is_up else "source"
            join_on = ("e.target = cc.source" if is_up
                       else "e.source = cc.target")

            short_name = qualified_name.split(".")[-1] if "." in qualified_name else None

            with conn.cursor() as cur:
                if file_path:
                    if short_name:
                        cur.execute(
                            f"""WITH RECURSIVE chain AS (
                                  SELECT e.source, e.target, e.kind, 1 AS depth
                                  FROM edges e
                                  JOIN files f ON f.id = e.source_file_id
                                  WHERE (e.{anchor_col} = %s OR e.{anchor_col} = %s)
                                    AND e.kind = 'calls' AND f.path = %s
                                  UNION ALL
                                  SELECT e.source, e.target, e.kind, cc.depth + 1
                                  FROM edges e
                                  JOIN chain cc ON {join_on}
                                  WHERE e.kind = 'calls' AND cc.depth < %s
                                )
                                SELECT DISTINCT source, target, depth FROM chain ORDER BY depth""",  # nosec B608
                            (qualified_name, short_name, file_path, depth),
                        )
                    else:
                        cur.execute(
                            f"""WITH RECURSIVE chain AS (
                                  SELECT e.source, e.target, e.kind, 1 AS depth
                                  FROM edges e
                                  JOIN files f ON f.id = e.source_file_id
                                  WHERE e.{anchor_col} = %s AND e.kind = 'calls' AND f.path = %s
                                  UNION ALL
                                  SELECT e.source, e.target, e.kind, cc.depth + 1
                                  FROM edges e
                                  JOIN chain cc ON {join_on}
                                  WHERE e.kind = 'calls' AND cc.depth < %s
                                )
                                SELECT DISTINCT source, target, depth FROM chain ORDER BY depth""",  # nosec B608
                            (qualified_name, file_path, depth),
                        )
                elif short_name:
                    cur.execute(
                        f"""WITH RECURSIVE chain AS (
                              SELECT source, target, kind, 1 AS depth
                              FROM edges
                              WHERE ({anchor_col} = %s OR {anchor_col} = %s) AND kind = 'calls'
                              UNION ALL
                              SELECT e.source, e.target, e.kind, cc.depth + 1
                              FROM edges e
                              JOIN chain cc ON {join_on}
                              WHERE e.kind = 'calls' AND cc.depth < %s
                            )
                            SELECT DISTINCT source, target, depth FROM chain ORDER BY depth""",  # nosec B608
                        (qualified_name, short_name, depth),
                    )
                else:
                    cur.execute(
                        f"""WITH RECURSIVE chain AS (
                              SELECT source, target, kind, 1 AS depth
                              FROM edges
                              WHERE {anchor_col} = %s AND kind = 'calls'
                              UNION ALL
                              SELECT e.source, e.target, e.kind, cc.depth + 1
                              FROM edges e
                              JOIN chain cc ON {join_on}
                              WHERE e.kind = 'calls' AND cc.depth < %s
                            )
                            SELECT DISTINCT source, target, depth FROM chain ORDER BY depth""",  # nosec B608
                        (qualified_name, depth),
                    )
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, r, strict=True)) for r in cur.fetchall()]
        finally:
            self._pool.putconn(conn)

    def _find_file_id(self, cur, path: str) -> int | None:
        """Resolve a file path to its internal ID."""
        cur.execute("SELECT id FROM files WHERE path = %s", (path,))
        row = cur.fetchone()
        return row[0] if row else None
