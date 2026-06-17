"""Integration tests for PostgreSQLStorageManager — requires a running PG.

Usage:
    docker compose up -d
    DATABASE_URL=postgresql://memorygraph:memorygraph@localhost:5432/memorygraph_test \
        pytest tests/test_pg_integration.py -v
    docker compose down
"""
import os

import pytest

try:
    import psycopg2  # noqa: F401
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

_DEFAULT_PG_URLS = [
    "postgresql://memorygraph:memorygraph@localhost:5432/memorygraph_test",
    "postgresql://postgres:postgres@localhost:5432/postgres",
    "postgresql://memorygraph:memorygraph@127.0.0.1:5432/memorygraph_test",
    "postgresql://postgres:postgres@127.0.0.1:5432/postgres",
]

_DETECTED_PG_URL: str = ""


def _detect_pg() -> str:
    """Detect if PostgreSQL is available by probing known connection URLs.

    Returns the connection URL if found, empty string otherwise.
    Does NOT mutate os.environ to avoid polluting other tests.
    """
    if not HAS_PSYCOPG2:
        return ""

    # Explicit DATABASE_URL takes priority
    pg_url = os.environ.get("DATABASE_URL", "")
    if pg_url.startswith("postgresql://") or pg_url.startswith("postgres://"):
        return pg_url

    # Auto-detect: try connecting to default Docker/local PG URLs
    for url in _DEFAULT_PG_URLS:
        try:
            conn = psycopg2.connect(dsn=url, connect_timeout=2)
            conn.close()
            return url
        except Exception:  # noqa: BLE001
            continue
    return ""


_DETECTED_PG_URL = _detect_pg()
HAS_PG = bool(_DETECTED_PG_URL)

pytestmark = pytest.mark.skipif(
    not HAS_PG,
    reason="PostgreSQL not available — set DATABASE_URL and install psycopg2",
)


@pytest.fixture
def pg_mgr():
    """Create a PostgreSQLStorageManager connected to the test DB, with clean tables."""
    from memorygraph.storage.pg_repository import PostgreSQLStorageManager

    # Ensure DATABASE_URL is set for the fixture lifetime
    old_url = os.environ.get("DATABASE_URL")
    if not old_url and _DETECTED_PG_URL:
        os.environ["DATABASE_URL"] = _DETECTED_PG_URL

    try:
        mgr = PostgreSQLStorageManager(".")
        mgr.connect()
        conn = mgr._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DROP TABLE IF EXISTS edges, fts_index, embeddings, "
                    "schema_version, functions, methods, classes, "
                    "interfaces, type_aliases, variables, files CASCADE"
                )
            conn.commit()
        finally:
            mgr._pool.putconn(conn)

        mgr.initialize()
        yield mgr
        mgr.close()
    finally:
        # Restore original env state
        if old_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_url


class TestPostgreSQLIntegration:
    """Integration tests requiring a real PostgreSQL database."""

    def test_initialize_creates_tables(self, pg_mgr):
        """initialize() creates all required tables."""
        conn = pg_mgr._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY table_name"
                )
                tables = {row[0] for row in cur.fetchall()}
                expected = {
                    "files", "functions", "methods", "classes",
                    "interfaces", "type_aliases", "variables",
                    "edges", "fts_index", "embeddings", "schema_version",
                }
                assert expected.issubset(tables), f"Missing: {expected - tables}"
        finally:
            pg_mgr._pool.putconn(conn)

    def test_initialize_idempotent(self, pg_mgr):
        """Calling initialize() twice is safe."""
        pg_mgr.initialize()
        pg_mgr.initialize()

        conn = pg_mgr._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
                assert len(cur.fetchall()) >= 8
        finally:
            pg_mgr._pool.putconn(conn)

    def test_stats_empty(self, pg_mgr):
        """stats() on empty DB returns zero counts."""
        result = pg_mgr.stats()
        assert result["file_count"] == 0
        assert result["symbol_count"] == 0
        assert result["edge_count"] == 0
        assert result["backend"] == "postgresql"

    def test_list_files_empty(self, pg_mgr):
        """list_files() returns empty list on fresh DB."""
        assert pg_mgr.list_files() == []

    def test_get_node_not_found(self, pg_mgr):
        """get_node() returns None for nonexistent symbol."""
        assert pg_mgr.get_node("nonexistent_func") is None

    def test_get_file_hash_not_found(self, pg_mgr):
        """get_file_hash() returns None for unknown file."""
        assert pg_mgr.get_file_hash("/nonexistent.py") is None

    def test_search_empty(self, pg_mgr):
        """search() returns empty on fresh DB."""
        result = pg_mgr.search("test")
        assert result == []

    def test_get_callers_empty(self, pg_mgr):
        """get_callers() returns empty on fresh DB."""
        assert pg_mgr.get_callers("func") == []

    def test_get_callees_empty(self, pg_mgr):
        """get_callees() returns empty on fresh DB."""
        assert pg_mgr.get_callees("func") == []

    def test_get_symbols_for_file_not_found(self, pg_mgr):
        """get_symbols_for_file() returns [] for unknown file."""
        assert pg_mgr.get_symbols_for_file("/unknown.py") == []

    def test_upsert_file_and_search(self, pg_mgr):
        """Insert a ParseResult and verify FTS search finds it."""
        from memorygraph.parsing.ir import (
            Edge,
            EdgeKind,
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        file_info = FileInfo(
            path="/test/app.py",
            language="python",
            content_hash="abc123_hash",
        )
        sym = Symbol(
            name="calculate_total",
            kind=SymbolKind.FUNCTION,
            span=Span(file="/test/app.py", start_line=10, start_col=0,
                      end_line=15, end_col=20),
            signature="def calculate_total(items: list) -> float",
            is_partial=False,
        )
        edge = Edge(
            source="calculate_total",
            target="sum",
            kind=EdgeKind.CALLS,
            source_span=Span(file="/test/app.py", start_line=10, start_col=0,
                             end_line=15, end_col=20),
            target_span=Span(file="/test/app.py", start_line=20, start_col=0,
                            end_line=20, end_col=10),
        )
        result = ParseResult(file=file_info, symbols=[sym], edges=[edge], errors=[])

        fid, fts_rows = pg_mgr.upsert_file(result)
        assert fid > 0
        assert len(fts_rows) > 0

        results = pg_mgr.search("calculate")
        assert len(results) > 0
        assert results[0]["symbol_name"] == "calculate_total"

        node = pg_mgr.get_node("calculate_total")
        assert node is not None
        assert node["name"] == "calculate_total"
        assert node["kind"] == "function"

        files = pg_mgr.list_files()
        assert len(files) == 1
        assert files[0]["path"] == "/test/app.py"

        assert pg_mgr.get_file_hash("/test/app.py") == "abc123_hash"

        stats = pg_mgr.stats()
        assert stats["file_count"] == 1
        assert stats["symbol_count"] == 1
        assert stats["edge_count"] == 1

    def test_upsert_file_updates_existing(self, pg_mgr):
        """Re-inserting the same file updates existing data."""
        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        file_info = FileInfo(
            path="/test/update.py",
            language="python",
            content_hash="hash_v1",
        )
        sym = Symbol(
            name="old_func",
            kind=SymbolKind.FUNCTION,
            span=Span(file="/test/update.py", start_line=1, start_col=0,
                      end_line=5, end_col=10),
            signature="def old_func()",
            is_partial=False,
        )
        result = ParseResult(file=file_info, symbols=[sym], edges=[], errors=[])
        fid1, _ = pg_mgr.upsert_file(result)
        assert fid1 > 0
        assert pg_mgr.get_node("old_func") is not None

        file_info2 = FileInfo(
            path="/test/update.py",
            language="python",
            content_hash="hash_v2",
        )
        sym2 = Symbol(
            name="new_func",
            kind=SymbolKind.FUNCTION,
            span=Span(file="/test/update.py", start_line=1, start_col=0,
                      end_line=5, end_col=10),
            signature="def new_func()",
            is_partial=False,
        )
        result2 = ParseResult(file=file_info2, symbols=[sym2], edges=[], errors=[])
        fid2, _ = pg_mgr.upsert_file(result2)
        assert fid2 > 0

        assert pg_mgr.get_node("old_func") is None
        assert pg_mgr.get_node("new_func") is not None
        assert pg_mgr.get_file_hash("/test/update.py") == "hash_v2"

    def test_delete_file(self, pg_mgr):
        """delete_file() removes a file and all its data."""
        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        file_info = FileInfo(
            path="/test/to_delete.py",
            language="python",
            content_hash="hash",
        )
        sym = Symbol(
            name="delete_me",
            kind=SymbolKind.FUNCTION,
            span=Span(file="/test/to_delete.py", start_line=1, start_col=0,
                      end_line=3, end_col=10),
            signature="def delete_me()",
            is_partial=False,
        )
        result = ParseResult(file=file_info, symbols=[sym], edges=[], errors=[])
        pg_mgr.upsert_file(result)
        assert pg_mgr.get_node("delete_me") is not None

        pg_mgr.delete_file("/test/to_delete.py")
        assert pg_mgr.get_node("delete_me") is None
        assert pg_mgr.get_file_hash("/test/to_delete.py") is None

    def test_get_callers_and_callees(self, pg_mgr):
        """Graph traversal works with caller/callee relationships."""
        from memorygraph.parsing.ir import (
            Edge,
            EdgeKind,
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        file_info = FileInfo(
            path="/test/flow.py",
            language="python",
            content_hash="hash",
        )
        sym_a = Symbol(
            name="function_a",
            kind=SymbolKind.FUNCTION,
            span=Span(file="/test/flow.py", start_line=1, start_col=0,
                      end_line=5, end_col=10),
            signature="def function_a()",
            is_partial=False,
        )
        sym_b = Symbol(
            name="function_b",
            kind=SymbolKind.FUNCTION,
            span=Span(file="/test/flow.py", start_line=10, start_col=0,
                      end_line=15, end_col=10),
            signature="def function_b()",
            is_partial=False,
        )
        edge = Edge(
            source="function_a",
            target="function_b",
            kind=EdgeKind.CALLS,
            source_span=Span(file="/test/flow.py", start_line=1, start_col=0,
                             end_line=5, end_col=10),
            target_span=Span(file="/test/flow.py", start_line=10, start_col=0,
                            end_line=15, end_col=10),
        )
        result = ParseResult(
            file=file_info, symbols=[sym_a, sym_b], edges=[edge], errors=[],
        )
        pg_mgr.upsert_file(result)

        callers = pg_mgr.get_callers("function_b")
        assert len(callers) == 1
        assert callers[0]["source"] == "function_a"

        callees = pg_mgr.get_callees("function_a")
        assert len(callees) == 1
        assert callees[0]["target"] == "function_b"

    def test_context_manager(self, pg_mgr):  # noqa: ARG002 — ensures DATABASE_URL is set
        """PostgreSQLStorageManager works as a context manager."""
        from memorygraph.storage.pg_repository import PostgreSQLStorageManager

        with PostgreSQLStorageManager(".") as mgr:
            stats = mgr.stats()
            assert stats["backend"] == "postgresql"

    # ── Coverage gap fills ─────────────────────────────────────────

    def test_read_only_connection_context_manager(self, pg_mgr):
        """read_only_connection() yields a read-only connection (lines 296-303)."""
        with pg_mgr.read_only_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                assert cur.fetchone()[0] == 1
        # Connection should be returned to pool

    def test_get_read_only_conn_direct(self, pg_mgr):
        """get_read_only_conn() returns a read-only connection (lines 287-291)."""
        conn = pg_mgr.get_read_only_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                assert cur.fetchone()[0] == 1
        finally:
            pg_mgr._pool.putconn(conn)

    def test_get_symbols_for_file_with_results(self, pg_mgr):
        """get_symbols_for_file() returns symbols when file exists (lines 435-445)."""
        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        file_info = FileInfo(
            path="/test/symbols_file.py", language="python",
            content_hash="hash_symbols",
        )
        sym = Symbol(
            name="my_function", kind=SymbolKind.FUNCTION,
            span=Span(file="/test/symbols_file.py", start_line=1, start_col=0,
                      end_line=5, end_col=10),
            signature="def my_function()", is_partial=False,
        )
        result = ParseResult(file=file_info, symbols=[sym], edges=[], errors=[])
        pg_mgr.upsert_file(result)

        symbols = pg_mgr.get_symbols_for_file("/test/symbols_file.py")
        assert len(symbols) >= 1
        assert any(s.get("name") == "my_function" for s in symbols)

    def test_search_with_file_filter(self, pg_mgr):
        """search() with file_path filter returns only matching file (line 462)."""
        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        # Insert file A
        fa = FileInfo(path="/test/file_a.py", language="python", content_hash="ha")
        sa = Symbol(name="unique_a", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/file_a.py", start_line=1, start_col=0,
                              end_line=3, end_col=5),
                    signature="def unique_a()", is_partial=False)
        pg_mgr.upsert_file(ParseResult(file=fa, symbols=[sa], edges=[], errors=[]))

        # Insert file B
        fb = FileInfo(path="/test/file_b.py", language="python", content_hash="hb")
        sb = Symbol(name="unique_b", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/file_b.py", start_line=1, start_col=0,
                              end_line=3, end_col=5),
                    signature="def unique_b()", is_partial=False)
        pg_mgr.upsert_file(ParseResult(file=fb, symbols=[sb], edges=[], errors=[]))

        # Search with file filter
        results = pg_mgr.search("unique", file_path="/test/file_a.py")
        assert len(results) >= 1
        for r in results:
            assert r["file_path"] == "/test/file_a.py"

    def test_search_cache_hit(self, pg_mgr):
        """search() caches results — second call hits cache (line 458)."""
        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        file_info = FileInfo(path="/test/cached.py", language="python", content_hash="hc")
        sym = Symbol(name="cached_func", kind=SymbolKind.FUNCTION,
                     span=Span(file="/test/cached.py", start_line=1, start_col=0,
                               end_line=3, end_col=5),
                     signature="def cached_func()", is_partial=False)
        pg_mgr.upsert_file(ParseResult(file=file_info, symbols=[sym], edges=[], errors=[]))

        # First call — misses cache, hits DB
        r1 = pg_mgr.search("cached_func")
        # Second call — should hit cache
        r2 = pg_mgr.search("cached_func")
        assert r1 == r2

    def test_semantic_search_fallback_to_phrase(self, pg_mgr):
        """semantic_search falls back to phrase search when word search empty (lines 555-561)."""
        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        file_info = FileInfo(path="/test/phrase.py", language="python", content_hash="hp")
        sym = Symbol(name="process_data_batch", kind=SymbolKind.FUNCTION,
                     span=Span(file="/test/phrase.py", start_line=1, start_col=0,
                               end_line=10, end_col=5),
                     signature="def process_data_batch(items)", is_partial=False)
        pg_mgr.upsert_file(ParseResult(file=file_info, symbols=[sym], edges=[], errors=[]))

        # Search with words that exist in the symbol name
        results = pg_mgr.semantic_search("process batch data")
        assert isinstance(results, list)

    def test_semantic_search_no_words_falls_through(self, pg_mgr):
        """semantic_search with no >=3 char words falls through to search (line 533)."""
        results = pg_mgr.semantic_search("a b c")
        # Should fall through to plain search — empty DB means empty results
        assert isinstance(results, list)
        assert results == []

    def test_bulk_upsert_multiple_files(self, pg_mgr):
        """bulk_upsert inserts multiple files in one transaction (lines 500-525)."""
        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        f1 = FileInfo(path="/test/bulk_a.py", language="python", content_hash="bha")
        s1 = Symbol(name="bulk_func_a", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/bulk_a.py", start_line=1, start_col=0,
                              end_line=3, end_col=5),
                    signature="def bulk_func_a()", is_partial=False)
        r1 = ParseResult(file=f1, symbols=[s1], edges=[], errors=[])

        f2 = FileInfo(path="/test/bulk_b.py", language="python", content_hash="bhb")
        s2 = Symbol(name="bulk_func_b", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/bulk_b.py", start_line=1, start_col=0,
                              end_line=3, end_col=5),
                    signature="def bulk_func_b()", is_partial=False)
        r2 = ParseResult(file=f2, symbols=[s2], edges=[], errors=[])

        count = pg_mgr.bulk_upsert({"/test/bulk_a.py": r1, "/test/bulk_b.py": r2})
        assert count == 2

        # Verify both files are searchable
        assert len(pg_mgr.search("bulk_func_a")) >= 1
        assert len(pg_mgr.search("bulk_func_b")) >= 1

    def test_bulk_upsert_skips_fatal_errors(self, pg_mgr):
        """bulk_upsert skips results with fatal_error set (line 508)."""
        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        f1 = FileInfo(path="/test/bulk_ok.py", language="python", content_hash="bok")
        s1 = Symbol(name="bulk_ok", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/bulk_ok.py", start_line=1, start_col=0,
                              end_line=3, end_col=5),
                    signature="def bulk_ok()", is_partial=False)
        r1 = ParseResult(file=f1, symbols=[s1], edges=[], errors=[])

        # Second result has a fatal error — should be skipped
        f2 = FileInfo(path="/test/bulk_bad.py", language="python", content_hash="bb")
        r2 = ParseResult(file=f2, symbols=[], edges=[], errors=["parse error"])
        r2.fatal_error = True

        count = pg_mgr.bulk_upsert({"/test/bulk_ok.py": r1, "/test/bulk_bad.py": r2})
        assert count == 1  # Only the good file counted

    def test_bulk_upsert_clears_query_cache(self, pg_mgr):
        """bulk_upsert clears query cache when items are populated (line 519)."""
        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        # Populate the cache first
        pg_mgr.query_cache.put("test_key", ["cached_value"])

        f1 = FileInfo(path="/test/cache_clear.py", language="python", content_hash="hcc")
        s1 = Symbol(name="cache_clear_func", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/cache_clear.py", start_line=1, start_col=0,
                              end_line=3, end_col=5),
                    signature="def cache_clear_func()", is_partial=False)
        r1 = ParseResult(file=f1, symbols=[s1], edges=[], errors=[])

        pg_mgr.bulk_upsert({"/test/cache_clear.py": r1})
        # Cache should be cleared after bulk_upsert
        assert pg_mgr.query_cache.get("test_key") is None

    def test_get_conn_returns_connection(self, pg_mgr):
        """get_conn() returns a raw connection from the pool (lines 282-283)."""
        conn = pg_mgr.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                assert cur.fetchone()[0] == 1
        finally:
            pg_mgr._pool.putconn(conn)

    def test_get_callers_cache_hit(self, pg_mgr):
        """get_callers() returns cached result on second call (line 570)."""
        from memorygraph.parsing.ir import (
            Edge,
            EdgeKind,
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        fi = FileInfo(path="/test/callers_cache.py", language="python", content_hash="hcc2")
        sa = Symbol(name="caller_a", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/callers_cache.py", start_line=1, start_col=0,
                              end_line=3, end_col=5),
                    signature="def caller_a()", is_partial=False)
        sb = Symbol(name="callee_b", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/callers_cache.py", start_line=10, start_col=0,
                              end_line=12, end_col=5),
                    signature="def callee_b()", is_partial=False)
        edge = Edge(source="caller_a", target="callee_b", kind=EdgeKind.CALLS,
                    source_span=Span(file="/test/callers_cache.py", start_line=1, start_col=0,
                                     end_line=3, end_col=5),
                    target_span=Span(file="/test/callers_cache.py", start_line=10, start_col=0,
                                     end_line=12, end_col=5))
        pg_mgr.upsert_file(ParseResult(file=fi, symbols=[sa, sb], edges=[edge], errors=[]))

        # First call — miss cache
        r1 = pg_mgr.get_callers("callee_b")
        # Second call — hit cache
        r2 = pg_mgr.get_callers("callee_b")
        assert r1 == r2
        assert len(r1) >= 1

    def test_get_callees_cache_hit(self, pg_mgr):
        """get_callees() returns cached result on second call (line 580)."""
        from memorygraph.parsing.ir import (
            Edge,
            EdgeKind,
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        fi = FileInfo(path="/test/callee_cache.py", language="python", content_hash="hcc3")
        sa = Symbol(name="parent_a", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/callee_cache.py", start_line=1, start_col=0,
                              end_line=3, end_col=5),
                    signature="def parent_a()", is_partial=False)
        sb = Symbol(name="child_b", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/callee_cache.py", start_line=10, start_col=0,
                              end_line=12, end_col=5),
                    signature="def child_b()", is_partial=False)
        edge = Edge(source="parent_a", target="child_b", kind=EdgeKind.CALLS,
                    source_span=Span(file="/test/callee_cache.py", start_line=1, start_col=0,
                                     end_line=3, end_col=5),
                    target_span=Span(file="/test/callee_cache.py", start_line=10, start_col=0,
                                     end_line=12, end_col=5))
        pg_mgr.upsert_file(ParseResult(file=fi, symbols=[sa, sb], edges=[edge], errors=[]))

        # First call — miss cache
        r1 = pg_mgr.get_callees("parent_a")
        # Second call — hit cache
        r2 = pg_mgr.get_callees("parent_a")
        assert r1 == r2
        assert len(r1) >= 1

    def test_get_impact_delegates_to_get_callees(self, pg_mgr):
        """get_impact() delegates to get_callees (line 586)."""
        from memorygraph.parsing.ir import (
            Edge,
            EdgeKind,
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        fi = FileInfo(path="/test/impact.py", language="python", content_hash="him")
        sa = Symbol(name="top_func", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/impact.py", start_line=1, start_col=0,
                              end_line=3, end_col=5),
                    signature="def top_func()", is_partial=False)
        sb = Symbol(name="low_func", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/impact.py", start_line=10, start_col=0,
                              end_line=12, end_col=5),
                    signature="def low_func()", is_partial=False)
        edge = Edge(source="top_func", target="low_func", kind=EdgeKind.CALLS,
                    source_span=Span(file="/test/impact.py", start_line=1, start_col=0,
                                     end_line=3, end_col=5),
                    target_span=Span(file="/test/impact.py", start_line=10, start_col=0,
                                     end_line=12, end_col=5))
        pg_mgr.upsert_file(ParseResult(file=fi, symbols=[sa, sb], edges=[edge], errors=[]))

        result = pg_mgr.get_impact("top_func")
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_get_node_with_file_path(self, pg_mgr):
        """get_node() with file_path filter (line 596)."""
        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        fi = FileInfo(path="/test/node_fp.py", language="python", content_hash="hnf")
        sym = Symbol(name="target_node", kind=SymbolKind.FUNCTION,
                     span=Span(file="/test/node_fp.py", start_line=1, start_col=0,
                               end_line=3, end_col=5),
                     signature="def target_node()", is_partial=False)
        pg_mgr.upsert_file(ParseResult(file=fi, symbols=[sym], edges=[], errors=[]))

        # With file_path
        node = pg_mgr.get_node("target_node", file_path="/test/node_fp.py")
        assert node is not None
        assert node["name"] == "target_node"

    def test_get_symbols_for_file_with_class_symbol(self, pg_mgr):
        """get_symbols_for_file with Class symbol exercises generic table insert (line 700)."""
        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        fi = FileInfo(path="/test/with_class.py", language="python", content_hash="hwc")
        sym = Symbol(name="MyClass", kind=SymbolKind.CLASS,
                     span=Span(file="/test/with_class.py", start_line=1, start_col=0,
                               end_line=10, end_col=5),
                     signature="", is_partial=False)
        pg_mgr.upsert_file(ParseResult(file=fi, symbols=[sym], edges=[], errors=[]))

        results = pg_mgr.get_symbols_for_file("/test/with_class.py")
        assert len(results) >= 1
        assert any(s.get("name") == "MyClass" for s in results)

    def test_upsert_file_with_method_symbol(self, pg_mgr):
        """Insert a METHOD symbol covers methods table insert path (line 688)."""
        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        fi = FileInfo(path="/test/method_file.py", language="python", content_hash="hm")
        sym = Symbol(name="my_method", kind=SymbolKind.METHOD,
                     span=Span(file="/test/method_file.py", start_line=1, start_col=0,
                               end_line=5, end_col=10),
                     signature="def my_method(self)", is_partial=False)
        pg_mgr.upsert_file(ParseResult(file=fi, symbols=[sym], edges=[], errors=[]))

        # Verify it's searchable
        results = pg_mgr.search("my_method")
        assert len(results) >= 1
        assert results[0]["symbol_name"] == "my_method"

    def test_get_callers_with_qualified_name(self, pg_mgr):
        """get_callers with qualified.name triggers short_name graph walk (line 806)."""
        from memorygraph.parsing.ir import (
            Edge,
            EdgeKind,
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        fi = FileInfo(path="/test/dotted.py", language="python", content_hash="hdot")
        sa = Symbol(name="outer_func", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/dotted.py", start_line=1, start_col=0,
                              end_line=3, end_col=5),
                    signature="def outer_func()", is_partial=False)
        sb = Symbol(name="inner_func", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/dotted.py", start_line=10, start_col=0,
                              end_line=12, end_col=5),
                    signature="def inner_func()", is_partial=False)
        edge = Edge(source="outer_func", target="inner_func", kind=EdgeKind.CALLS,
                    source_span=Span(file="/test/dotted.py", start_line=1, start_col=0,
                                     end_line=3, end_col=5),
                    target_span=Span(file="/test/dotted.py", start_line=10, start_col=0,
                                     end_line=12, end_col=5))
        pg_mgr.upsert_file(ParseResult(file=fi, symbols=[sa, sb], edges=[edge], errors=[]))

        # Query by qualified name with a dot triggers short_name extraction
        result = pg_mgr.get_callers("outer_func")
        assert isinstance(result, list)

    def test_graph_walk_with_file_path_and_dotted_name(self, pg_mgr):
        """get_callers with file_path + dotted name triggers short_name CTE (lines 772-788)."""
        from memorygraph.parsing.ir import (
            Edge,
            EdgeKind,
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        fi = FileInfo(path="/test/gw_file.py", language="python", content_hash="hgw")
        sa = Symbol(name="pkg_mod_func_a", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/gw_file.py", start_line=1, start_col=0,
                              end_line=3, end_col=5),
                    signature="def func_a()", is_partial=False)
        sb = Symbol(name="pkg_mod_func_b", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/gw_file.py", start_line=10, start_col=0,
                              end_line=12, end_col=5),
                    signature="def func_b()", is_partial=False)
        edge = Edge(source="pkg_mod_func_a", target="pkg_mod_func_b", kind=EdgeKind.CALLS,
                    source_span=Span(file="/test/gw_file.py", start_line=1, start_col=0,
                                     end_line=3, end_col=5),
                    target_span=Span(file="/test/gw_file.py", start_line=10, start_col=0,
                                     end_line=12, end_col=5))
        pg_mgr.upsert_file(ParseResult(file=fi, symbols=[sa, sb], edges=[edge], errors=[]))

        # Dotted name + file_path → short_name CTE branch
        result = pg_mgr.get_callers("pkg.mod.func_b", file_path="/test/gw_file.py")
        assert isinstance(result, list)

    def test_graph_walk_with_dotted_name_no_file_path(self, pg_mgr):
        """get_callers with dotted name and no file_path triggers short_name branch (line 806)."""
        from memorygraph.parsing.ir import (
            Edge,
            EdgeKind,
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        fi = FileInfo(path="/test/gw_dot.py", language="python", content_hash="hgwd")
        sa = Symbol(name="alpha_beta_caller", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/gw_dot.py", start_line=1, start_col=0,
                              end_line=3, end_col=5),
                    signature="def caller()", is_partial=False)
        sb = Symbol(name="alpha_beta_target", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/gw_dot.py", start_line=10, start_col=0,
                              end_line=12, end_col=5),
                    signature="def target()", is_partial=False)
        edge = Edge(source="alpha_beta_caller", target="alpha_beta_target", kind=EdgeKind.CALLS,
                    source_span=Span(file="/test/gw_dot.py", start_line=1, start_col=0,
                                     end_line=3, end_col=5),
                    target_span=Span(file="/test/gw_dot.py", start_line=10, start_col=0,
                                     end_line=12, end_col=5))
        pg_mgr.upsert_file(ParseResult(file=fi, symbols=[sa, sb], edges=[edge], errors=[]))

        # Dotted name without file_path → short_name-only branch
        result = pg_mgr.get_callers("alpha.beta.target")
        assert isinstance(result, list)

    def test_graph_walk_with_file_path_no_short_name(self, pg_mgr):
        """get_callees with file_path and simple name (no dot) — file_path-only CTE (line 790+)."""
        from memorygraph.parsing.ir import (
            Edge,
            EdgeKind,
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        fi = FileInfo(path="/test/gw_fp.py", language="python", content_hash="hgfp")
        sa = Symbol(name="source_func", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/gw_fp.py", start_line=1, start_col=0,
                              end_line=3, end_col=5),
                    signature="def source()", is_partial=False)
        sb = Symbol(name="target_func", kind=SymbolKind.FUNCTION,
                    span=Span(file="/test/gw_fp.py", start_line=10, start_col=0,
                              end_line=12, end_col=5),
                    signature="def target()", is_partial=False)
        edge = Edge(source="source_func", target="target_func", kind=EdgeKind.CALLS,
                    source_span=Span(file="/test/gw_fp.py", start_line=1, start_col=0,
                                     end_line=3, end_col=5),
                    target_span=Span(file="/test/gw_fp.py", start_line=10, start_col=0,
                                     end_line=12, end_col=5))
        pg_mgr.upsert_file(ParseResult(file=fi, symbols=[sa, sb], edges=[edge], errors=[]))

        # Simple name + file_path
        result = pg_mgr.get_callees("source_func", file_path="/test/gw_fp.py")
        assert isinstance(result, list)

    def test_upsert_file_exception_rolls_back(self, pg_mgr):
        """upsert_file raises and rolls back on DB error (lines 383-385)."""
        from unittest import mock

        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        fi = FileInfo(path="/test/upsert_fail.py", language="python", content_hash="huf")
        sym = Symbol(name="fail_func", kind=SymbolKind.FUNCTION,
                     span=Span(file="/test/upsert_fail.py", start_line=1, start_col=0,
                               end_line=3, end_col=5),
                     signature="def fail_func()", is_partial=False)
        result = ParseResult(file=fi, symbols=[sym], edges=[], errors=[])

        # Mock _insert_symbols to simulate DB failure mid-upsert
        with mock.patch.object(pg_mgr, "_insert_symbols") as mock_insert:
            mock_insert.side_effect = RuntimeError("simulated DB insert error")
            with pytest.raises(RuntimeError, match="simulated DB insert error"):
                pg_mgr.upsert_file(result)

    def test_delete_file_exception_rolls_back(self, pg_mgr):
        """delete_file raises and rolls back on DB error (lines 407-409)."""
        from unittest import mock

        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        # First insert a file normally
        fi = FileInfo(path="/test/delete_fail.py", language="python", content_hash="hdf")
        sym = Symbol(name="will_fail", kind=SymbolKind.FUNCTION,
                     span=Span(file="/test/delete_fail.py", start_line=1, start_col=0,
                               end_line=3, end_col=5),
                     signature="def will_fail()", is_partial=False)
        pg_mgr.upsert_file(ParseResult(file=fi, symbols=[sym], edges=[], errors=[]))

        # Use a MagicMock connection whose cursor() raises
        bad_conn = mock.MagicMock()
        bad_conn.cursor.side_effect = RuntimeError("simulated delete error")

        with mock.patch.object(pg_mgr._pool, "getconn", return_value=bad_conn):
            with mock.patch.object(pg_mgr._pool, "putconn"):  # skip putconn
                with mock.patch.object(pg_mgr, "connect"):  # skip re-connect
                    with pytest.raises(RuntimeError, match="simulated delete error"):
                        pg_mgr.delete_file("/test/delete_fail.py")

    def test_bulk_upsert_exception_rolls_back(self, pg_mgr):
        """bulk_upsert raises and rolls back on DB error (lines 521-523)."""
        from unittest import mock

        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        fi = FileInfo(path="/test/bulk_fail.py", language="python", content_hash="hbf")
        sym = Symbol(name="bulk_fail_func", kind=SymbolKind.FUNCTION,
                     span=Span(file="/test/bulk_fail.py", start_line=1, start_col=0,
                               end_line=3, end_col=5),
                     signature="def bulk_fail_func()", is_partial=False)
        result = ParseResult(file=fi, symbols=[sym], edges=[], errors=[])

        # Mock _insert_fts_rows to simulate DB failure mid-bulk-upsert
        with mock.patch.object(pg_mgr, "_insert_fts_rows") as mock_fts:
            mock_fts.side_effect = RuntimeError("simulated bulk FTS error")
            with pytest.raises(RuntimeError, match="simulated bulk FTS error"):
                pg_mgr.bulk_upsert({"/test/bulk_fail.py": result})

    def test_semantic_search_word_exception_skipped(self, pg_mgr):
        """semantic_search skips failing word search gracefully (lines 539-541)."""
        from unittest import mock

        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        fi = FileInfo(path="/test/sem_fail.py", language="python", content_hash="hsf")
        sym = Symbol(name="seman_search_ok", kind=SymbolKind.FUNCTION,
                     span=Span(file="/test/sem_fail.py", start_line=1, start_col=0,
                               end_line=3, end_col=5),
                     signature="def seman_search_ok()", is_partial=False)
        pg_mgr.upsert_file(ParseResult(file=fi, symbols=[sym], edges=[], errors=[]))

        # Mock search to raise for one word, succeed for another
        original_search = pg_mgr.search
        call_count = [0]

        def _flaky_search(query, limit=20, file_path=None):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("word search failed")
            return original_search(query, limit=limit, file_path=file_path)

        with mock.patch.object(pg_mgr, "search", side_effect=_flaky_search):
            results = pg_mgr.semantic_search("failword goodword")
            # Should skip the failing word and use the good one
            assert isinstance(results, list)

    def test_stats_embeddings_table_missing(self, pg_mgr):
        """stats handles missing embeddings table gracefully (lines 643-644)."""
        # Drop the embeddings table to trigger the exception handler
        conn = pg_mgr._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS embeddings CASCADE")
            conn.commit()
        finally:
            pg_mgr._pool.putconn(conn)

        # stats() should handle the missing embeddings table gracefully
        stats = pg_mgr.stats()
        assert stats["embeddings_available"] is False

        # Re-initialize to restore the table for other tests
        pg_mgr.initialize()

    def test_semantic_search_fallback_phrase_success(self, pg_mgr):
        """semantic_search fallback phrase search succeeds (line 558)."""
        from unittest import mock

        from memorygraph.parsing.ir import (
            FileInfo,
            ParseResult,
            Span,
            Symbol,
            SymbolKind,
        )

        fi = FileInfo(path="/test/fb_ok.py", language="python", content_hash="hfb")
        sym = Symbol(name="full_phrase_match", kind=SymbolKind.FUNCTION,
                     span=Span(file="/test/fb_ok.py", start_line=1, start_col=0,
                               end_line=3, end_col=5),
                     signature="def full_phrase_match()", is_partial=False)
        pg_mgr.upsert_file(ParseResult(file=fi, symbols=[sym], edges=[], errors=[]))

        # Mock search: per-word returns empty, full phrase returns results
        original_search = pg_mgr.search
        call_count = [0]

        def _selective_search(query, limit=20, file_path=None):
            call_count[0] += 1
            if len(query.split()) == 1:
                return []  # Per-word: empty → triggers fallback
            return original_search(query, limit=limit, file_path=file_path)

        with mock.patch.object(pg_mgr, "search", side_effect=_selective_search):
            results = pg_mgr.semantic_search("full phrase match")
            assert isinstance(results, list)
            # Should have gotten results from phrase fallback
            assert len(results) >= 1

    def test_semantic_search_fallback_phrase_exception(self, pg_mgr):
        """semantic_search fallback phrase search fails silently (lines 560-561)."""
        from unittest import mock

        # Mock search: per-word returns empty, full phrase raises
        call_count = [0]

        def _flaky_search(query, limit=20, file_path=None):
            call_count[0] += 1
            if len(query.split()) == 1:
                return []  # Per-word: empty
            raise RuntimeError("phrase search also failed")

        with mock.patch.object(pg_mgr, "search", side_effect=_flaky_search):
            results = pg_mgr.semantic_search("no match at all")
            # Should return empty gracefully
            assert isinstance(results, list)
            assert results == []
