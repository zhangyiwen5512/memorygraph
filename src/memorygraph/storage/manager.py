"""StorageManager — 存储层的唯一对外入口。"""
from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager, suppress
from types import TracebackType
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from memorygraph.storage.cache import QueryCache  # pragma: no cover

from memorygraph.parsing.ir import ParseResult
from memorygraph.storage.connection import get_connection, get_db_path
from memorygraph.storage.helpers import qualified_name, symbol_to_row
from memorygraph.storage.repositories import EdgeRepo, FileRepo, FTSRepo, SymbolRepo
from memorygraph.storage.schema import SYMBOL_KIND_TO_TABLE, init_db, validate_table_name

logger = logging.getLogger(__name__)

# Reverse mapping: table name → kind string (e.g. "functions" → "function")
_TABLE_TO_KIND: dict[str, str] = {v: k for k, v in SYMBOL_KIND_TO_TABLE.items()}


def _reconstruct_path(
    forward: dict[str, str | None],
    backward: dict[str, str | None],
    meeting: str,
) -> dict:
    """Reconstruct the shortest path from bidirectional BFS frontiers."""
    # Build path from source → meeting
    fwd_path: list[str] = []
    cur: str | None = meeting
    while cur is not None:
        fwd_path.append(cur)
        cur = forward.get(cur)
    fwd_path.reverse()

    # Build path from meeting → target
    bwd_path: list[str] = []
    cur = backward.get(meeting)
    while cur is not None:
        bwd_path.append(cur)
        cur = backward.get(cur)

    node_ids = fwd_path + bwd_path
    edges = []
    for i in range(len(node_ids) - 1):
        edges.append({
            "source": node_ids[i],
            "target": node_ids[i + 1],
            "kind": "calls",
        })

    return {
        "found": True,
        "path": edges,
        "node_ids": node_ids,
        "length": len(node_ids) - 1,
    }


class StorageManager:
    """代码图谱的持久化存储。"""

    def __init__(self, project_root: str = "."):
        self._db_path = get_db_path(project_root)
        self._conn: sqlite3.Connection | None = None
        self._conn_lock = threading.Lock()
        self._file_id_cache: dict[str, int] = {}
        self._file_id_cache_lock = threading.Lock()
        self._query_cache: QueryCache | None = None
        self._read_only_conns: list[sqlite3.Connection] = []
        self._ro_lock = threading.Lock()
        self._closing = False

    @property
    def query_cache(self) -> "QueryCache":
        if self._query_cache is None:
            from memorygraph.storage.cache import QueryCache  # noqa: F811
            self._query_cache = QueryCache()
        return self._query_cache

    def initialize(self) -> None:
        """初始化数据库 schema。幂等。"""
        conn = self._get_conn()
        init_db(conn)

    def __enter__(self) -> "StorageManager":
        """Context manager entry — initializes the database and returns self."""
        self.initialize()
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> bool | None:
        """Context manager exit — always closes the connection."""
        self.close()
        return None

    def close(self) -> None:
        self._closing = True
        with self._conn_lock:
            if self._conn:
                self._conn.close()
                self._conn = None
        with self._ro_lock:
            for ro_conn in self._read_only_conns:
                with suppress(Exception):
                    ro_conn.close()  # may already be closed by context manager
            self._read_only_conns.clear()
        with self._file_id_cache_lock:
            self._file_id_cache.clear()
        if self._query_cache:
            self._query_cache.clear()

    def __del__(self) -> None:
        """Best-effort cleanup on garbage collection."""
        with suppress(Exception):
            self.close()

    def upsert_file(self, result: ParseResult, batch: bool = False) -> tuple[int, list[tuple]]:
        """插入或更新一个文件的全量数据。单事务内完成。

        Returns:
            A tuple of ``(file_id, fts_rows)`` where ``fts_rows`` is the list
            of FTS rows collected for this file.  The caller is responsible
            for inserting these FTS rows (via :class:`FTSRepo.insert_batch`)
            and rebuilding the FTS index when ``batch=True``; when
            ``batch=False`` they are inserted immediately before committing.
        """
        conn = self._get_conn()
        file_repo = FileRepo(conn)
        sym_repo = SymbolRepo(conn)
        edge_repo = EdgeRepo(conn)
        fts_repo = FTSRepo(conn)

        try:
            path = result.file.path
            fid_row = conn.execute(
                "SELECT id FROM files WHERE path = ?", (path,)
            ).fetchone()

            if fid_row:
                fid = fid_row[0]
                stored_hash = file_repo.get_hash(path)
                if stored_hash == result.file.content_hash:
                    return (fid, [])  # unchanged, skip re-index
                edge_repo.delete_by_source_file(fid)
                for table in SYMBOL_KIND_TO_TABLE.values():
                    sym_repo.delete_by_file(table, fid)
                fts_repo.delete_by_file(path)

            # Upsert file record
            fid = file_repo.upsert(
                path=path,
                language=result.file.language,
                file_hash=result.file.content_hash,
                symbol_count=len(result.symbols),
                edge_count=len(result.edges),
                error_count=len(result.errors),
            )

            # Group symbols by kind and collect FTS rows for deferred insert
            by_kind: dict[str, list] = {}
            fts_rows: list[tuple] = []
            for sym in result.symbols:
                qn = self._qualified_name(sym)
                sym_table: str | None = SYMBOL_KIND_TO_TABLE.get(sym.kind.value)
                if sym_table is None:
                    continue
                if sym_table not in by_kind:
                    by_kind[sym_table] = []
                by_kind[sym_table].append(self._symbol_to_row(sym, qn))
                fts_rows.append((
                    sym.name, qn, sym.signature or "", path, sym.kind.value
                ))

            # In non-batch mode, insert FTS rows immediately (caller does not
            # handle them).  In batch mode, defer insertion to bulk_upsert.
            if not batch and fts_rows:
                fts_repo.insert_batch(fts_rows)
                conn.execute("INSERT INTO fts_index(fts_index) VALUES('rebuild')")

            # Bulk insert symbols
            for table, rows in by_kind.items():
                self._insert_symbols(sym_repo, table, rows, fid)

            # Insert edges
            edge_rows = []
            for edge in result.edges:
                tgt_fid = None
                tgt_line = tgt_col = tgt_end_line = tgt_end_col = None
                if edge.target_span is not None:
                    tgt_fid = self._find_file_id(conn, edge.target_span.file)
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
                edge_repo.insert_batch(edge_rows)

            if not batch:
                conn.commit()
            return (fid, fts_rows)
        except Exception:
            conn.rollback()
            raise

    def delete_file(self, file_path: str) -> None:
        """Remove an indexed file and all of its associated data.

        Deletes the file's edges, full-text-search entries, and the file
        record itself from the database in a single transaction.

        Args:
            file_path: Absolute path of the file to remove from the index.
        """
        conn = self._get_conn()
        fid_row = conn.execute(
            "SELECT id FROM files WHERE path = ?", (file_path,)
        ).fetchone()
        if fid_row is None:
            return  # file not indexed, nothing to delete
        fid = fid_row[0]
        conn.execute(
            "DELETE FROM edges WHERE source_file_id = ?", (fid,)
        )
        conn.execute(
            "DELETE FROM edges WHERE target_file_id = ?", (fid,)
        )
        # Explicitly delete from per-kind symbol tables (defense in depth:
        # SQLite foreign-key CASCADE handles this, but explicit deletes
        # protect against the PRAGMA being silently off).
        from memorygraph.storage.schema import SYMBOL_TABLES, validate_table_name
        for table in SYMBOL_TABLES:
            safe_name = validate_table_name(table)
            conn.execute(
                f"DELETE FROM {safe_name} WHERE file_id = ?", (fid,)  # nosec B608
            )
        conn.execute("DELETE FROM fts_index WHERE file_path = ?", (file_path,))
        conn.execute("DELETE FROM files WHERE id = ?", (fid,))
        conn.commit()

    def get_file_hash(self, file_path: str) -> str | None:
        return FileRepo(self._get_conn()).get_hash(file_path)

    def get_symbols_for_file(self, file_path: str) -> list[dict]:
        """Look up all indexed symbols defined in a given file.

        Queries every symbol-kind table (functions, methods, classes, etc.)
        for rows matching the file's internal ID.

        Args:
            file_path: Absolute path of the indexed file.

        Returns:
            A list of symbol dicts (one per row in each symbol table), or
            an empty list if the file is not indexed.
        """
        conn = self._get_conn()
        fid_row = conn.execute(
            "SELECT id FROM files WHERE path = ?", (file_path,)
        ).fetchone()
        if not fid_row:
            return []
        fid = fid_row[0]
        results: list[dict] = []
        for table in SYMBOL_KIND_TO_TABLE.values():
            rows = conn.execute(
                f"SELECT * FROM {validate_table_name(table)} WHERE file_id = ?", (fid,)  # nosec B608
            ).fetchall()
            results.extend(dict(r) for r in rows)
        return results

    def search(self, query: str, limit: int = 20,
               file_path: str | None = None) -> list[dict]:
        """Search indexed symbols by name or signature via FTS5.

        Results are cached in the query cache. Each result is enriched
        with the symbol's ``start_line`` from its full node record.

        Args:
            query: The full-text search string (FTS5 syntax).
            limit: Maximum number of results to return (default 20).
            file_path: Optional file path filter (exact match).

        Returns:
            A list of result dicts with keys such as ``qualified_name``,
            ``kind``, ``file_path``, ``signature``, and ``start_line``.
        """
        cache_key = f"search:{query}:{limit}:{file_path or ''}"
        cached = self.query_cache.get(cache_key)
        if isinstance(cached, list):
            return cached  # type: ignore[return-value]
        results = FTSRepo(self._get_conn()).search(query, limit, file_path=file_path)
        # Batch-fetch start_line by kind group (1 query per kind, max 6)
        # instead of N individual get_node() calls.
        self._enrich_start_lines(results)
        self.query_cache.put(cache_key, results)
        return results

    def _enrich_start_lines(self, results: list[dict]) -> None:
        """Batch-fetch ``start_line`` for FTS search results by kind group.

        Instead of calling :meth:`get_node` once per result (N queries),
        group results by ``kind`` and issue at most one ``SELECT`` per
        symbol table (≤6 queries total).
        """
        if not results:
            return
        conn = self._get_conn()
        # Group qualified_name by kind → table
        by_table: dict[str, list[str]] = {}
        for r in results:
            table = SYMBOL_KIND_TO_TABLE.get(r.get("kind", ""))
            if table:
                by_table.setdefault(table, []).append(r["qualified_name"])
        # Batch fetch start_line per table
        start_lines: dict[str, int] = {}
        for table, names in by_table.items():
            vtable = validate_table_name(table)
            # SQLite IN clause max 999 params; safe for typical search limits
            placeholders = ",".join(["?"] * len(names))
            rows = conn.execute(
                f"SELECT qualified_name, start_line FROM {vtable} "  # nosec B608
                f"WHERE qualified_name IN ({placeholders})",
                names,
            ).fetchall()
            for row in rows:
                start_lines[row["qualified_name"]] = row["start_line"]
        # Enrich results
        for r in results:
            sl = start_lines.get(r["qualified_name"])
            if sl is not None:
                r["start_line"] = sl

    def bulk_upsert(self, results: dict) -> int:
        """Insert multiple parse results in a single transaction.

        FTS rows are deferred — they are collected from every file and
        inserted once at the end, followed by an FTS index rebuild, which
        significantly reduces write overhead during large indexing passes.
        """
        conn = self._get_conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            count = 0
            all_fts_rows: list[tuple] = []
            for _path, result in results.items():
                if result.fatal_error:
                    continue
                fid, fts_rows = self.upsert_file(result, batch=True)
                all_fts_rows.extend(fts_rows)
                count += 1

            # Deferred FTS insertion: single batch insert + index rebuild
            if all_fts_rows:
                FTSRepo(conn).insert_batch(all_fts_rows)
                conn.execute("INSERT INTO fts_index(fts_index) VALUES('rebuild')")

            conn.commit()
            if self._query_cache:
                self._query_cache.clear()
            return count
        except Exception:
            conn.rollback()
            raise

    @contextmanager
    def read_only_connection(self) -> Iterator[sqlite3.Connection]:
        """Context manager yielding a read-only connection.

        The connection is automatically closed when the ``with`` block
        exits and is also tracked so that :meth:`close` will clean it up
        if the caller forgets to exit the block (e.g. during shutdown).

        Usage::

            with manager.read_only_connection() as conn:
                rows = conn.execute("SELECT ...").fetchall()
        """
        conn = get_connection(self._db_path)
        conn.execute("PRAGMA query_only = ON")
        with self._ro_lock:
            if self._closing:
                conn.close()
                raise RuntimeError("StorageManager is shutting down")
            self._read_only_conns.append(conn)
        try:
            yield conn
        finally:
            with self._ro_lock, suppress(ValueError):
                self._read_only_conns.remove(conn)  # close() already cleared the list
            with suppress(Exception):
                conn.close()  # close() may have already closed it

    def semantic_search(self, task: str, limit: int = 10,
                        file_path: str | None = None) -> list[dict]:
        """Search by multi-word task description, not just symbol names.

        Tokenizes the task into words, searches each via FTS5,
        merges results ranked by how many words matched.

        Args:
            task: Multi-word task/feature description.
            limit: Maximum results.
            file_path: Optional file path filter.
        """
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

        # Fallback: if no multi-word match, try full phrase as single FTS5 query
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
            return cached  # type: ignore[return-value]
        result = EdgeRepo(self._get_conn()).get_callers(
            qualified_name, depth, file_path=file_path
        )
        self.query_cache.put(cache_key, result)
        return result

    def get_callees(self, qualified_name: str, depth: int = 1,
                    file_path: str | None = None) -> list[dict]:
        cache_key = f"callees:{qualified_name}:{file_path}:{depth}"
        cached = self.query_cache.get(cache_key)
        if isinstance(cached, list):
            return cached  # type: ignore[return-value]
        result = EdgeRepo(self._get_conn()).get_callees(
            qualified_name, depth, file_path=file_path
        )
        self.query_cache.put(cache_key, result)
        return result

    def get_impact(self, qualified_name: str, max_depth: int = 5) -> list[dict]:
        return EdgeRepo(self._get_conn()).get_callees(qualified_name, max_depth)

    def get_node(self, qualified_name: str,
                 file_path: str | None = None) -> dict | None:
        """Retrieve a single symbol node by its qualified name.

        Searches across all symbol-kind tables. Optionally restricts the
        lookup to a specific file to resolve ambiguous names.

        Args:
            qualified_name: Fully qualified symbol name (e.g. ``module.ClassName.method``).
            file_path: If given, only return a match from this file.

        Returns:
            A dict with the symbol's row data (including ``file_path`` and
            ``kind``) or ``None`` if no matching symbol is found.
        """
        conn = self._get_conn()
        for kind_value, table in SYMBOL_KIND_TO_TABLE.items():
            if file_path:
                row = conn.execute(
                    f"SELECT s.*, f.path AS file_path FROM {validate_table_name(table)} s "  # nosec B608
                    f"JOIN files f ON f.id = s.file_id "
                    f"WHERE s.qualified_name = ? AND f.path = ?",
                    (qualified_name, file_path)
                ).fetchone()
            else:
                row = conn.execute(
                    f"SELECT s.*, f.path AS file_path FROM {validate_table_name(table)} s "  # nosec B608
                    f"JOIN files f ON f.id = s.file_id "
                    f"WHERE s.qualified_name = ?",
                    (qualified_name,)
                ).fetchone()
            if row:
                result = dict(row)
                result["kind"] = kind_value
                return result
        return None

    def stats(self) -> dict:
        conn = self._get_conn()
        file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        sym_count = sum(
            conn.execute(f"SELECT COUNT(*) FROM {validate_table_name(t)}").fetchone()[0]  # nosec B608
            for t in SYMBOL_KIND_TO_TABLE.values()
        )
        edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        last = conn.execute("SELECT MAX(last_indexed) FROM files").fetchone()[0]
        # Check if embeddings are available
        emb_available = False
        try:
            emb_count = conn.execute(
                "SELECT COUNT(*) FROM embeddings"
            ).fetchone()[0]
            emb_available = emb_count > 0
        except Exception:
            logger.warning("Failed to query embeddings table (may not exist yet)", exc_info=True)
        return {
            "file_count": file_count,
            "symbol_count": sym_count,
            "edge_count": edge_count,
            "last_updated": last or "never",
            "semantic_coverage": "0%",
            "embeddings_available": emb_available,
            "backend": "sqlite",
        }

    def list_files(self) -> list[dict]:
        """Return all indexed files with metadata. Public API."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT path, language, file_hash, symbol_count, "
            "error_count, last_indexed FROM files ORDER BY path"
        ).fetchall()
        return [dict(r) for r in rows]

    # === Public accessors ===

    @property
    def db_path(self) -> str:
        """Return the path to the SQLite database file."""
        return self._db_path

    @property
    def symbol_tables(self) -> list[str]:
        """All symbol table names for batch queries."""
        from memorygraph.storage.schema import SYMBOL_TABLES
        return list(SYMBOL_TABLES)

    def get_all_edges(self) -> list[dict]:
        """Return all edges in the graph as ``[{source, target, kind}, ...]``."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT source, target, kind FROM edges"
        ).fetchall()
        return [{"source": r[0], "target": r[1], "kind": r[2]} for r in rows]

    def get_shortest_path(self, source: str, target: str, max_depth: int = 20) -> dict:
        """Bidirectional BFS to find shortest path between two symbols.

        Returns ``{"found": bool, "path": [...], "node_ids": [...], "length": int}``.
        """
        if source == target:
            return {"found": True, "path": [], "node_ids": [source], "length": 0}

        conn = self._get_conn()
        # Forward: source → ?
        # Backward: ? → target
        forward: dict[str, str | None] = {source: None}
        backward: dict[str, str | None] = {target: None}
        forward_queue: list[str] = [source]
        backward_queue: list[str] = [target]

        for _depth in range(max_depth):
            # Expand forward
            next_forward: list[str] = []
            for node in forward_queue:
                rows = conn.execute(
                    "SELECT target FROM edges WHERE source = ?", (node,)
                ).fetchall()
                for (nxt,) in rows:
                    if nxt in forward:
                        continue
                    forward[nxt] = node
                    next_forward.append(nxt)
                    if nxt in backward:
                        return _reconstruct_path(forward, backward, nxt)
            forward_queue = next_forward

            # Expand backward
            next_backward: list[str] = []
            for node in backward_queue:
                rows = conn.execute(
                    "SELECT source FROM edges WHERE target = ?", (node,)
                ).fetchall()
                for (prev,) in rows:
                    if prev in backward:
                        continue
                    backward[prev] = node
                    next_backward.append(prev)
                    if prev in forward:
                        return _reconstruct_path(forward, backward, prev)
            backward_queue = next_backward

        return {"found": False, "path": [], "node_ids": [], "length": 0}

    def get_conn(self) -> sqlite3.Connection:
        """Return the singleton write connection, creating it on first call.

        This returns the same write-capable connection used internally by
        all ``StorageManager`` methods. For read-only access, use the
        :meth:`read_only_connection` context manager instead.
        """
        return self._get_conn()  # pragma: no cover — internal getter, tested indirectly

    # === Internal helpers ===

    def _get_conn(self) -> sqlite3.Connection:
        """Return the shared write connection (thread-safe, double-checked)."""
        if self._conn is None:
            with self._conn_lock:
                if self._conn is None:
                    self._conn = get_connection(self._db_path)
        return self._conn

    def _qualified_name(self, sym) -> str:
        return qualified_name(sym)

    def _symbol_to_row(self, sym, qn: str) -> tuple:
        return symbol_to_row(sym, qn)

    def _insert_symbols(self, repo: SymbolRepo, table: str,
                        rows: list, file_id: int) -> None:
        method_map = {
            "functions": repo.insert_functions,
            "methods": repo.insert_methods,
            "classes": repo.insert_classes,
            "interfaces": repo.insert_interfaces,
            "type_aliases": repo.insert_type_aliases,
            "variables": repo.insert_variables,
        }
        insert_fn = method_map.get(table)
        if insert_fn:
            insert_fn(rows, file_id)
        else:  # pragma: no cover — defensive, only reached if method_map is out of sync with SYMBOL_KIND_TO_TABLE
            import logging
            logging.warning("Unknown symbol table: %s", table)

    def _find_file_id(self, conn, path: str) -> int | None:
        with self._file_id_cache_lock:
            if path in self._file_id_cache:
                return self._file_id_cache[path]
        row = conn.execute(
            "SELECT id FROM files WHERE path = ?", (path,)
        ).fetchone()
        if row:
            with self._file_id_cache_lock:
                # Double-check: another thread may have populated the cache
                # between our first check and the DB query.
                if path not in self._file_id_cache:
                    self._file_id_cache[path] = row[0]
                return self._file_id_cache[path]
        return None
