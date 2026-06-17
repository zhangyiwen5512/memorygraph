"""Semantic data repository — abstract base + PostgreSQL implementation.

Replaces the JSON-file semantic store with per-annotation PG rows.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class AbstractSemanticRepository(ABC):
    """Interface for semantic data persistence (annotations, unknowns, insights, modules)."""

    # -- Annotations --

    @abstractmethod
    def upsert_annotation(
        self,
        file_path: str,
        symbol: str,
        kind: str = "unknown",
        summary: str = "",
        design_intent: str = "",
        pitfalls: str = "",
        source: str = "manual",
    ) -> None:
        """Insert or update a per-symbol annotation."""

    @abstractmethod
    def get_annotation(self, file_path: str, symbol: str) -> dict | None:
        """Get a single annotation. Returns None if not found."""

    @abstractmethod
    def get_annotations_for_file(self, file_path: str) -> list[dict]:
        """Get all annotations for a file."""

    @abstractmethod
    def delete_annotation(self, file_path: str, symbol: str) -> bool:
        """Delete a single annotation. Returns True if deleted."""

    @abstractmethod
    def count_annotated_symbols(self) -> int:
        """Count distinct annotated symbols across all files."""

    @abstractmethod
    def load_all_annotations(self) -> list[dict]:
        """Load all annotations (for bulk enrichment)."""

    # -- Unknowns --

    @abstractmethod
    def upsert_unknown(
        self,
        file_path: str,
        symbol: str,
        question: str,
        context: str = "",
        source: str = "manual",
    ) -> None:
        """Insert an unknown (open question) for a symbol."""

    @abstractmethod
    def get_unknowns_for_file(self, file_path: str) -> list[dict]:
        """Get all unknowns for a file."""

    @abstractmethod
    def load_all_unknowns(self) -> list[dict]:
        """Load all unknowns."""

    # -- Insights --

    @abstractmethod
    def upsert_insight(
        self,
        file_path: str,
        insight: str,
        related_symbols: list[str] | None = None,
        source: str = "manual",
    ) -> None:
        """Insert a design insight for a file."""

    @abstractmethod
    def get_insights_for_file(self, file_path: str) -> list[dict]:
        """Get all insights for a file."""

    @abstractmethod
    def load_all_insights(self) -> list[dict]:
        """Load all insights."""

    # -- Module --

    @abstractmethod
    def upsert_module(
        self,
        file_path: str,
        module_summary: str = "",
        module_roles: dict | None = None,
        metrics: dict | None = None,
        odors: list | None = None,
        source: str = "manual",
    ) -> None:
        """Insert or update module-level metadata."""

    @abstractmethod
    def get_module(self, file_path: str) -> dict | None:
        """Get module metadata for a file. Returns None if not found."""

    @abstractmethod
    def load_all_modules(self) -> list[dict]:
        """Load all module metadata (for coverage/enrichment)."""

    # -- Bulk --

    @abstractmethod
    def list_documented_files(self) -> set[str]:
        """Return set of file paths that have any semantic data."""

    @abstractmethod
    def remove_all_for_file(self, file_path: str) -> None:
        """Remove all semantic data for a file (orphan cleanup)."""


class PgSemanticRepository(AbstractSemanticRepository):
    """PostgreSQL-backed semantic data persistence.

    Uses the same connection pool and schema as the main PG storage manager.
    """

    def __init__(self, pool: Any, schema: str) -> None:
        """Initialize with a psycopg2 ThreadedConnectionPool and schema name.

        Args:
            pool: A ``psycopg2.pool.ThreadedConnectionPool`` instance.
            schema: The PostgreSQL schema name for this project.
        """
        self._pool = pool
        self._schema = schema

    def _execute(self, sql: str, params: tuple | None = None) -> None:
        """Execute a write statement (INSERT/UPDATE/DELETE)."""
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()
        finally:
            self._pool.putconn(conn)

    def _fetch_all(self, sql: str, params: tuple | None = None) -> list[dict]:
        """Execute a read query and return all rows as dicts."""
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                columns = [desc[0] for desc in cur.description] if cur.description else []
                rows = cur.fetchall()
                return [dict(zip(columns, row, strict=True)) for row in rows]
        finally:
            self._pool.putconn(conn)

    def _fetch_one(self, sql: str, params: tuple | None = None) -> dict | None:
        """Execute a read query and return the first row as a dict, or None."""
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if cur.description is None:
                    return None
                columns = [desc[0] for desc in cur.description]
                row = cur.fetchone()
                return dict(zip(columns, row, strict=True)) if row else None
        finally:
            self._pool.putconn(conn)

    # -- Annotations --

    def upsert_annotation(
        self,
        file_path: str,
        symbol: str,
        kind: str = "unknown",
        summary: str = "",
        design_intent: str = "",
        pitfalls: str = "",
        source: str = "manual",
    ) -> None:
        self._execute(
            f"""INSERT INTO {self._schema}.semantic_annotations
                (file_path, symbol, kind, summary, design_intent, pitfalls, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (file_path, symbol) DO UPDATE SET
                kind = EXCLUDED.kind,
                summary = EXCLUDED.summary,
                design_intent = EXCLUDED.design_intent,
                pitfalls = EXCLUDED.pitfalls,
                source = EXCLUDED.source,
                updated_at = NOW()""",
            (file_path, symbol, kind, summary, design_intent, pitfalls, source),
        )

    def get_annotation(self, file_path: str, symbol: str) -> dict | None:
        return self._fetch_one(
            f"SELECT * FROM {self._schema}.semantic_annotations WHERE file_path = %s AND symbol = %s",
            (file_path, symbol),
        )

    def get_annotations_for_file(self, file_path: str) -> list[dict]:
        return self._fetch_all(
            f"SELECT * FROM {self._schema}.semantic_annotations WHERE file_path = %s ORDER BY symbol",
            (file_path,),
        )

    def delete_annotation(self, file_path: str, symbol: str) -> bool:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self._schema}.semantic_annotations WHERE file_path = %s AND symbol = %s",
                    (file_path, symbol),
                )
                deleted = cur.rowcount > 0
            conn.commit()
            return deleted
        finally:
            self._pool.putconn(conn)

    def count_annotated_symbols(self) -> int:
        result = self._fetch_one(
            f"SELECT COUNT(*) as cnt FROM {self._schema}.semantic_annotations"
        )
        return result["cnt"] if result else 0

    def load_all_annotations(self) -> list[dict]:
        return self._fetch_all(
            f"SELECT * FROM {self._schema}.semantic_annotations ORDER BY file_path, symbol"
        )

    # -- Unknowns --

    def upsert_unknown(
        self,
        file_path: str,
        symbol: str,
        question: str,
        context: str = "",
        source: str = "manual",
    ) -> None:
        self._execute(
            f"""INSERT INTO {self._schema}.semantic_unknowns
                (file_path, symbol, question, context, source)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (file_path, symbol, question) DO NOTHING""",
            (file_path, symbol, question, context, source),
        )

    def get_unknowns_for_file(self, file_path: str) -> list[dict]:
        return self._fetch_all(
            f"SELECT * FROM {self._schema}.semantic_unknowns WHERE file_path = %s ORDER BY symbol",
            (file_path,),
        )

    def load_all_unknowns(self) -> list[dict]:
        return self._fetch_all(
            f"SELECT * FROM {self._schema}.semantic_unknowns ORDER BY file_path, symbol"
        )

    # -- Insights --

    def upsert_insight(
        self,
        file_path: str,
        insight: str,
        related_symbols: list[str] | None = None,
        source: str = "manual",
    ) -> None:
        self._execute(
            f"""INSERT INTO {self._schema}.semantic_insights
                (file_path, insight, related_symbols, source)
                VALUES (%s, %s, %s, %s)""",
            (file_path, insight, related_symbols or [], source),
        )

    def get_insights_for_file(self, file_path: str) -> list[dict]:
        return self._fetch_all(
            f"SELECT * FROM {self._schema}.semantic_insights WHERE file_path = %s ORDER BY id",
            (file_path,),
        )

    def load_all_insights(self) -> list[dict]:
        return self._fetch_all(
            f"SELECT * FROM {self._schema}.semantic_insights ORDER BY file_path, id"
        )

    # -- Module --

    def upsert_module(
        self,
        file_path: str,
        module_summary: str = "",
        module_roles: dict | None = None,
        metrics: dict | None = None,
        odors: list | None = None,
        source: str = "manual",
    ) -> None:
        import json

        self._execute(
            f"""INSERT INTO {self._schema}.semantic_modules
                (file_path, module_summary, module_roles, metrics, odors, source)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (file_path) DO UPDATE SET
                module_summary = EXCLUDED.module_summary,
                module_roles = EXCLUDED.module_roles,
                metrics = EXCLUDED.metrics,
                odors = EXCLUDED.odors,
                source = EXCLUDED.source,
                updated_at = NOW()""",
            (
                file_path,
                module_summary,
                json.dumps(module_roles or {}),
                json.dumps(metrics or {}),
                json.dumps(odors or []),
                source,
            ),
        )

    def get_module(self, file_path: str) -> dict | None:
        return self._fetch_one(
            f"SELECT * FROM {self._schema}.semantic_modules WHERE file_path = %s",
            (file_path,),
        )

    def load_all_modules(self) -> list[dict]:
        return self._fetch_all(
            f"SELECT * FROM {self._schema}.semantic_modules ORDER BY file_path"
        )

    # -- Bulk --

    def list_documented_files(self) -> set[str]:
        files: set[str] = set()
        for table in ("semantic_annotations", "semantic_unknowns", "semantic_insights", "semantic_modules"):
            rows = self._fetch_all(
                f"SELECT DISTINCT file_path FROM {self._schema}.{table}"
            )
            files.update(r["file_path"] for r in rows)
        # Also include modules with module_summary
        mods = self._fetch_all(
            f"SELECT file_path FROM {self._schema}.semantic_modules WHERE module_summary != ''"
        )
        files.update(r["file_path"] for r in mods)
        return files

    def remove_all_for_file(self, file_path: str) -> None:
        """Remove all semantic data for a file."""
        for table in ("semantic_annotations", "semantic_unknowns", "semantic_insights", "semantic_modules"):
            self._execute(
                f"DELETE FROM {self._schema}.{table} WHERE file_path = %s",
                (file_path,),
            )
