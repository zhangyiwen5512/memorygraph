"""Tests for MCP server tools."""
import asyncio
import json
import os
import tempfile

import pytest
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    ListToolsRequest,
)

from memorygraph.mcp.server import create_memorygraph_server
from memorygraph.storage import StorageManager


@pytest.fixture
def indexed_project():
    """Create a temp project, index it, and return the path."""
    tmpdir = tempfile.mkdtemp()
    src_dir = os.path.join(tmpdir, "src")
    os.makedirs(src_dir)

    with open(os.path.join(src_dir, "app.py"), "w") as f:
        f.write("""def helper(x):
    return x * 2

def main():
    result = helper(21)
    print(result)
""")

    # Index
    mgr = StorageManager(tmpdir)
    mgr.initialize()

    from pathlib import Path

    from memorygraph.parsing.batch import ParallelParser
    from memorygraph.parsing.registry import LanguageRegistry

    registry = LanguageRegistry()
    parser = ParallelParser(registry)

    files = []
    for dirpath, dirnames, filenames in os.walk(tmpdir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(Path(os.path.join(dirpath, fn)))

    results = parser.parse_files(files, resolve_symbols=True)
    for _path, result in results.items():
        if not result.fatal_error:
            mgr.upsert_file(result)

    mgr.close()
    yield tmpdir
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestMCPServerTools:
    """Test MCP server tool registration and execution."""

    def test_server_creation(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        assert server is not None
        assert server.name == "memorygraph"

    def test_list_tools(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        handler = server.request_handlers.get(ListToolsRequest)
        assert handler is not None, "ListToolsRequest handler not registered"

        result = asyncio.run(handler(None))
        # Unwrap ServerResult -> ListToolsResult
        inner = result.root
        tool_names = [t.name for t in inner.tools]
        assert "memorygraph_search" in tool_names
        assert "memorygraph_callers" in tool_names
        assert "memorygraph_callees" in tool_names
        assert "memorygraph_impact" in tool_names
        assert "memorygraph_node" in tool_names
        assert "memorygraph_context" in tool_names
        assert "memorygraph_diff" in tool_names

    def _call_tool(self, server, name: str, arguments: dict):
        """Helper to invoke a tool via the MCP server handler."""
        handler = server.request_handlers.get(CallToolRequest)
        assert handler is not None, "CallToolRequest handler not registered"
        req = CallToolRequest(
            params=CallToolRequestParams(name=name, arguments=arguments)
        )
        result = asyncio.run(handler(req))
        # Unwrap ServerResult
        return result.root

    def test_search_tool(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(server, "memorygraph_search", {"query": "helper"})
        text = result.content[0].text
        data = json.loads(text)
        assert len(data) > 0
        assert any("helper" in str(r) for r in data)

    def test_callers_tool(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(server, "memorygraph_callers", {"symbol": "helper"})
        data = json.loads(result.content[0].text)
        assert len(data) >= 1

    def test_callees_tool(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(server, "memorygraph_callees", {"symbol": "main"})
        data = json.loads(result.content[0].text)
        assert len(data) >= 1

    def test_node_tool_found(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(server, "memorygraph_node", {"symbol": "helper"})
        data = json.loads(result.content[0].text)
        assert data["found"] is True
        assert data["node"]["name"] == "helper"

    def test_node_tool_not_found(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(
            server, "memorygraph_node", {"symbol": "nonexistent_func"}
        )
        data = json.loads(result.content[0].text)
        assert data["found"] is False

    def test_context_tool(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(
            server, "memorygraph_context", {"task": "multiply numbers"}
        )
        data = json.loads(result.content[0].text)
        assert "entry_points" in data
        assert "related" in data
        assert data["task"] == "multiply numbers"

    def test_diff_tool(self, indexed_project):
        server = create_memorygraph_server(indexed_project)

        diff_text = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,3 @@
 def helper(x):
-    return x * 2
+    return x * 3
"""
        result = self._call_tool(
            server, "memorygraph_diff", {"diff": diff_text}
        )
        data = json.loads(result.content[0].text)
        assert "changed_files" in data
        assert "src/app.py" in data["changed_files"]
        assert "affected_symbols" in data

    def test_callers_with_file_path(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        import os
        file_path = os.path.join(indexed_project, "src", "app.py")
        result = self._call_tool(
            server, "memorygraph_callers",
            {"symbol": "helper", "file_path": file_path}
        )
        data = json.loads(result.content[0].text)
        assert isinstance(data, list)

    def test_callees_with_file_path(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        import os
        file_path = os.path.join(indexed_project, "src", "app.py")
        result = self._call_tool(
            server, "memorygraph_callees",
            {"symbol": "main", "file_path": file_path}
        )
        data = json.loads(result.content[0].text)
        assert isinstance(data, list)

    def test_node_with_file_path(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        import os
        file_path = os.path.join(indexed_project, "src", "app.py")
        result = self._call_tool(
            server, "memorygraph_node",
            {"symbol": "helper", "file_path": file_path}
        )
        data = json.loads(result.content[0].text)
        assert data["found"] is True

    def test_semantic_context_tool(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(
            server, "memorygraph_semantic_context",
            {"file": "src/app.py"}
        )
        data = json.loads(result.content[0].text)
        assert isinstance(data, dict)

    def test_annotations_tool(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(
            server, "memorygraph_annotations", {}
        )
        data = json.loads(result.content[0].text)
        assert "annotations" in data

    def test_unknowns_tool(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(
            server, "memorygraph_unknowns", {"limit": 5}
        )
        data = json.loads(result.content[0].text)
        assert "unknowns" in data

    def test_insights_tool(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(
            server, "memorygraph_insights", {"limit": 5}
        )
        data = json.loads(result.content[0].text)
        assert "insights" in data

    def test_search_tool_with_limit(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(
            server, "memorygraph_search",
            {"query": "helper", "limit": 3}
        )
        data = json.loads(result.content[0].text)
        assert len(data) <= 3

    def test_unknown_tool_name(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(
            server, "nonexistent_tool", {}
        )
        text = result.content[0].text
        assert "Unknown tool" in text

    def test_semantic_context_with_file(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        import os
        file_path = os.path.join(indexed_project, "src", "app.py")
        result = self._call_tool(
            server, "memorygraph_semantic_context",
            {"file": file_path}
        )
        data = json.loads(result.content[0].text)
        assert isinstance(data, dict)

    def test_semantic_context_with_symbol(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(
            server, "memorygraph_semantic_context",
            {"symbol": "helper"}
        )
        data = json.loads(result.content[0].text)
        assert isinstance(data, dict)

    def test_annotations_with_file_filter(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        import os
        file_path = os.path.join(indexed_project, "src", "app.py")
        result = self._call_tool(
            server, "memorygraph_annotations",
            {"file": file_path}
        )
        data = json.loads(result.content[0].text)
        assert "annotations" in data

    def test_annotations_with_symbol_filter(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(
            server, "memorygraph_annotations",
            {"symbol": "helper"}
        )
        data = json.loads(result.content[0].text)
        assert "annotations" in data

    def test_diff_with_removed_file(self, indexed_project):
        server = create_memorygraph_server(indexed_project)

        diff_text = """diff --git a/src/old.py b/src/old.py
--- a/src/old.py
+++ b/src/old.py
@@ -1,3 +0,0 @@
-def old_func():
-    pass
"""
        result = self._call_tool(
            server, "memorygraph_diff", {"diff": diff_text}
        )
        data = json.loads(result.content[0].text)
        assert "changed_files" in data

    def test_diff_empty(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(
            server, "memorygraph_diff", {"diff": ""}
        )
        data = json.loads(result.content[0].text)
        assert data.get("changed_files") is not None

    def test_context_with_limit(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(
            server, "memorygraph_context",
            {"task": "helper function", "limit": 3}
        )
        data = json.loads(result.content[0].text)
        assert "entry_points" in data

    def test_impact_tool(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(
            server, "memorygraph_impact",
            {"symbol": "helper", "depth": 2}
        )
        data = json.loads(result.content[0].text)
        assert isinstance(data, list)

    def test_node_tool_includes_file_path(self, indexed_project):
        server = create_memorygraph_server(indexed_project)
        result = self._call_tool(
            server, "memorygraph_node", {"symbol": "helper"}
        )
        data = json.loads(result.content[0].text)
        if data["found"]:
            assert "file_path" in data.get("node", {})
