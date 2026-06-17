"""Repository classes for individual table operations."""
import sqlite3

from memorygraph.storage.schema import SYMBOL_KIND_TO_TABLE, validate_table_name

# Kind priority: lower = higher priority in search results
_KIND_PRIORITY: dict[str, int] = {
    "class": 0,
    "interface": 0,
    "function": 50,
    "method": 50,
    "type_alias": 80,
    "variable": 100,
}


def _rank_search_results(results: list[dict], query: str) -> list[dict]:
    """Re-rank search results combining FTS5 rank with name match quality.

    Applies bonus scores for exact/prex/partial name matches and symbol kind
    priority.  Lower score = better result.

    Scoring tiers:
      - Exact name match: -1000 points
      - Prex match (symbol_name starts with query): -500 points
      - Partial match (query in symbol_name): -200 points
      - Kind priority: class/interface(0) < function/method(+50) < other(+100)
    """
    q_lower = query.lower().strip()
    for r in results:
        score = float(r.get("rank", 0))
        name = (r.get("symbol_name") or "").lower()

        # Name match boost (prefer exact > prex > partial)
        if name == q_lower:
            score -= 1000
        elif name.startswith(q_lower):
            score -= 500
        elif q_lower in name:
            score -= 200

        # Kind priority boost
        kind = r.get("kind", "")
        score += _KIND_PRIORITY.get(kind, 110)

        r["_score"] = score

    results.sort(key=lambda r: r["_score"])
    return results


class FileRepo:
    """文件元信息表 CRUD。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def upsert(self, path: str, language: str, file_hash: str,
               symbol_count: int, edge_count: int, error_count: int) -> int:
        """插入或更新文件记录，返回 file_id。使用 RETURNING 避免二次查询。"""
        row = self._conn.execute(
            """INSERT INTO files (path, language, file_hash, symbol_count, edge_count, error_count)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET
               language=excluded.language,
               file_hash=excluded.file_hash,
               symbol_count=excluded.symbol_count,
               edge_count=excluded.edge_count,
               error_count=excluded.error_count,
               last_indexed=datetime('now')
               RETURNING id""",
            (path, language, file_hash, symbol_count, edge_count, error_count)
        ).fetchone()
        assert row is not None, "RETURNING id should always return a row"
        return row[0]

    def get_hash(self, path: str) -> str | None:
        row = self._conn.execute(
            "SELECT file_hash FROM files WHERE path = ?", (path,)
        ).fetchone()
        return row[0] if row else None


class SymbolRepo:
    """符号表 CRUD。每种符号类型一张表。"""

    # Re-use the canonical mapping from schema.py to avoid duplication.
    # If a new symbol kind is added, only schema.py needs updating.
    SYMBOL_KIND_TO_TABLE = SYMBOL_KIND_TO_TABLE

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert_functions(self, rows: list[tuple], file_id: int) -> None:
        self._conn.executemany(
            """INSERT INTO functions (file_id, name, qualified_name, signature,
               start_line, start_col, end_line, end_col, is_partial)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(file_id, *row) for row in rows]
        )

    def insert_methods(self, rows: list[tuple], file_id: int) -> None:
        self._conn.executemany(
            """INSERT INTO methods (file_id, name, qualified_name, parent_class, signature,
               start_line, start_col, end_line, end_col, is_partial)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(file_id, *row) for row in rows]
        )

    def insert_classes(self, rows: list[tuple], file_id: int) -> None:
        self._conn.executemany(
            """INSERT INTO classes (file_id, name, qualified_name,
               start_line, start_col, end_line, end_col, is_partial)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [(file_id, *row) for row in rows]
        )

    def insert_interfaces(self, rows: list[tuple], file_id: int) -> None:
        self._conn.executemany(
            """INSERT INTO interfaces (file_id, name, qualified_name,
               start_line, start_col, end_line, end_col, is_partial)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [(file_id, *row) for row in rows]
        )

    def insert_type_aliases(self, rows: list[tuple], file_id: int) -> None:
        self._conn.executemany(
            """INSERT INTO type_aliases (file_id, name, qualified_name,
               start_line, start_col, end_line, end_col, is_partial)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [(file_id, *row) for row in rows]
        )

    def insert_variables(self, rows: list[tuple], file_id: int) -> None:
        self._conn.executemany(
            """INSERT INTO variables (file_id, name, qualified_name,
               start_line, start_col, end_line, end_col, is_partial)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [(file_id, *row) for row in rows]
        )

    def delete_by_file(self, table: str, file_id: int) -> None:
        self._conn.execute(
            f"DELETE FROM {validate_table_name(table)} WHERE file_id = ?", (file_id,)  # nosec B608
        )


class EdgeRepo:
    """关系边表 CRUD + 图遍历查询。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert_batch(self, rows: list[tuple]) -> None:
        self._conn.executemany(
            """INSERT INTO edges
               (source, target, kind, source_file_id,
                source_start_line, source_start_col, source_end_line, source_end_col,
                target_file_id, target_start_line, target_start_col, target_end_line, target_end_col)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows
        )

    def delete_by_source_file(self, file_id: int) -> None:
        self._conn.execute(
            "DELETE FROM edges WHERE source_file_id = ?", (file_id,)
        )

    def get_callers(self, qualified_name: str, depth: int = 1,
                    file_path: str | None = None) -> list[dict]:
        """Return the call graph upstream from *qualified_name*."""
        return self._graph_walk(qualified_name, depth, file_path, "up")

    def get_callees(self, qualified_name: str, depth: int = 1,
                    file_path: str | None = None) -> list[dict]:
        """Return the call graph downstream from *qualified_name*."""
        return self._graph_walk(qualified_name, depth, file_path, "down")

    def _graph_walk(self, qualified_name: str, depth: int,
                    file_path: str | None, direction: str) -> list[dict]:
        """Unified recursive CTE traversal for callers/callees.

        Args:
            direction: ``"up"`` for callers (walk from target to source),
                       ``"down"`` for callees (walk from source to target).
        """
        is_up = direction == "up"
        anchor_col = "target" if is_up else "source"
        join_on = ("e.target = cc.source" if is_up
                   else "e.source = cc.target")
        file_col = f"{'target' if is_up else 'source'}_file_id"

        short_name = qualified_name.split(".")[-1] if "." in qualified_name else None
        params: tuple = ()
        if file_path:
            if short_name:
                sql = (
                    f"WITH RECURSIVE chain AS ("  # nosec B608
                    f"  SELECT e.source, e.target, e.kind, 1 AS depth"
                    f"  FROM edges e"
                    f"  JOIN files f ON f.id = e.{file_col}"
                    f"  WHERE (e.{anchor_col} = ? OR e.{anchor_col} = ?"
                    f"    OR e.{anchor_col} LIKE '%.' || ?)"
                    f"    AND e.kind = 'calls' AND f.path = ?"
                    f"  UNION ALL"
                    f"  SELECT e.source, e.target, e.kind, cc.depth + 1"
                    f"  FROM edges e"
                    f"  JOIN chain cc ON {join_on}"
                    f"  WHERE e.kind = 'calls' AND cc.depth < ?"
                    f")"
                    f" SELECT DISTINCT source, target, depth FROM chain ORDER BY depth"
                )
                params = (qualified_name, short_name, short_name, file_path, depth)
            else:
                sql = (
                    f"WITH RECURSIVE chain AS ("  # nosec B608
                    f"  SELECT e.source, e.target, e.kind, 1 AS depth"
                    f"  FROM edges e"
                    f"  JOIN files f ON f.id = e.{file_col}"
                    f"  WHERE e.{anchor_col} = ? AND e.kind = 'calls' AND f.path = ?"
                    f"  UNION ALL"
                    f"  SELECT e.source, e.target, e.kind, cc.depth + 1"
                    f"  FROM edges e"
                    f"  JOIN chain cc ON {join_on}"
                    f"  WHERE e.kind = 'calls' AND cc.depth < ?"
                    f")"
                    f" SELECT DISTINCT source, target, depth FROM chain ORDER BY depth"
                )
                params = (qualified_name, file_path, depth)
        elif short_name:
            sql = (
                f"WITH RECURSIVE chain AS ("  # nosec B608
                f"  SELECT source, target, kind, 1 AS depth"
                f"  FROM edges"
                f"  WHERE ({anchor_col} = ? OR {anchor_col} = ?"
                f"    OR {anchor_col} LIKE '%.' || ?) AND kind = 'calls'"
                f"  UNION ALL"
                f"  SELECT e.source, e.target, e.kind, cc.depth + 1"
                f"  FROM edges e"
                f"  JOIN chain cc ON {join_on}"
                f"  WHERE e.kind = 'calls' AND cc.depth < ?"
                f")"
                f" SELECT DISTINCT source, target, depth FROM chain ORDER BY depth"
            )
            params = (qualified_name, short_name, short_name, depth)
        else:
            sql = (
                f"WITH RECURSIVE chain AS ("  # nosec B608
                f"  SELECT source, target, kind, 1 AS depth"
                f"  FROM edges"
                f"  WHERE {anchor_col} = ? AND kind = 'calls'"
                f"  UNION ALL"
                f"  SELECT e.source, e.target, e.kind, cc.depth + 1"
                f"  FROM edges e"
                f"  JOIN chain cc ON {join_on}"
                f"  WHERE e.kind = 'calls' AND cc.depth < ?"
                f")"
                f" SELECT DISTINCT source, target, depth FROM chain ORDER BY depth"
            )
            params = (qualified_name, depth)

        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


class FTSRepo:
    """FTS5 全文检索。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert_batch(self, rows: list[tuple]) -> None:
        """Batch insert FTS rows for performance."""
        self._conn.executemany(
            """INSERT INTO fts_index (symbol_name, qualified_name, signature, file_path, kind)
               VALUES (?, ?, ?, ?, ?)""",
            rows
        )

    def delete_by_file(self, file_path: str) -> None:
        self._conn.execute(
            "DELETE FROM fts_index WHERE file_path = ?", (file_path,)
        )

    def search(self, query: str, limit: int = 20,
               file_path: str | None = None) -> list[dict]:
        """Full-text search with FTS5 rank + name match quality boost.

        Scoring tiers (lower score = better):
          1. FTS5 rank (BM25, lower is more relevant)
          2. Name match bonus: exact(-1000) > prefix(-500) > partial(-200)
          3. Kind priority: class/interface(0) > function/method(+50) > other(+100)

        Args:
            query: FTS5 search query.
            limit: Max results to return.
            file_path: Optional file path filter (exact match).
        """
        # Fetch more results than needed for re-ranking
        fetch_limit = max(limit * 3, 60)
        if file_path:
            rows = self._conn.execute(
                """SELECT symbol_name, qualified_name, signature, file_path, kind, rank
                   FROM fts_index
                   WHERE fts_index MATCH ? AND file_path = ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, file_path, fetch_limit)
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT symbol_name, qualified_name, signature, file_path, kind, rank
                   FROM fts_index
                   WHERE fts_index MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, fetch_limit)
            ).fetchall()
        results = [dict(r) for r in rows]
        if not results:
            return []

        return _rank_search_results(results, query)[:limit]
