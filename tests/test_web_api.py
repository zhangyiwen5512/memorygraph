"""Tests for web API handlers."""
from unittest.mock import MagicMock

import pytest

from memorygraph.web.api import _node_to_json, handle_annotate, handle_api, handle_delete_annotation


class TestHandleApiGraph:
    def test_graph_with_root(self):
        mgr = MagicMock()
        mgr._db_path = "/tmp/project/.memorygraph/memorygraph.db"
        mgr.get_node.return_value = {
            "qualified_name": "main",
            "kind": "function",
            "start_line": 1,
            "file_path": "/tmp/project/main.py",
        }
        mgr.get_callers.return_value = [{"source": "caller1", "target": "main"}]
        mgr.get_callees.return_value = [{"source": "main", "target": "callee1"}]

        sem_store = MagicMock()
        sem_store.load_all.return_value = []

        result = handle_api("/api/graph?root=main&depth=1", mgr, sem_store)
        assert "nodes" in result
        assert "edges" in result
        assert len(result["nodes"]) >= 1

    def test_graph_returns_empty_when_root_not_found(self):
        mgr = MagicMock()
        mgr._db_path = "/tmp/project/.memorygraph/memorygraph.db"
        mgr.get_node.return_value = None
        mgr.get_callers.return_value = []
        mgr.get_callees.return_value = []

        sem_store = MagicMock()
        sem_store.load_all.return_value = []

        result = handle_api("/api/graph?root=nonexistent&depth=1", mgr, sem_store)
        assert result["nodes"] == []
        assert result["edges"] == []


class TestHandleApiSearch:
    def test_search_with_query(self):
        mgr = MagicMock()
        mgr.semantic_search.return_value = [
            {"qualified_name": "handle_request", "kind": "function",
             "file_path": "/src/server.py", "start_line": 42}
        ]
        sem_store = MagicMock()

        result = handle_api("/api/search?q=handle+request&limit=5", mgr, sem_store)
        assert "results" in result
        assert len(result["results"]) == 1
        assert result["results"][0]["symbol"] == "handle_request"

    def test_search_empty_query(self):
        mgr = MagicMock()
        sem_store = MagicMock()

        result = handle_api("/api/search?q=", mgr, sem_store)
        assert result == {"results": []}


class TestHandleApiNode:
    def test_node_found(self):
        mgr = MagicMock()
        mgr.get_node.return_value = {
            "qualified_name": "foo.bar",
            "kind": "function",
            "start_line": 10,
        }
        mgr.get_callers.return_value = [{"source": "caller1", "depth": 1}]
        mgr.get_callees.return_value = [{"target": "callee1", "depth": 1}]

        sem_store = MagicMock()

        result = handle_api("/api/node/foo.bar", mgr, sem_store)
        assert result["symbol"] == "foo.bar"
        assert len(result["callers"]) == 1
        assert len(result["callees"]) == 1

    def test_node_not_found(self):
        mgr = MagicMock()
        mgr.get_node.return_value = None
        sem_store = MagicMock()

        with pytest.raises(ValueError, match="node not found"):
            handle_api("/api/node/doesnotexist", mgr, sem_store)


class TestHandleApiStatus:
    def test_status(self):
        mgr = MagicMock()
        mgr.stats.return_value = {
            "file_count": 42,
            "symbol_count": 1000,
            "edge_count": 500,
            "last_updated": "2024-01-01",
        }
        sem_store = MagicMock()
        sem_store.get_coverage.return_value = "50.0% files, 30.0% symbols"

        result = handle_api("/api/status", mgr, sem_store)
        assert result["files"] == 42
        assert result["symbols"] == 1000
        assert result["edges"] == 500
        assert "coverage" in result


class TestHandleApiUnknownEndpoint:
    def test_unknown_endpoint(self):
        mgr = MagicMock()
        sem_store = MagicMock()

        with pytest.raises(ValueError, match="unknown endpoint"):
            handle_api("/api/unknown", mgr, sem_store)


class TestNodeToJson:
    def test_basic(self):
        sem_store = MagicMock()
        sem_store.load_all.return_value = []
        node = {
            "qualified_name": "foo.bar",
            "kind": "function",
            "start_line": 42,
            "file_path": "/src/main.py",
        }
        result = _node_to_json(node, sem_store)
        assert result["id"] == "foo.bar"
        assert result["kind"] == "function"
        assert result["file"] == "/src/main.py"


class TestHandleApiNodeMissingName:
    def test_missing_node_name(self):
        mgr = MagicMock()
        sem_store = MagicMock()

        with pytest.raises(ValueError, match="missing node name"):
            handle_api("/api/node/", mgr, sem_store)


class TestHandleAnnotate:
    def test_missing_file_field(self):
        mgr = MagicMock()
        sem_store = MagicMock()

        with pytest.raises(ValueError, match="missing"):
            handle_annotate({}, mgr, sem_store)

    def test_empty_file_field(self):
        mgr = MagicMock()
        sem_store = MagicMock()

        with pytest.raises(ValueError, match="missing"):
            handle_annotate({"file": ""}, mgr, sem_store)


class TestNodeToJsonWithMissingKeys:
    def test_missing_keys(self):
        sem_store = MagicMock()
        sem_store.load_all.return_value = []
        node = {"qualified_name": "foo.bar"}
        result = _node_to_json(node, sem_store)
        assert result["id"] == "foo.bar"
        assert result["kind"] == "?"
        assert result["line"] == "?"

    def test_finds_file_from_multiple_keys(self):
        sem_store = MagicMock()
        sem_store.load_all.return_value = []
        node = {
            "qualified_name": "foo",
            "kind": "function",
            "start_line": 1,
            "path": "/src/main.py",
        }
        result = _node_to_json(node, sem_store)
        assert result["file"] == "/src/main.py"


class TestDeleteAnnotation:
    def test_delete_existing_annotation(self):
        """Should delete an existing annotation."""
        mgr = MagicMock()
        sem_store = MagicMock()
        sem_store.delete_annotation.return_value = True

        result = handle_delete_annotation(
            {"file": "src/app.py", "symbol": "my_func", "index": 0},
            mgr, sem_store,
        )
        assert result["deleted"] is True
        assert result["file"] == "src/app.py"
        assert result["symbol"] == "my_func"

    def test_delete_nonexistent_annotation(self):
        """Should return deleted=False when annotation not found."""
        mgr = MagicMock()
        sem_store = MagicMock()
        sem_store.delete_annotation.return_value = False

        result = handle_delete_annotation(
            {"file": "src/app.py", "symbol": "nonexistent", "index": 0},
            mgr, sem_store,
        )
        assert result["deleted"] is False

    def test_delete_missing_fields(self):
        """Should raise ValueError when fields are missing."""
        mgr = MagicMock()
        sem_store = MagicMock()

        with pytest.raises(ValueError, match="missing"):
            handle_delete_annotation({"file": "src/app.py"}, mgr, sem_store)

        with pytest.raises(ValueError, match="missing"):
            handle_delete_annotation({"symbol": "foo"}, mgr, sem_store)


class TestHandleHealth:
    """Tests for handle_health, covering /proc/self/status error path."""

    def test_handle_health_proc_error(self):
        """handle_health returns -1 for memory_usage_mb when /proc/self/status is unreadable
        (cover api.py lines 179-180)."""
        import time

        from memorygraph.web.api import handle_health
        mgr = MagicMock()
        mgr.stats.return_value = {"file_count": 5, "symbol_count": 10, "edge_count": 3}
        start_time = time.time()
        # Patch open to raise OSError
        from unittest.mock import patch
        with patch("builtins.open", side_effect=OSError("permission denied")):
            result = handle_health(mgr, start_time, "/tmp/db", {"query_count": 0})
        assert result["memory_usage_mb"] == -1
        assert result["status"] == "ok"
        assert result["file_count"] == 5
        assert result["symbol_count"] == 10

    def test_handle_health_index_rate(self):
        """handle_health computes index_rate when index_count > 0 (lines 201-203)."""
        import time

        from memorygraph.web.api import handle_health
        mgr = MagicMock()
        mgr.stats.return_value = {"file_count": 5, "symbol_count": 10, "edge_count": 3}
        # Set start_time 2 minutes ago so index_rate is 10/2 = 5
        start_time = time.time() - 120
        result = handle_health(mgr, start_time, "/tmp/db",
                               {"index_count": 10, "query_count": 0})
        assert "index_rate_per_minute" in result
        assert result["index_rate_per_minute"] == 5.0

    def test_handle_health_db_error(self):
        """handle_health sets db_status=error when DB ping fails."""
        import time

        from memorygraph.web.api import handle_health
        mgr = MagicMock()
        mgr.stats.return_value = {
            "file_count": 5, "symbol_count": 10, "edge_count": 3, "last_updated": "",
        }
        # DB ping fails
        mgr.get_conn().execute.side_effect = Exception("DB connection lost")
        start_time = time.time()
        result = handle_health(mgr, start_time, "/tmp/db", {"query_count": 0})
        assert result["db_status"] == "error"
        assert result["status"] == "ok"  # still ok overall
