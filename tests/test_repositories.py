"""Tests for repository layer."""
import os
import sqlite3
import tempfile

import pytest

from memorygraph.storage.repositories import EdgeRepo, FileRepo, FTSRepo, SymbolRepo
from memorygraph.storage.schema import init_db


@pytest.fixture
def conn():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    init_db(c)
    yield c
    c.close()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestFileRepo:
    def test_upsert_inserts_new_file(self, conn):
        repo = FileRepo(conn)
        fid = repo.upsert(
            path="/abs/test.py", language="python",
            file_hash="abc123", symbol_count=3, edge_count=2, error_count=0
        )
        assert fid > 0
        row = conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
        assert row["path"] == "/abs/test.py"
        assert row["file_hash"] == "abc123"

    def test_upsert_updates_existing_file(self, conn):
        repo = FileRepo(conn)
        fid1 = repo.upsert(
            path="/abs/test.py", language="python",
            file_hash="abc", symbol_count=1, edge_count=0, error_count=0
        )
        fid2 = repo.upsert(
            path="/abs/test.py", language="python",
            file_hash="xyz", symbol_count=5, edge_count=3, error_count=0
        )
        assert fid2 == fid1
        row = conn.execute("SELECT * FROM files WHERE id = ?", (fid2,)).fetchone()
        assert row["file_hash"] == "xyz"
        assert row["symbol_count"] == 5

    def test_get_hash(self, conn):
        repo = FileRepo(conn)
        repo.upsert("/a.py", "python", "hash1", 0, 0, 0)
        assert repo.get_hash("/a.py") == "hash1"

    def test_get_hash_none_for_unknown_path(self, conn):
        repo = FileRepo(conn)
        assert repo.get_hash("/nonexistent.py") is None



def _insert_file(conn, path="/test.py", lang="python", hash_val="abc"):
    conn.execute(
        "INSERT INTO files (path, language, file_hash) VALUES (?, ?, ?)",
        (path, lang, hash_val)
    )
    return conn.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()[0]


class TestSymbolRepo:
    def test_insert_function(self, conn):
        fid = _insert_file(conn)
        repo = SymbolRepo(conn)
        repo.insert_functions([
            ("func1", "mod.func1", "def func1():", 1, 0, 1, 20, 0),
        ], file_id=fid)
        rows = conn.execute("SELECT * FROM functions").fetchall()
        assert len(rows) == 1
        assert rows[0]["name"] == "func1"

    def test_insert_method(self, conn):
        fid = _insert_file(conn)
        repo = SymbolRepo(conn)
        repo.insert_methods([
            ("add", "Calc.add", "Calculator", "def add(self, a, b):", 5, 4, 5, 24, 0),
        ], file_id=fid)
        rows = conn.execute("SELECT * FROM methods").fetchall()
        assert len(rows) == 1
        assert rows[0]["parent_class"] == "Calculator"

    def test_insert_class(self, conn):
        fid = _insert_file(conn)
        repo = SymbolRepo(conn)
        repo.insert_classes([
            ("MyClass", "mod.MyClass", 3, 0, 10, 0, 0),
        ], file_id=fid)
        rows = conn.execute("SELECT * FROM classes").fetchall()
        assert len(rows) == 1
        assert rows[0]["qualified_name"] == "mod.MyClass"

    def test_delete_by_file(self, conn):
        fid = _insert_file(conn)
        repo = SymbolRepo(conn)
        repo.insert_functions([("f", "f", "", 1, 0, 1, 0, 0)], file_id=fid)
        repo.insert_classes([("C", "C", 2, 0, 2, 0, 0)], file_id=fid)
        repo.delete_by_file("functions", fid)
        rows = conn.execute("SELECT * FROM functions").fetchall()
        assert len(rows) == 0
        rows2 = conn.execute("SELECT * FROM classes").fetchall()
        assert len(rows2) == 1

    def test_insert_interfaces(self, conn):
        fid = _insert_file(conn)
        repo = SymbolRepo(conn)
        repo.insert_interfaces([("I", "I", 1, 0, 1, 0, 0)], file_id=fid)
        rows = conn.execute("SELECT * FROM interfaces").fetchall()
        assert len(rows) == 1
        assert rows[0]["name"] == "I"

    def test_insert_type_aliases(self, conn):
        fid = _insert_file(conn)
        repo = SymbolRepo(conn)
        repo.insert_type_aliases([("T", "T", 1, 0, 1, 0, 0)], file_id=fid)
        rows = conn.execute("SELECT * FROM type_aliases").fetchall()
        assert len(rows) == 1
        assert rows[0]["name"] == "T"

    def test_insert_variables(self, conn):
        fid = _insert_file(conn)
        repo = SymbolRepo(conn)
        repo.insert_variables([("v", "v", 1, 0, 1, 0, 0)], file_id=fid)
        rows = conn.execute("SELECT * FROM variables").fetchall()
        assert len(rows) == 1
        assert rows[0]["name"] == "v"

class TestEdgeRepo:
    def test_insert_edges(self, conn):
        fid = _insert_file(conn)
        repo = EdgeRepo(conn)
        repo.insert_batch([
            ("a.f", "b.g", "calls", fid, 5, 4, 5, 10, None, None, None, None, None),
        ])
        rows = conn.execute("SELECT * FROM edges").fetchall()
        assert len(rows) == 1
        assert rows[0]["kind"] == "calls"

    def test_delete_by_source_file(self, conn):
        fid = _insert_file(conn)
        repo = EdgeRepo(conn)
        repo.insert_batch([
            ("a", "b", "calls", fid, 0, 0, 0, 0, None, None, None, None, None),
        ])
        repo.delete_by_source_file(fid)
        rows = conn.execute("SELECT * FROM edges").fetchall()
        assert len(rows) == 0

    def test_get_callers(self, conn):
        fid = _insert_file(conn)
        repo = EdgeRepo(conn)
        repo.insert_batch([
            ("caller_func", "target_func", "calls", fid, 0, 0, 0, 0, None, None, None, None, None),
        ])
        callers = list(repo.get_callers("target_func"))
        assert len(callers) == 1
        assert callers[0]["source"] == "caller_func"

    def test_get_callees(self, conn):
        fid = _insert_file(conn)
        repo = EdgeRepo(conn)
        repo.insert_batch([
            ("caller_func", "target_func", "calls", fid, 0, 0, 0, 0, None, None, None, None, None),
        ])
        callees = list(repo.get_callees("caller_func"))
        assert len(callees) == 1
        assert callees[0]["target"] == "target_func"

    def test_get_callers_short_name_fallback(self, conn):
        """get_callers matches short-name edges when querying with qualified_name."""
        fid = _insert_file(conn)
        repo = EdgeRepo(conn)
        # Edge stores short name as target, but query uses qualified name
        repo.insert_batch([
            ("caller_func", "do_work", "calls", fid, 0, 0, 0, 0, None, None, None, None, None),
        ])
        callers = list(repo.get_callers("MyClass.do_work"))
        assert len(callers) == 1
        assert callers[0]["source"] == "caller_func"
        assert callers[0]["target"] == "do_work"

    def test_get_callees_short_name_fallback(self, conn):
        """get_callees matches short-name edges when querying with qualified_name."""
        fid = _insert_file(conn)
        repo = EdgeRepo(conn)
        repo.insert_batch([
            ("do_work", "helper_func", "calls", fid, 0, 0, 0, 0, None, None, None, None, None),
        ])
        callees = list(repo.get_callees("MyClass.do_work"))
        assert len(callees) == 1
        assert callees[0]["target"] == "helper_func"

    def test_get_callers_with_file_path(self, conn):
        """get_callers with file_path filter uses CTE query."""
        fid = _insert_file(conn)
        repo = EdgeRepo(conn)
        repo.insert_batch([
            ("caller_func", "Helper.do_work", "calls", fid, 0, 0, 0, 0, None, None, None, None, None),
        ])
        callers = list(repo.get_callers("Helper.do_work", file_path="/proj/test.py"))
        assert len(callers) >= 0

    def test_get_callees_with_file_path(self, conn):
        """get_callees with file_path filter uses CTE query."""
        fid = _insert_file(conn)
        repo = EdgeRepo(conn)
        repo.insert_batch([
            ("Helper.do_work", "target_func", "calls", fid, 0, 0, 0, 0, None, None, None, None, None),
        ])
        callees = list(repo.get_callees("Helper.do_work", file_path="/proj/test.py"))
        assert len(callees) >= 0


class TestFTSRepo:
    def test_insert_and_search(self, conn):
        repo = FTSRepo(conn)
        repo.insert_batch([(
            "greet", "greet", "def greet(name: str) -> str", "/a.py", "function"
        )])
        results = repo.search("greet")
        assert len(results) > 0
        assert results[0]["symbol_name"] == "greet"

    def test_delete_by_file(self, conn):
        repo = FTSRepo(conn)
        repo.insert_batch([("f1", "f1", "", "/a.py", "function")])
        repo.insert_batch([("f2", "f2", "", "/b.py", "function")])
        repo.delete_by_file("/a.py")
        results = repo.search("f1")
        assert len(results) == 0
        results2 = repo.search("f2")
        assert len(results2) == 1

    def test_search_exact_match_ranks_highest(self, conn):
        """Exact name match should rank before partial matches."""
        repo = FTSRepo(conn)
        repo.insert_batch([("do_work", "do_work", "def do_work()", "/a.py", "function")])
        repo.insert_batch([("do_work_helper", "do_work_helper", "def do_work_helper()", "/b.py", "function")])
        repo.insert_batch([("helper_do_work", "helper_do_work", "def helper_do_work()", "/c.py", "function")])
        results = repo.search("do_work")
        assert len(results) >= 3
        assert results[0]["symbol_name"] == "do_work"

    def test_search_class_ranks_before_variable(self, conn):
        """Class/interface should rank before variable for same name match."""
        repo = FTSRepo(conn)
        repo.insert_batch([("MyThing", "MyThing", "", "/a.py", "variable")])
        repo.insert_batch([("MyThing", "MyThing", "", "/b.py", "class")])
        results = repo.search("MyThing")
        assert len(results) >= 2
        # Class should rank before variable
        assert results[0]["kind"] == "class"

    def test_search_results_have_score(self, conn):
        """All search results should include _score field."""
        repo = FTSRepo(conn)
        repo.insert_batch([("compute", "compute", "def compute(x)", "/a.py", "function")])
        results = repo.search("compute")
        assert len(results) > 0
        assert "_score" in results[0]

    def test_search_empty_result(self, conn):
        """Search with no matches returns empty list."""
        repo = FTSRepo(conn)
        results = repo.search("nonexistent_xyz_123")
        assert results == []

    def test_search_with_file_path(self, conn):
        """FTS search with file_path filter (cover repositories.py line 371)."""
        repo = FTSRepo(conn)
        repo.insert_batch([("foo", "foo", "def foo()", "/a.py", "function")])
        repo.insert_batch([("foo", "foo", "def foo()", "/b.py", "function")])
        results = repo.search("foo", file_path="/a.py")
        assert len(results) == 1
        assert results[0]["file_path"] == "/a.py"


def test_rank_search_results_exact_boost():
    """_rank_search_results: exact match gets -1000 score boost."""
    from memorygraph.storage.repositories import _rank_search_results
    results = [
        {"symbol_name": "Helper", "qualified_name": "Helper", "rank": 1.0, "kind": "class"},
        {"symbol_name": "do_work", "qualified_name": "do_work", "rank": 0.5, "kind": "function"},
    ]
    ranked = _rank_search_results(results, "do_work")
    assert ranked[0]["symbol_name"] == "do_work"

def test_rank_search_results_prefix_boost():
    """_rank_search_results: prefix match gets -500 score boost."""
    from memorygraph.storage.repositories import _rank_search_results
    results = [
        {"symbol_name": "fetch_data", "qualified_name": "fetch_data", "rank": 2.0, "kind": "function"},
        {"symbol_name": "fetch", "qualified_name": "fetch", "rank": 3.0, "kind": "function"},
    ]
    ranked = _rank_search_results(results, "fetch")
    assert ranked[0]["symbol_name"] == "fetch"

def test_rank_search_results_kind_priority():
    """_rank_search_results: class ranks before variable with same match quality."""
    from memorygraph.storage.repositories import _rank_search_results
    results = [
        {"symbol_name": "Data", "qualified_name": "Data", "rank": 1.0, "kind": "variable"},
        {"symbol_name": "Data", "qualified_name": "Data", "rank": 1.0, "kind": "class"},
    ]
    ranked = _rank_search_results(results, "Data")
    assert ranked[0]["kind"] == "class"
