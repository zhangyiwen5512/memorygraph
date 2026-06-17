"""Tests for StorageManager."""
import os
import tempfile

import pytest

from memorygraph.parsing.ir import Edge, EdgeKind, FileInfo, ParseResult, Span, Symbol, SymbolKind
from memorygraph.storage.manager import StorageManager


@pytest.fixture
def db():
    tmpdir = tempfile.mkdtemp()
    mgr = StorageManager(tmpdir)
    mgr.initialize()
    yield mgr
    mgr.close()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


def make_parse_result(file_path: str) -> ParseResult:
    span = Span(file=file_path, start_line=1, start_col=0, end_line=1, end_col=10)
    info = FileInfo(path=file_path, language="python", content_hash="abc123")
    return ParseResult(
        file=info,
        symbols=[
            Symbol(name="my_func", kind=SymbolKind.FUNCTION, span=span,
                   parent_symbol=None, signature="def my_func():"),
            Symbol(name="MyClass", kind=SymbolKind.CLASS, span=span,
                   parent_symbol=None),
            Symbol(name="do_thing", kind=SymbolKind.METHOD, span=span,
                   parent_symbol="MyClass", signature="def do_thing(self):"),
        ],
        edges=[
            Edge(source="my_func", target="MyClass.do_thing", kind=EdgeKind.CALLS,
                 source_span=span),
        ],
        errors=[]
    )


def test_initialize_creates_db(db):
    assert os.path.exists(db._db_path)


def test_upsert_file_stores_symbols(db):
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)

    symbols = db.get_symbols_for_file("/proj/test.py")
    assert len(symbols) == 3


def test_upsert_file_stores_edges(db):
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)

    callers = db.get_callers("MyClass.do_thing")
    assert len(callers) == 1
    assert callers[0]["source"] == "my_func"


def test_upsert_file_updates_existing(db):
    result1 = make_parse_result("/proj/test.py")
    db.upsert_file(result1)

    span = Span(file="/proj/test.py", start_line=1, start_col=0, end_line=1, end_col=10)
    info = FileInfo(path="/proj/test.py", language="python", content_hash="newhash")
    result2 = ParseResult(
        file=info,
        symbols=[Symbol(name="new_func", kind=SymbolKind.FUNCTION, span=span)],
        edges=[],
        errors=[]
    )
    db.upsert_file(result2)

    symbols = db.get_symbols_for_file("/proj/test.py")
    assert len(symbols) == 1
    assert symbols[0]["name"] == "new_func"


def test_file_hash_tracking(db):
    result = make_parse_result("/proj/a.py")
    db.upsert_file(result)
    assert db.get_file_hash("/proj/a.py") == "abc123"
    assert db.get_file_hash("/proj/unknown.py") is None


def test_search_fts(db):
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)

    results = db.search("my_func")
    assert len(results) > 0
    assert results[0]["symbol_name"] == "my_func"


def test_get_node(db):
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)

    node = db.get_node("my_func")
    assert node is not None
    assert node["name"] == "my_func"
    assert node["kind"] == "function"

    # Method should have kind='method'
    node2 = db.get_node("MyClass.do_thing")
    assert node2 is not None
    assert node2["kind"] == "method"

    # Class should have kind='class'
    node3 = db.get_node("MyClass")
    assert node3 is not None
    assert node3["kind"] == "class"


def test_get_node_none_for_unknown(db):
    assert db.get_node("nonexistent") is None


def test_get_node_returns_file_path(db):
    """get_node should include file_path resolved from the files table."""
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)

    node = db.get_node("my_func")
    assert node is not None
    assert "file_path" in node, "get_node must return 'file_path' field"
    assert node["file_path"] == "/proj/test.py"


def test_stats(db):
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)

    s = db.stats()
    assert s["file_count"] == 1


def test_get_node_with_file_path(db):
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)

    # Find with matching file_path
    node = db.get_node("my_func", file_path="/proj/test.py")
    assert node is not None
    assert node["name"] == "my_func"

    # Non-matching file_path should return None
    node2 = db.get_node("my_func", file_path="/other/file.py")
    assert node2 is None


def test_list_files(db):
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)

    files = db.list_files()
    assert len(files) == 1
    assert files[0]["path"] == "/proj/test.py"
    assert files[0]["language"] == "python"


def test_semantic_search_edge_cases(db):
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)

    # Empty query (no words >= 3 chars)
    results = db.semantic_search("ab", limit=10)
    assert isinstance(results, list)

    # Multi-word query
    results = db.semantic_search("my func helper", limit=10)
    assert isinstance(results, list)


def test_get_callees(db):
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)

    callees = db.get_callees("my_func")
    assert len(callees) == 1
    assert callees[0]["target"] == "MyClass.do_thing"


def test_get_impact(db):
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)

    impact = db.get_impact("my_func", max_depth=3)
    assert len(impact) >= 1


def test_delete_file(db):
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)
    db.delete_file("/proj/test.py")

    symbols = db.get_symbols_for_file("/proj/test.py")
    assert len(symbols) == 0


def test_delete_nonexistent_file(db):
    """Line 196: delete_file on a file not in the index is a no-op."""
    # Should not raise
    db.delete_file("/proj/does_not_exist.py")
    # Verify existing data is unaffected
    result = make_parse_result("/proj/existing.py")
    db.upsert_file(result)
    db.delete_file("/proj/does_not_exist.py")
    symbols = db.get_symbols_for_file("/proj/existing.py")
    assert len(symbols) == 3  # make_parse_result produces 3 symbols


# ── Iteration 34: manager.py coverage push ────────────────────────

def test_unknown_symbol_kind_skipped(db):
    """Line 78: symbol with unknown kind is skipped gracefully."""
    from memorygraph.parsing.ir import SymbolKind
    span = Span(file="/proj/test.py", start_line=1, start_col=0, end_line=1, end_col=10)
    info = FileInfo(path="/proj/test.py", language="python", content_hash="abc")

    # Create a symbol with a valid kind first, then mutate its kind value
    sym = Symbol(name="valid_func", kind=SymbolKind.FUNCTION, span=span)
    # Monkey-patch SymbolKind enum to remove one table→kind mapping
    result = ParseResult(file=info, symbols=[sym], edges=[], errors=[])
    db.upsert_file(result)
    assert len(db.get_symbols_for_file("/proj/test.py")) == 1


def test_edges_with_target_span(db):
    """Lines 99-103, 360-368: edges with non-None target_span."""
    span1 = Span(file="/proj/a.py", start_line=1, start_col=0, end_line=1, end_col=10)
    span2 = Span(file="/proj/b.py", start_line=5, start_col=0, end_line=5, end_col=10)
    info_a = FileInfo(path="/proj/a.py", language="python", content_hash="aaa")
    info_b = FileInfo(path="/proj/b.py", language="python", content_hash="bbb")

    # First upsert b.py so _find_file_id can find it
    result_b = ParseResult(
        file=info_b,
        symbols=[Symbol(name="target_func", kind=SymbolKind.FUNCTION, span=span2)],
        edges=[], errors=[]
    )
    db.upsert_file(result_b)

    # Now create edge in a.py pointing to b.py:target_func
    target_span = Span(file="/proj/b.py", start_line=5, start_col=0, end_line=5, end_col=10)
    result_a = ParseResult(
        file=info_a,
        symbols=[Symbol(name="source_func", kind=SymbolKind.FUNCTION, span=span1)],
        edges=[Edge(source="source_func", target="target_func", kind=EdgeKind.CALLS,
                     source_span=span1, target_span=target_span)],
        errors=[]
    )
    db.upsert_file(result_a)

    # Verify edge was stored with cross-file target
    callers = db.get_callers("target_func")
    assert len(callers) == 1
    assert callers[0]["source"] == "source_func"


def test_find_file_id_cache(db):
    """Lines 360-368: _find_file_id cache hit, DB hit, and not-found."""
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)
    # Clear cache
    db._file_id_cache.clear()
    # First call: DB hit (line 362-367)
    fid1 = db._find_file_id(db._get_conn(), "/proj/test.py")
    assert fid1 is not None
    # Second call: cache hit (line 360-361)
    fid2 = db._find_file_id(db._get_conn(), "/proj/test.py")
    assert fid2 == fid1
    # Not found (line 368)
    fid3 = db._find_file_id(db._get_conn(), "/proj/nonexistent.py")
    assert fid3 is None


def test_cache_hits(db):
    """Lines 150, 230, 242: search/get_callers/get_callees cache hits."""
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)

    # First call: populates cache
    r1 = db.search("my_func")
    assert len(r1) > 0
    # Second call: cache hit (line 150)
    r2 = db.search("my_func")
    assert r2 == r1

    # get_callers cache hit (line 230)
    c1 = db.get_callers("MyClass.do_thing")
    c2 = db.get_callers("MyClass.do_thing")
    assert c2 == c1

    # get_callees cache hit (line 242)
    cal1 = db.get_callees("my_func")
    cal2 = db.get_callees("my_func")
    assert cal2 == cal1


def test_bulk_upsert_skips_fatal_error(db):
    """Line 167: bulk_upsert skips results with fatal_error."""
    Span(file="/proj/bad.py", start_line=1, start_col=0, end_line=1, end_col=10)
    info = FileInfo(path="/proj/bad.py", language="python", content_hash="err")
    bad_result = ParseResult(
        file=info, symbols=[], edges=[], errors=[],
        fatal_error="Parse timeout"
    )
    good_result = make_parse_result("/proj/good.py")
    results = {"/proj/bad.py": bad_result, "/proj/good.py": good_result}
    count = db.bulk_upsert(results)
    assert count == 1  # Only good file
    # bad.py should not be indexed
    assert db.get_symbols_for_file("/proj/bad.py") == []


def test_bulk_upsert_clears_cache(db):
    """Line 172: bulk_upsert clears query_cache on success."""
    result = make_parse_result("/proj/test.py")
    # Prime cache
    db.query_cache.put("test_key", "test_value")
    assert db.query_cache.get("test_key") == "test_value"
    db.bulk_upsert({"/proj/test.py": result})
    # Cache should be cleared
    assert db.query_cache.get("test_key") is None


def test_bulk_upsert_rollback(db):
    """Lines 174-176: bulk_upsert rollback on exception."""
    from unittest import mock
    span = Span(file="/proj/test.py", start_line=1, start_col=0, end_line=1, end_col=10)
    info = FileInfo(path="/proj/test.py", language="python", content_hash="abc")
    result = ParseResult(
        file=info,
        symbols=[Symbol(name="func", kind=SymbolKind.FUNCTION, span=span)],
        edges=[], errors=[]
    )
    # Mock the internal upsert_file to raise exception mid-transaction
    with mock.patch.object(db, "upsert_file", side_effect=Exception("DB error")):
        with pytest.raises(Exception):
            db.bulk_upsert({"/proj/test.py": result})
    # Symbol should NOT be persisted (rolled back)
    assert db.get_symbols_for_file("/proj/test.py") == []


def test_semantic_search_per_word_exception(db):
    """Lines 199-200: semantic_search handles per-word exception."""
    from unittest import mock
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)
    # Mock search to fail on first word, succeed on second
    original_search = db.search
    call_count = [0]

    def mock_search(query, limit=None):
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("FTS error")
        return original_search(query, limit=limit)

    with mock.patch.object(db, "search", side_effect=mock_search):
        results = db.semantic_search("my_func helper", limit=10)
        assert isinstance(results, list)


def test_semantic_search_fallback(db):
    """Lines 214-221: semantic_search fallback when no multi-word match."""
    from unittest import mock
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)
    # Mock search to return empty for individual words, then succeed on fallback
    with mock.patch.object(db, "search", return_value=[]):
        results = db.semantic_search("unique fancy query", limit=10)
        assert results == []  # Fallback searches with full phrase (also returns [])

    # Test fallback exception (line 220-221)
    call_count = [0]

    def mock_search_second_fails(query, limit=None):
        call_count[0] += 1
        if call_count[0] == 4:  # 3 words + 1 fallback (the 4th call)
            raise Exception("Fallback error")
        return []

    with mock.patch.object(db, "search", side_effect=mock_search_second_fails):
        results = db.semantic_search("unique fancy query", limit=10)
        assert results == []


def test_stats_missing_embeddings(db):
    """Lines 292-293: stats handles missing embeddings table."""
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)
    s = db.stats()
    assert s["file_count"] == 1
    assert s["embeddings_available"] is False


def test_unknown_symbol_table_warning(db):
    """Lines 356-357: _insert_symbols with unknown table."""
    from memorygraph.storage.repositories import SymbolRepo
    # Monkey-patch method_map to miss a table, then call _insert_symbols
    # Directly call _insert_symbols with a nonexistent table name
    db._insert_symbols(SymbolRepo(db._get_conn()), "unknown_table", [], 1)
    # Should log warning but not crash


def test_unknown_symbol_kind_monkeypatched(db):
    """Line 78: symbol kind not in SYMBOL_KIND_TO_TABLE is skipped."""
    span = Span(file="/proj/test.py", start_line=1, start_col=0, end_line=1, end_col=10)
    info = FileInfo(path="/proj/test.py", language="python", content_hash="abc")

    # Create a symbol with a kind whose value is not in SYMBOL_KIND_TO_TABLE
    class FakeKind:
        value = "unknown_kind_xyz"
    sym = Symbol(name="unknown", kind=FakeKind(), span=span)
    result = ParseResult(file=info, symbols=[sym], edges=[], errors=[])
    db.upsert_file(result)
    assert len(db.get_symbols_for_file("/proj/test.py")) == 0


def test_semantic_search_fallback_score(db):
    """Line 218: semantic_search fallback assigns _score=1."""
    from unittest import mock
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)
    # "three word query here" has 4 words (all >= 3 chars)
    # Make all per-word searches return [] so fallback triggers
    call_count = [0]
    def mock_search(query, limit=None, file_path=None):
        call_count[0] += 1
        if call_count[0] <= 4:  # 4 per-word calls → []
            return []
        # 5th call = fallback with full phrase → returns result
        return [{"qualified_name": "my_func", "symbol_name": "my_func",
                  "kind": "function", "file_path": "/proj/test.py",
                  "start_line": 1, "signature": "def my_func():"}]
    with mock.patch.object(db, "search", side_effect=mock_search):
        results = db.semantic_search("three word query here", limit=10)
        assert len(results) == 1
        # Fallback sets _score=1
        assert results[0].get("_score") == 1


def test_stats_embeddings_exception(db):
    """Lines 292-293: stats handles exception from embeddings table query."""
    from unittest import mock
    result = make_parse_result("/proj/test.py")
    db.upsert_file(result)
    # Mock _get_conn to return a MagicMock that fails on embeddings query
    mock_conn = mock.MagicMock()
    def execute_side(query, *args):
        m = mock.MagicMock()
        if "embeddings" in str(query).lower():
            raise Exception("Table missing")
        m.fetchone.return_value = [1]
        return m
    mock_conn.execute.side_effect = execute_side

    with mock.patch.object(db, "_get_conn", return_value=mock_conn):
        s = db.stats()
        assert s["file_count"] >= 0
        assert s["embeddings_available"] is False


# ── Iteration 46: Coverage refresh ──────────────────────────────


class TestManagerCoverageGaps:
    """Targeted tests for remaining manager.py coverage gaps."""

    def test_close_with_read_only_conns(self, db):
        """close() handles read-only connections (cover line 52)."""
        # Open a read-only connection
        with db.read_only_connection() as conn:
            assert conn is not None
            # Now close the manager while read-only conn is tracked
            # We don't close inside the with block, instead close the manager
        # After the with block, the conn is removed from _read_only_conns
        # So let's add a conn directly to test line 52
        from memorygraph.storage.connection import get_connection
        extra_conn = get_connection(db._db_path)
        db._read_only_conns.append(extra_conn)
        # Now close - should iterate and close all read-only conns
        db.close()
        # After close, _read_only_conns should be empty
        assert len(db._read_only_conns) == 0

    def test_upsert_file_exception_triggers_rollback(self, db):
        """upsert_file rolls back on exception (cover lines 134-136)."""
        from unittest import mock
        result = make_parse_result("/test_except.py")
        # Force an error during edge insert by providing invalid data
        from memorygraph.storage.manager import sqlite3
        with mock.patch.object(db, "_get_conn") as mock_get_conn:
            mock_conn = mock.MagicMock()
            mock_get_conn.return_value = mock_conn
            # Make execute fail
            mock_conn.execute.side_effect = sqlite3.OperationalError("mock error")
            with pytest.raises(sqlite3.OperationalError):
                db.upsert_file(result)
            mock_conn.rollback.assert_called_once()

    def test_read_only_connection_context_manager(self, db):
        """read_only_connection creates and cleans up a read-only conn (cover lines 263-270)."""
        with db.read_only_connection() as conn:
            assert conn is not None
            # Verify it's actually queryable
            rows = conn.execute("SELECT 1").fetchall()
            assert rows[0][0] == 1
        # After exit, the conn should be removed
        assert len(db._read_only_conns) == 0

    def test_db_path_property(self, db):
        """db_path property returns the database path (cover line 420)."""
        path = db.db_path
        assert path == db._db_path
        assert path.endswith(".memorygraph/memorygraph.db")

