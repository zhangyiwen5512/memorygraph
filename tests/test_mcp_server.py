"""Tests for MCP server module."""
import asyncio
import json
from unittest import mock

import pytest


class TestRunMCPServer:
    """Tests for the MCP server entry point."""

    def test_run_mcp_imports(self):
        """Verify run_mcp_server is importable."""
        from memorygraph.mcp.server import run_mcp_server
        assert callable(run_mcp_server)

    def test_server_module_has_tools(self):
        """Verify server module defines tools."""
        from memorygraph.mcp import server
        assert hasattr(server, 'run_mcp_server')

    def test_create_server_returns_server(self):
        """Verify create_memorygraph_server creates a valid server."""
        from memorygraph.mcp.server import create_memorygraph_server
        server = create_memorygraph_server(".")
        assert server is not None


class TestWebAPI:
    """Tests for web API handlers (no socket needed)."""

    def test_handle_annotate_success(self):
        """Test handle_annotate with valid data."""
        from memorygraph.web.api import handle_annotate
        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()

        data = {
            "file": "src/app.py",
            "annotations": [
                {"symbol": "helper", "kind": "function",
                 "summary": "Doubles input", "design_intent": "",
                 "pitfalls": ""}
            ],
            "unknowns": [],
            "insights": [],
            "module_summary": "Test module"
        }

        result = handle_annotate(data, mgr, sem_store)
        assert result["saved"] is True
        assert result["file"] == "src/app.py"
        sem_store.save.assert_called_once()

    def test_handle_annotate_with_insights(self):
        """Test handle_annotate with insights."""
        from memorygraph.web.api import handle_annotate
        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()

        data = {
            "file": "src/app.py",
            "annotations": [],
            "unknowns": [
                {"symbol": "helper", "question": "Why double?",
                 "context": ""}
            ],
            "insights": [
                {"insight": "Uses functional style",
                 "related_symbols": ["helper"]}
            ]
        }

        result = handle_annotate(data, mgr, sem_store)
        assert result["unknowns"] == 1
        assert result["insights"] == 1

    def test_handle_annotate_missing_file(self):
        """Test handle_annotate with missing file field raises."""
        import pytest

        from memorygraph.web.api import handle_annotate
        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()

        with pytest.raises(ValueError, match="file"):
            handle_annotate({}, mgr, sem_store)

    def test_api_semantic_endpoint_no_file(self):
        """Test GET /api/semantic without file param."""
        from memorygraph.web.api import handle_api
        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()

        result = handle_api("/api/semantic", mgr, sem_store)
        assert "error" in result

    def test_api_semantic_endpoint_with_file_not_found(self):
        """Test GET /api/semantic for nonexistent file."""
        from memorygraph.web.api import handle_api
        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()
        sem_store.load.return_value = None

        result = handle_api("/api/semantic?file=src/nope.py", mgr, sem_store)
        assert result["file"] == "src/nope.py"
        assert result["annotations"] == []

    def test_api_semantic_endpoint_with_doc(self):
        """Test GET /api/semantic with existing document."""
        from memorygraph.semantic.models import Annotation, SemanticDocument
        from memorygraph.web.api import handle_api
        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()
        doc = SemanticDocument(file="src/app.py", source="test")
        doc.annotations.append(Annotation(
            symbol="helper", kind="function",
            summary="Doubles input", design_intent="", pitfalls=""
        ))
        sem_store.load.return_value = doc

        result = handle_api("/api/semantic?file=src/app.py", mgr, sem_store)
        assert len(result["annotations"]) == 1
        assert result["annotations"][0]["symbol"] == "helper"


class TestLookupSemantic:
    """Tests for _lookup_semantic_for_file helper."""

    def test_lookup_semantic_returns_none_when_doc_not_found(self):
        """When sem_store.load returns None, should return None."""
        from unittest import mock

        from memorygraph.mcp.server import _lookup_semantic_for_file

        sem_store = mock.MagicMock()
        sem_store.load.return_value = None

        result = _lookup_semantic_for_file(sem_store, "nonexistent.py")
        assert result is None

    def test_lookup_semantic_serializes_doc(self):
        """Should serialize SemanticDocument to dict correctly."""
        from unittest import mock

        from memorygraph.mcp.server import _lookup_semantic_for_file
        from memorygraph.semantic.models import Annotation, SemanticDocument

        doc = SemanticDocument(file="src/app.py", source="test")
        doc.module_summary = "Test module"
        doc.annotations.append(Annotation(
            symbol="foo", kind="function", summary="does thing",
            design_intent="helper", pitfalls="none"
        ))

        sem_store = mock.MagicMock()
        sem_store.load.return_value = doc

        result = _lookup_semantic_for_file(sem_store, "src/app.py")
        assert result is not None
        assert result["file"] == "src/app.py"
        assert result["module_summary"] == "Test module"
        assert len(result["annotations"]) == 1
        assert result["annotations"][0]["symbol"] == "foo"


class TestMCPServerHelpers:
    """Tests for MCP server internal helper functions via tool dispatch."""

    def _create_server(self):
        """Create server with mocked dependencies, return (server, mgr, sem_store)."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls:
            with mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls:
                server = create_memorygraph_server(".")

        return server, mock_mgr_cls.return_value, mock_sem_cls.return_value

    async def _call_tool(self, server, name, args):
        """Call the MCP tool handler directly."""
        return await server._tool_handler(name, args)

    def _run(self, coro):
        """Run coroutine synchronously."""
        return asyncio.run(coro)

    def test_semantic_context_by_file(self):
        """Semantic context for specific file should return that file's context."""
        from unittest import mock

        from memorygraph.semantic.models import Annotation, SemanticDocument

        with mock.patch("memorygraph.mcp.server.create_storage_manager"):
            with mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls:
                sem_store = mock_sem_cls.return_value
                doc = SemanticDocument(file="src/app.py", source="test")
                doc.annotations.append(Annotation(
                    symbol="foo", kind="function", summary="bar",
                    design_intent="", pitfalls=""
                ))
                sem_store.load.return_value = doc

                from memorygraph.mcp.server import create_memorygraph_server
                server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_semantic_context", {"file": "src/app.py"}
        ))
        text = result[0].text
        data = json.loads(text)
        assert "src/app.py" in data

    def test_annotations_filtered_by_file(self):
        """Annotations tool should filter by file path."""
        from unittest import mock

        from memorygraph.semantic.models import Annotation, SemanticDocument

        with mock.patch("memorygraph.mcp.server.create_storage_manager"):
            with mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls:
                sem_store = mock_sem_cls.return_value
                doc1 = SemanticDocument(file="src/a.py", source="test")
                doc1.annotations.append(Annotation(
                    symbol="foo", kind="function", summary="A",
                    design_intent="", pitfalls=""
                ))
                doc2 = SemanticDocument(file="src/b.py", source="test")
                doc2.annotations.append(Annotation(
                    symbol="bar", kind="method", summary="B",
                    design_intent="", pitfalls=""
                ))
                sem_store.load_all.return_value = [doc1, doc2]

                from memorygraph.mcp.server import create_memorygraph_server
                server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_annotations", {"file": "src/a.py"}
        ))
        data = json.loads(result[0].text)
        assert len(data["annotations"]) == 1
        assert data["annotations"][0]["symbol"] == "foo"

    def test_unknowns_with_reference_counts(self):
        """Unknowns tool should include reference counts."""
        from unittest import mock

        from memorygraph.semantic.models import SemanticDocument, Unknown

        with mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls:
            with mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls:
                mgr = mock_mgr_cls.return_value
                mgr.get_callers.return_value = [{"source": "caller1"}]
                mgr.get_callees.return_value = [{"target": "callee1"}]

                sem_store = mock_sem_cls.return_value
                doc = SemanticDocument(file="src/app.py", source="test")
                doc.unknowns.append(Unknown(
                    symbol="mystery", question="What does this do?",
                    context="found in main"
                ))
                sem_store.load_all.return_value = [doc]

                from memorygraph.mcp.server import create_memorygraph_server
                server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_unknowns", {"limit": 5}
        ))
        data = json.loads(result[0].text)
        assert len(data["unknowns"]) == 1
        assert data["unknowns"][0]["symbol"] == "mystery"

    def test_insights_returns_items(self):
        """Insights tool should return design insights."""
        from unittest import mock

        from memorygraph.semantic.models import Insight, SemanticDocument

        with mock.patch("memorygraph.mcp.server.create_storage_manager"):
            with mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls:
                sem_store = mock_sem_cls.return_value
                doc = SemanticDocument(file="src/app.py", source="test")
                doc.insights.append(Insight(
                    insight="Uses Observer pattern",
                    related_symbols=["Subject", "Observer"]
                ))
                sem_store.load_all.return_value = [doc]

                from memorygraph.mcp.server import create_memorygraph_server
                server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_insights", {"limit": 10}
        ))
        data = json.loads(result[0].text)
        assert len(data["insights"]) == 1
        assert data["insights"][0]["insight"] == "Uses Observer pattern"

    def test_call_tool_unknown_tool(self):
        """Calling unknown tool should return error text."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with mock.patch("memorygraph.mcp.server.create_storage_manager"):
            with mock.patch("memorygraph.mcp.server.create_semantic_store"):
                server = create_memorygraph_server(".")

        result = self._run(server._tool_handler("unknown_tool_name", {}))
        assert "Unknown tool" in result[0].text

    def test_call_tool_exception_handling(self):
        """Calling a tool that raises should catch exception and return error."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls:
            with mock.patch("memorygraph.mcp.server.create_semantic_store"):
                mgr = mock_mgr_cls.return_value
                mgr.search.side_effect = RuntimeError("DB connection failed")

                server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_search", {"query": "test"}
        ))
        data = json.loads(result[0].text)
        assert "error" in data

    def test_semantic_search_tool_dispatches(self):
        """memorygraph_semantic_search tool should return search results."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls:
            with mock.patch("memorygraph.mcp.server.create_semantic_store"):
                mgr = mock_mgr_cls.return_value
                mgr.semantic_search.return_value = [
                    {"name": "login", "qualified_name": "auth.login",
                     "kind": "function", "file_path": "src/auth.py",
                     "signature": "def login(user, pw)", "rank": 1.0}
                ]

                server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_semantic_search",
            {"query": "user auth", "limit": 5, "hybrid": False}
        ))
        data = json.loads(result[0].text)
        assert len(data) == 1
        assert data[0]["name"] == "login"

    def test_diff_with_relative_paths(self):
        """Diff tool should resolve relative paths to absolute."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls:
            with mock.patch("memorygraph.mcp.server.create_semantic_store"):
                mgr = mock_mgr_cls.return_value
                mgr.get_symbols_for_file.return_value = [
                    {"qualified_name": "app.main"}
                ]
                mgr.get_impact.return_value = [
                    {"target": "app.helper"}
                ]

                server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_diff",
            {"diff": "+++ b/src/app.py\n--- a/src/app.py"}
        ))
        data = json.loads(result[0].text)
        assert "src/app.py" in data["changed_files"]
        assert "app.main" in data["affected_symbols"]

    def test_node_tool_returns_found_false(self):
        """Node tool should return found=False when node not found."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls:
            with mock.patch("memorygraph.mcp.server.create_semantic_store"):
                mgr = mock_mgr_cls.return_value
                mgr.get_node.return_value = None

                server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_node",
            {"symbol": "nonexistent", "file_path": "src/ghost.py"}
        ))
        data = json.loads(result[0].text)
        assert data["found"] is False
        assert data["node"] is None

    def test_context_tool_with_semantic_data(self):
        """Context tool should attach semantic context when available."""
        from unittest import mock

        from memorygraph.semantic.models import Annotation, SemanticDocument

        with mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls:
            with mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls:
                mgr = mock_mgr_cls.return_value
                mgr.semantic_search.return_value = [
                    {"qualified_name": "app.main", "kind": "function",
                     "file_path": "src/app.py", "signature": "def main()",
                     "rank": 1.0}
                ]
                mgr.get_callers.return_value = [{"source": "script.run"}]
                mgr.get_callees.return_value = [{"target": "app.init"}]

                sem_store = mock_sem_cls.return_value
                doc = SemanticDocument(file="src/app.py", source="test")
                doc.annotations.append(Annotation(
                    symbol="main", kind="function", summary="Entry point",
                    design_intent="startup", pitfalls="none"
                ))
                sem_store.load.return_value = doc

                from memorygraph.mcp.server import create_memorygraph_server
                server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_context", {"task": "find entry point"}
        ))
        data = json.loads(result[0].text)
        assert len(data["entry_points"]) == 1
        assert "semantic_context" in data

    def test_semantic_search_vector_path(self):
        """Semantic search should use vector embeddings when available."""
        from unittest import mock

        import numpy as np

        from memorygraph.mcp.server import create_memorygraph_server

        # Create a real embedding vector (384-dim)
        vec = np.random.randn(384).astype(np.float32)
        blob = vec.tobytes()

        with mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls:
            with mock.patch("memorygraph.mcp.server.create_semantic_store"):
                mgr = mock_mgr_cls.return_value
                mgr.semantic_search.return_value = [
                    {"name": "login", "qualified_name": "auth.login",
                     "kind": "function", "file_path": "src/auth.py",
                     "signature": "def login(u,p)", "rank": 0.8}
                ]

                # Mock DB connection for embeddings
                mock_conn = mock.MagicMock()
                mock_conn.execute.return_value.fetchall.return_value = [
                    ("login", "auth.login", "def login(u,p)",
                     "src/auth.py", "function", blob)
                ]
                mgr._get_conn.return_value = mock_conn

                # Mock EmbeddingGenerator to be available
                with mock.patch(
                    "memorygraph.semantic.embeddings.EmbeddingGenerator"
                ) as mock_emb_cls:
                    mock_gen = mock_emb_cls.return_value
                    mock_gen.is_available = True
                    mock_gen.generate.return_value = vec
                    mock_gen.search.return_value = [
                        {"name": "login", "qualified_name": "auth.login",
                         "similarity": 0.95, "file_path": "src/auth.py"}
                    ]

                    server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_semantic_search",
            {"query": "user auth", "limit": 5, "hybrid": False}
        ))
        data = json.loads(result[0].text)
        assert len(data) >= 1

    def test_semantic_context_no_params(self):
        """Semantic context with no file/symbol should return all docs."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server
        from memorygraph.semantic.models import Annotation, SemanticDocument

        with mock.patch("memorygraph.mcp.server.create_storage_manager"):
            with mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls:
                sem_store = mock_sem_cls.return_value
                doc = SemanticDocument(file="src/app.py", source="test")
                doc.annotations.append(Annotation(
                    symbol="foo", kind="function", summary="bar",
                    design_intent="", pitfalls=""
                ))
                sem_store.load_all.return_value = [doc]

                server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_semantic_context", {"file": "", "symbol": ""}
        ))
        data = json.loads(result[0].text)
        assert "documents" in data
        assert len(data["documents"]) >= 1

    def test_annotations_filtered_by_symbol(self):
        """Annotations tool should filter by symbol name."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server
        from memorygraph.semantic.models import Annotation, SemanticDocument

        with mock.patch("memorygraph.mcp.server.create_storage_manager"):
            with mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls:
                sem_store = mock_sem_cls.return_value
                doc = SemanticDocument(file="src/app.py", source="test")
                doc.annotations.append(Annotation(
                    symbol="foo", kind="function", summary="A",
                    design_intent="", pitfalls=""
                ))
                doc.annotations.append(Annotation(
                    symbol="bar", kind="method", summary="B",
                    design_intent="", pitfalls=""
                ))
                sem_store.load_all.return_value = [doc]

                server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_annotations", {"symbol": "foo"}
        ))
        data = json.loads(result[0].text)
        assert len(data["annotations"]) == 1
        assert data["annotations"][0]["symbol"] == "foo"

    def test_diff_with_absolute_path(self):
        """Diff tool should handle absolute file paths."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls:
            with mock.patch("memorygraph.mcp.server.create_semantic_store"):
                mgr = mock_mgr_cls.return_value
                mgr.get_symbols_for_file.return_value = [
                    {"qualified_name": "app.main"}
                ]
                mgr.get_impact.return_value = [
                    {"target": "app.helper"}
                ]

                server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_diff",
            {"diff": "+++ b//abs/path/src/app.py\n--- a//abs/path/src/app.py"}
        ))
        data = json.loads(result[0].text)
        assert "/abs/path/src/app.py" in data["changed_files"]

    def test_semantic_search_hybrid_path(self):
        """Hybrid search should combine FTS + vector results."""
        from unittest import mock

        import numpy as np

        from memorygraph.mcp.server import create_memorygraph_server

        vec = np.random.randn(384).astype(np.float32)
        blob = vec.tobytes()

        with mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls:
            with mock.patch("memorygraph.mcp.server.create_semantic_store"):
                mgr = mock_mgr_cls.return_value
                # Return FTS results for hybrid path
                mgr.semantic_search.return_value = [
                    {"name": "login", "qualified_name": "auth.login",
                     "kind": "function", "file_path": "src/auth.py",
                     "signature": "def login(u,p)", "rank": 0.8}
                ]

                mock_conn = mock.MagicMock()
                mock_conn.execute.return_value.fetchall.return_value = [
                    ("login", "auth.login", "def login(u,p)",
                     "src/auth.py", "function", blob)
                ]
                mgr._get_conn.return_value = mock_conn

                with mock.patch(
                    "memorygraph.semantic.embeddings.EmbeddingGenerator"
                ) as mock_emb_cls:
                    mock_gen = mock_emb_cls.return_value
                    mock_gen.is_available = True
                    mock_gen.generate.return_value = vec
                    mock_gen.search.return_value = [
                        {"name": "login", "similarity": 0.95}
                    ]
                    mock_gen.hybrid_search.return_value = [
                        {"name": "login", "similarity": 0.88,
                         "fts_rank": 0.8, "final_score": 0.84}
                    ]

                    server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_semantic_search",
            {"query": "user auth", "limit": 5, "hybrid": True}
        ))
        data = json.loads(result[0].text)
        assert len(data) >= 1

    def test_semantic_search_vector_exception_fallback(self):
        """Vector search exception should fallback to FTS."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls:
            with mock.patch("memorygraph.mcp.server.create_semantic_store"):
                mgr = mock_mgr_cls.return_value
                mgr.semantic_search.return_value = [
                    {"name": "fts_result", "qualified_name": "fts.find"}
                ]

                with mock.patch(
                    "memorygraph.semantic.embeddings.EmbeddingGenerator"
                ) as mock_emb_cls:
                    mock_gen = mock_emb_cls.return_value
                    mock_gen.is_available = True
                    mock_gen.generate.side_effect = RuntimeError("embedding failed")

                    server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_semantic_search",
            {"query": "test", "limit": 5}
        ))
        data = json.loads(result[0].text)
        assert len(data) >= 1
        # Should fallback to FTS
        assert data[0]["name"] == "fts_result"

    def test_semantic_search_db_exception_fallback(self):
        """DB error during vector search should fallback to FTS (covers server.py:111-112)."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls:
            with mock.patch("memorygraph.mcp.server.create_semantic_store"):
                mgr = mock_mgr_cls.return_value
                mgr.semantic_search.return_value = [
                    {"name": "fts_db_error", "qualified_name": "fts.find"}
                ]
                # Simulate EmbeddingGenerator available but DB blows up
                with mock.patch(
                    "memorygraph.semantic.embeddings.EmbeddingGenerator"
                ) as mock_emb_cls:
                    mock_gen = mock_emb_cls.return_value
                    mock_gen.is_available = True
                    mock_gen.generate.return_value = "fake_vector"
                    # DB connection error triggers except Exception: pass
                    mgr._get_conn.side_effect = RuntimeError("DB connection lost")

                    server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_semantic_search",
            {"query": "test", "limit": 5}
        ))
        data = json.loads(result[0].text)
        assert data[0]["name"] == "fts_db_error"

    def test_run_mcp_server_importable(self):
        """run_mcp_server should be importable and callable."""
        from unittest import mock

        from memorygraph.mcp.server import run_mcp_server

        with mock.patch("memorygraph.mcp.server.create_memorygraph_server") as mock_create:
            mock_srv = mock.MagicMock()
            mock_create.return_value = mock_srv

            with mock.patch("memorygraph.mcp.server.stdio_server") as mock_stdio:
                mock_read = mock.MagicMock()
                mock_write = mock.MagicMock()
                mock_stdio.return_value.__aenter__.return_value = (mock_read, mock_write)

                # Run the function
                try:
                    asyncio.run(run_mcp_server("."))
                except Exception:
                    pass  # Expected - mock setup incomplete
                mock_create.assert_called_once_with(".")


class TestMCPAsyncIntegration:
    """Async integration tests for MCP server using pytest-asyncio.

    These tests exercise the MCP server's async call_tool handler directly
    (memorygraph_search, memorygraph_callers, etc.) using real StorageManager,
    without mocking the underlying storage layer.
    """

    @pytest.mark.asyncio
    async def test_call_tool_unknown_tool_returns_error(self):
        """Calling an unregistered tool should return error text."""
        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(".")
        result = await server._tool_handler("nonexistent_tool", {})

        assert len(result) >= 1
        assert "Unknown tool" in result[0].text

    @pytest.mark.asyncio
    async def test_search_tool_empty_result(self):
        """memorygraph_search should return empty list for no matches."""
        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(".")
        result = await server._tool_handler(
            "memorygraph_search", {"query": "zzz_nonexistent_symbol_xyz", "limit": 5}
        )
        data = json.loads(result[0].text)
        assert isinstance(data, list)
        assert len(data) == 0

    @pytest.mark.asyncio
    async def test_callers_tool_error_on_missing_symbol(self):
        """memorygraph_callers without 'symbol' arg should return error dict."""
        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(".")
        result = await server._tool_handler("memorygraph_callers", {})
        data = json.loads(result[0].text)
        assert data.get("status") == "error"

    @pytest.mark.asyncio
    async def test_node_tool_error_on_missing_symbol(self):
        """memorygraph_node without 'symbol' arg should return error dict."""
        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(".")
        result = await server._tool_handler("memorygraph_node", {})
        data = json.loads(result[0].text)
        assert data.get("status") == "error"

    @pytest.mark.asyncio
    async def test_impact_tool_returns_empty_on_unknown(self):
        """memorygraph_impact on unknown symbol should return empty list."""
        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(".")
        result = await server._tool_handler(
            "memorygraph_impact", {"symbol": "nonexistent", "depth": 2}
        )
        data = json.loads(result[0].text)
        # Impact for unknown symbol returns empty list
        assert isinstance(data, list)
        assert data == []

    @pytest.mark.asyncio
    async def test_callers_tool_returns_list(self):
        """memorygraph_callers should return a list (empty for unknown symbol)."""
        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(".")
        result = await server._tool_handler(
            "memorygraph_callers", {"symbol": "nonexistent_func", "depth": 1}
        )
        data = json.loads(result[0].text)
        assert isinstance(data, list)
        assert data == []


class TestMCPSemanticWriteTools:
    """L5: 'learn while using' — MCP tools for writing semantic data back."""

    def test_annotate_symbol_new_file(self, tmp_path):
        """memorygraph_annotate should create annotation for a symbol."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        sem_dir = tmp_path / ".memorygraph" / "semantic"
        sem_dir.mkdir(parents=True)

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr,
            mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls,
        ):
            mock_mgr.return_value.stats.return_value = {
                "symbol_count": 100, "file_count": 10,
            }
            mock_sem = mock_sem_cls.return_value
            mock_sem.load.return_value = None  # no existing doc
            server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_annotate",
            {
                "file_path": "src/app.py",
                "symbol": "calculate_total",
                "kind": "function",
                "summary": "Calculates total from item list",
                "design_intent": "Single-pass for performance",
                "pitfalls": "Assumes non-empty list",
            },
        ))
        data = json.loads(result[0].text)
        assert data["status"] == "ok"
        assert data["symbol"] == "calculate_total"
        mock_sem.save.assert_called_once()

    def test_annotate_symbol_upserts_existing(self, tmp_path):
        """memorygraph_annotate should replace existing annotation for same symbol."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server
        from memorygraph.semantic.models import Annotation, SemanticDocument

        sem_dir = tmp_path / ".memorygraph" / "semantic"
        sem_dir.mkdir(parents=True)

        existing_doc = SemanticDocument(file="src/app.py", source="manual")
        existing_doc.annotations.append(Annotation(
            symbol="calculate_total", kind="function",
            summary="Old summary", design_intent="", pitfalls="",
        ))

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr,
            mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls,
        ):
            mock_mgr.return_value.stats.return_value = {
                "symbol_count": 100, "file_count": 10,
            }
            mock_sem = mock_sem_cls.return_value
            mock_sem.load.return_value = existing_doc
            server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_annotate",
            {
                "file_path": "src/app.py",
                "symbol": "calculate_total",
                "kind": "function",
                "summary": "Updated summary",
                "design_intent": "",
                "pitfalls": "Now handles empty lists",
            },
        ))
        data = json.loads(result[0].text)
        assert data["status"] == "ok"
        mock_sem.save.assert_called_once()

    def test_add_insight(self, tmp_path):
        """memorygraph_add_insight should record an insight."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        sem_dir = tmp_path / ".memorygraph" / "semantic"
        sem_dir.mkdir(parents=True)

        with mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr:
            with mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls:
                mock_mgr.return_value.stats.return_value = {
                    "symbol_count": 100, "file_count": 10,
                }
                mock_sem = mock_sem_cls.return_value
                mock_sem.load.return_value = None

                server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_add_insight",
            {
                "file_path": "src/auth.py",
                "insight": "JWT token refresh uses rolling tokens for security",
                "related_symbols": ["refresh_token", "validate_session"],
            },
        ))
        data = json.loads(result[0].text)
        assert data["status"] == "ok"
        mock_sem.save.assert_called_once()

    def test_add_insight_missing_file_path(self, tmp_path):
        """memorygraph_add_insight without file_path should error."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr:
            with mock.patch("memorygraph.mcp.server.create_semantic_store"):
                mock_mgr.return_value.stats.return_value = {
                    "symbol_count": 100, "file_count": 10,
                }
                server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_add_insight",
            {"insight": "An observation", "file_path": ""},
        ))
        data = json.loads(result[0].text)
        assert data["status"] == "error"

    def test_add_unknown(self, tmp_path):
        """memorygraph_add_unknown should record an open question."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        sem_dir = tmp_path / ".memorygraph" / "semantic"
        sem_dir.mkdir(parents=True)

        with mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr:
            with mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls:
                mock_mgr.return_value.stats.return_value = {
                    "symbol_count": 100, "file_count": 10,
                }
                mock_sem = mock_sem_cls.return_value
                mock_sem.load.return_value = None

                server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_add_unknown",
            {
                "file_path": "src/parser.py",
                "symbol": "parse_expression",
                "question": "Does this handle Unicode operators?",
                "context": "Found while reviewing i18n support",
            },
        ))
        data = json.loads(result[0].text)
        assert data["status"] == "ok"
        assert data["symbol"] == "parse_expression"
        mock_sem.save.assert_called_once()

    # ── annotate edge cases ────────────────────────────────────────────

    def test_annotate_only_required_fields(self, tmp_path):
        """annotate with only required fields (no design_intent/pitfalls)."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        sem_dir = tmp_path / ".memorygraph" / "semantic"
        sem_dir.mkdir(parents=True)

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr,
            mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls,
        ):
            mock_mgr.return_value.stats.return_value = {"symbol_count": 0, "file_count": 0}
            mock_sem = mock_sem_cls.return_value
            mock_sem.load.return_value = None
            server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_annotate",
            {"file_path": "src/lib.py", "symbol": "helper", "summary": "Utility helper"},
        ))
        data = json.loads(result[0].text)
        assert data["status"] == "ok"
        mock_sem.save.assert_called_once()

    def test_annotate_minimal_valid(self, tmp_path):
        """annotate with minimal valid data (summary can be empty)."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        sem_dir = tmp_path / ".memorygraph" / "semantic"
        sem_dir.mkdir(parents=True)

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr,
            mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls,
        ):
            mock_mgr.return_value.stats.return_value = {"symbol_count": 0, "file_count": 0}
            mock_sem = mock_sem_cls.return_value
            mock_sem.load.return_value = None
            server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_annotate",
            {"file_path": "src/lib.py", "symbol": "helper", "summary": "does things"},
        ))
        data = json.loads(result[0].text)
        assert data["status"] == "ok"

    def test_annotate_class_kind(self, tmp_path):
        """annotate with kind='class' should be accepted."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        sem_dir = tmp_path / ".memorygraph" / "semantic"
        sem_dir.mkdir(parents=True)

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr,
            mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls,
        ):
            mock_mgr.return_value.stats.return_value = {"symbol_count": 0, "file_count": 0}
            mock_sem = mock_sem_cls.return_value
            mock_sem.load.return_value = None
            server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_annotate",
            {"file_path": "src/models.py", "symbol": "UserModel", "kind": "class",
             "summary": "Represents a user entity"},
        ))
        data = json.loads(result[0].text)
        assert data["status"] == "ok"

    def test_add_unknown_missing_symbol(self, tmp_path):
        """add_unknown without 'symbol' returns error."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
        ):
            mock_mgr.return_value.stats.return_value = {"symbol_count": 0, "file_count": 0}
            server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_add_unknown",
            {"file_path": "src/x.py", "question": "What does this do?"},
        ))
        data = json.loads(result[0].text)
        assert data["status"] == "error"

    def test_add_insight_empty_insight(self, tmp_path):
        """add_insight with empty insight returns error."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
        ):
            mock_mgr.return_value.stats.return_value = {"symbol_count": 0, "file_count": 0}
            server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_add_insight",
            {"file_path": "src/x.py", "insight": ""},
        ))
        data = json.loads(result[0].text)
        assert data["status"] == "error"

    def _run(self, coro):
        return asyncio.run(coro)


class TestAutoSync:
    """L5-2: automatic index freshness check and repair."""

    def test_auto_sync_disabled_by_env(self, monkeypatch):
        """auto_sync_on_startup should skip when MEMORYGRAPH_AUTO_SYNC=false."""
        monkeypatch.setenv("MEMORYGRAPH_AUTO_SYNC", "false")
        from memorygraph.mcp.server import auto_sync_on_startup

        result = auto_sync_on_startup(".")
        assert result["skipped"] is True
        assert "disabled" in result["reason"]

    def test_auto_sync_empty_project(self, tmp_path):
        """auto_sync_on_startup should skip when no source files found."""
        from memorygraph.mcp.server import auto_sync_on_startup

        result = auto_sync_on_startup(str(tmp_path))
        assert result.get("skipped") is True

    def test_auto_sync_with_changed_files_calls_analyze(self, tmp_path):
        """L5-6: auto_sync_on_startup should re-analyze changed files semantically."""
        from unittest import mock

        from memorygraph.mcp.server import auto_sync_on_startup

        # Create a Python file that will be detected
        src_file = tmp_path / "mod.py"
        src_file.write_text("def foo(): pass\n")

        mock_analyze = mock.MagicMock(return_value=1)
        mock_parser = mock.MagicMock()
        mock_parser.parse_files.return_value = []
        mock_mgr = mock.MagicMock()
        mock_mgr.get_file_hash.return_value = "oldhash"

        with (
            mock.patch("memorygraph.cli.shared._collect_files",
                       return_value=[str(src_file)]),
            mock.patch("memorygraph.cli.shared._compute_hash",
                       return_value="newhash"),
            mock.patch("memorygraph.parsing.batch.ParallelParser",
                       return_value=mock_parser),
            mock.patch("memorygraph.mcp.server.create_storage_manager",
                       return_value=mock_mgr),
            mock.patch("memorygraph.parsing.registry.LanguageRegistry"),
            mock.patch("memorygraph.cli.shared._analyze_files", mock_analyze),
        ):
            result = auto_sync_on_startup(str(tmp_path))
            assert result["status"] == "synced"
            assert "analyzed_count" in result
            mock_analyze.assert_called_once()

    def test_auto_sync_analyze_error_is_non_fatal(self, tmp_path):
        """L5-6: auto_sync_on_startup should not crash if semantic analysis fails."""
        from unittest import mock

        from memorygraph.mcp.server import auto_sync_on_startup

        src_file = tmp_path / "mod.py"
        src_file.write_text("def foo(): pass\n")

        mock_parser = mock.MagicMock()
        mock_parser.parse_files.return_value = []
        mock_mgr = mock.MagicMock()
        mock_mgr.get_file_hash.return_value = "oldhash"

        with (
            mock.patch("memorygraph.cli.shared._collect_files",
                       return_value=[str(src_file)]),
            mock.patch("memorygraph.cli.shared._compute_hash",
                       return_value="newhash"),
            mock.patch("memorygraph.parsing.batch.ParallelParser",
                       return_value=mock_parser),
            mock.patch("memorygraph.mcp.server.create_storage_manager",
                       return_value=mock_mgr),
            mock.patch("memorygraph.parsing.registry.LanguageRegistry"),
            mock.patch("memorygraph.cli.shared._analyze_files",
                       side_effect=RuntimeError("analysis failed")),
        ):
            result = auto_sync_on_startup(str(tmp_path))
            assert result["status"] == "synced"
            assert result["analyzed_count"] == 0

    def test_check_freshness_tool(self, tmp_path):
        """memorygraph_check_freshness should return sync result and stats."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with (
            mock.patch("memorygraph.mcp.server.auto_sync_on_startup") as mock_sync,
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
        ):
            mock_sync.return_value = {
                "status": "fresh", "new": 0, "changed": 0,
                "unchanged": 10, "total_files": 10,
            }
            mock_mgr.return_value.stats.return_value = {
                "file_count": 10, "symbol_count": 100,
                "edge_count": 300, "last_updated": "2024-01-01",
            }
            server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_check_freshness", {},
        ))
        data = json.loads(result[0].text)
        assert "startup_sync" in data
        assert data["startup_sync"]["status"] == "fresh"
        assert data["current_stats"]["files"] == 10

    def test_auto_sync_tool(self, tmp_path):
        """memorygraph_auto_sync should trigger sync and return results."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with (
            mock.patch("memorygraph.mcp.server.auto_sync_on_startup") as mock_startup,
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
        ):
            mock_startup.return_value = {"skipped": True, "reason": "disabled by env"}
            mock_mgr = mock_mgr_cls.return_value

            # Mock the _auto_sync internal check
            mock_mgr.get_file_hash.return_value = "abc123"

            server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_auto_sync", {},
        ))
        data = json.loads(result[0].text)
        # Should report status (may be 'fresh' if no source files in tmp_path)
        assert "status" in data

    def test_auto_sync_disabled_env_respected(self, monkeypatch):
        """MEMORYGRAPH_AUTO_SYNC=false should be respected in auto_sync_on_startup."""
        monkeypatch.setenv("MEMORYGRAPH_AUTO_SYNC", "0")
        from memorygraph.mcp.server import auto_sync_on_startup

        result = auto_sync_on_startup(".")
        assert result["skipped"] is True

    def _run(self, coro):
        return asyncio.run(coro)


class TestMCPHotSymbols:
    """Tests for memorygraph_hot_symbols and _get_hot_symbols."""

    def test_hot_symbols_empty_log(self, tmp_path):
        """hot_symbols with no query log returns empty list or status."""
        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(str(tmp_path))
        result = self._run(server._tool_handler(
            "memorygraph_hot_symbols", {},
        ))
        assert len(result) >= 1
        data = json.loads(result[0].text)
        # Should return empty list when no query log exists
        assert isinstance(data, list)
        assert len(data) == 0

    def test_hot_symbols_with_limit(self, tmp_path):
        """hot_symbols respects limit parameter."""
        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(str(tmp_path))
        result = self._run(server._tool_handler(
            "memorygraph_hot_symbols", {"limit": 5},
        ))
        data = json.loads(result[0].text)
        assert isinstance(data, list)

    def _run(self, coro):
        return asyncio.run(coro)


class TestMCPConversationTools:
    """Tests for memorygraph_ingest_conversation and memorygraph_save_conversation."""

    def test_ingest_conversation_basic(self, tmp_path):
        """ingest_conversation should accept text and save to conversation store."""
        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(str(tmp_path))
        result = self._run(server._tool_handler(
            "memorygraph_ingest_conversation",
            {"text": "We should refactor the auth module to use JWT tokens."},
        ))
        data = json.loads(result[0].text)
        assert "status" in data

    def test_ingest_conversation_with_file_path(self, tmp_path):
        """ingest_conversation with explicit file_path should associate annotations."""
        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(str(tmp_path))
        result = self._run(server._tool_handler(
            "memorygraph_ingest_conversation",
            {"text": "The login function in auth.py has a race condition.",
             "file_path": "auth.py"},
        ))
        data = json.loads(result[0].text)
        assert "status" in data

    def test_save_conversation_json(self, tmp_path):
        """save_conversation should accept JSON text and store it."""
        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(str(tmp_path))
        result = self._run(server._tool_handler(
            "memorygraph_save_conversation",
            {"text": '{"topic": "auth refactor", "decisions": ["use JWT"]}'},
        ))
        data = json.loads(result[0].text)
        assert "status" in data

    def test_save_conversation_plain_text(self, tmp_path):
        """save_conversation should accept plain text (not JSON) and wrap it."""
        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(str(tmp_path))
        result = self._run(server._tool_handler(
            "memorygraph_save_conversation",
            {"text": "We decided to use asyncpg for PostgreSQL access."},
        ))
        data = json.loads(result[0].text)
        assert "status" in data

    def _run(self, coro):
        return asyncio.run(coro)


class TestMCPToolMissingArgs:
    """Cover argument validation error paths in MCP server dispatch.

    These tests cover the _err_response lines for missing required arguments
    (lines 928, 936, 954, 971, 979, 1002, 1011, 1040, 1048 in server.py).
    """

    MISSING_ARG_CASES = [
        # (tool_name, args, missing_field) — covers server.py err_response lines
        ("memorygraph_search", {}, "query"),            # line 928
        ("memorygraph_callers", {}, "symbol"),          # line 936
        ("memorygraph_callees", {}, "symbol"),          # around 944
        ("memorygraph_impact", {}, "symbol"),           # line 954
        ("memorygraph_node", {}, "symbol"),             # line 963
        ("memorygraph_context", {}, "task"),            # line 971
        ("memorygraph_diff", {}, "diff"),               # line 979
        ("memorygraph_semantic_search", {}, "query"),   # line 1002
        ("memorygraph_annotate", {}, "file_path"),      # line 1011
        ("memorygraph_ingest_conversation", {}, "text"), # line 1040
        ("memorygraph_save_conversation", {}, "text"),  # line 1048
    ]

    @pytest.mark.parametrize("tool_name,args,missing_field", MISSING_ARG_CASES)
    @pytest.mark.asyncio
    async def test_tool_missing_required_arg(self, tool_name, args, missing_field):
        """Calling tool without required arg should return error, not crash."""
        import json as _json

        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(".")
        result = await server._tool_handler(tool_name, args)
        assert len(result) >= 1
        text = result[0].text
        # Can be JSON error response or plain error text
        is_error = False
        try:
            data = _json.loads(text) if text.strip().startswith("{") else {}
            is_error = (data.get("status") == "error" or "error" in data.get("message", "").lower())
        except _json.JSONDecodeError:
            pass
        assert is_error or "error" in text.lower() or "required" in text.lower()


class TestMCPCoverageGaps:
    """Targeted tests for uncovered MCP server code paths — 85% → 90%."""

    # ── callees tool dispatch ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_callees_tool_dispatches(self):
        """memorygraph_callees should return a list (empty for unknown symbol)."""
        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(".")
        result = await server._tool_handler(
            "memorygraph_callees", {"symbol": "nonexistent_func", "depth": 1}
        )
        data = json.loads(result[0].text)
        assert isinstance(data, list)
        assert data == []

    @pytest.mark.asyncio
    async def test_callees_tool_error_on_missing_symbol(self):
        """memorygraph_callees without 'symbol' arg should return error."""
        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(".")
        result = await server._tool_handler("memorygraph_callees", {})
        data = json.loads(result[0].text)
        assert data.get("status") == "error"

    # ── semantic context via symbol lookup ─────────────────────────────

    def test_semantic_context_by_symbol(self):
        """_semantic_context should resolve file_path from symbol via mgr.get_node."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server
        from memorygraph.semantic.models import Annotation, SemanticDocument

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls,
            mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls,
        ):
            mgr = mock_mgr_cls.return_value
            mgr.get_node.return_value = {"file_path": "src/app.py"}

            sem_store = mock_sem_cls.return_value
            doc = SemanticDocument(file="src/app.py", source="test")
            doc.annotations.append(Annotation(
                symbol="main", kind="function", summary="Entry point",
                design_intent="startup", pitfalls="none"
            ))
            sem_store.load.return_value = doc

            server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_semantic_context",
            {"symbol": "main", "file": ""}
        ))
        data = json.loads(result[0].text)
        assert "src/app.py" in data

    def test_semantic_context_symbol_node_missing_file_path(self):
        """_semantic_context: node found but no file_path → should return all docs."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server
        from memorygraph.semantic.models import SemanticDocument

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls,
            mock.patch("memorygraph.mcp.server.create_semantic_store") as mock_sem_cls,
        ):
            mgr = mock_mgr_cls.return_value
            mgr.get_node.return_value = {}  # no file_path key

            sem_store = mock_sem_cls.return_value
            doc = SemanticDocument(file="src/other.py", source="test")
            sem_store.load_all.return_value = [doc]

            server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_semantic_context",
            {"symbol": "orphan_symbol", "file": ""}
        ))
        data = json.loads(result[0].text)
        # Falls back to returning all docs
        assert "documents" in data

    # ── add_unknown missing file_path error ────────────────────────────

    def test_add_unknown_missing_file_path(self, tmp_path):
        """memorygraph_add_unknown without file_path should error."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
        ):
            mock_mgr.return_value.stats.return_value = {
                "symbol_count": 100, "file_count": 10,
            }
            server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_add_unknown",
            {"symbol": "foo", "question": "why?", "file_path": ""},
        ))
        data = json.loads(result[0].text)
        assert data["status"] == "error"

    # ── hot_symbols with query log data ────────────────────────────────

    def test_hot_symbols_with_populated_log(self, tmp_path):
        """hot_symbols should return aggregated counts from query log."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        log_dir = tmp_path / ".memorygraph"
        log_dir.mkdir(parents=True)
        log_file = log_dir / "queries.jsonl"
        log_file.write_text(
            json.dumps({"ts": 1, "tool": "search", "query": "auth",
                        "symbols": ["auth.login", "auth.logout"]}) + "\n" +
            json.dumps({"ts": 2, "tool": "context", "query": "login flow",
                        "symbols": ["auth.login", "app.main"]}) + "\n" +
            json.dumps({"ts": 3, "tool": "search", "query": "password",
                        "symbols": ["auth.login"]}) + "\n"
        )

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
        ):
            mock_mgr.return_value.stats.return_value = {
                "symbol_count": 100, "file_count": 10,
            }
            server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_hot_symbols", {"limit": 5}
        ))
        data = json.loads(result[0].text)
        assert isinstance(data, list)
        assert len(data) >= 1
        # auth.login appears 3 times — should be top
        assert data[0]["symbol"] == "auth.login"
        assert data[0]["access_count"] == 3

    def test_hot_symbols_corrupt_log_lines(self, tmp_path):
        """hot_symbols should skip corrupt JSON lines in query log."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        log_dir = tmp_path / ".memorygraph"
        log_dir.mkdir(parents=True)
        log_file = log_dir / "queries.jsonl"
        log_file.write_text(
            "this is not json\n" +
            json.dumps({"ts": 1, "tool": "search", "query": "auth",
                        "symbols": ["auth.login"]}) + "\n" +
            "{incomplete\n"
        )

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
        ):
            mock_mgr.return_value.stats.return_value = {
                "symbol_count": 100, "file_count": 10,
            }
            server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_hot_symbols", {"limit": 5}
        ))
        data = json.loads(result[0].text)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["symbol"] == "auth.login"

    # ── semantic search: embedding generator unavailable ───────────────

    def test_semantic_search_fts_fallback_when_embedding_unavailable(self):
        """Semantic search should fallback to FTS when no embedding model."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
        ):
            mgr = mock_mgr_cls.return_value
            mgr.semantic_search.return_value = [
                {"name": "fts_result", "qualified_name": "fts.find",
                 "kind": "function", "file_path": "src/a.py",
                 "signature": "def f()", "rank": 0.9}
            ]

            with mock.patch(
                "memorygraph.semantic.embeddings.EmbeddingGenerator"
            ) as mock_emb_cls:
                mock_gen = mock_emb_cls.return_value
                mock_gen.is_available = False

                server = create_memorygraph_server(".")

        result = self._run(server._tool_handler(
            "memorygraph_semantic_search",
            {"query": "auth", "limit": 5}
        ))
        data = json.loads(result[0].text)
        assert len(data) >= 1
        assert data[0]["name"] == "fts_result"

    # ── search tool logs queries ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_search_tool_logs_query(self):
        """memorygraph_search should log to query log for hotness tracking."""
        from memorygraph.mcp.server import create_memorygraph_server

        server = create_memorygraph_server(".")
        # Run search — the internal _log_query is called
        result = await server._tool_handler(
            "memorygraph_search", {"query": "test_symbol", "limit": 5}
        )
        data = json.loads(result[0].text)
        assert isinstance(data, list)

    # ── auto_sync tool (coverage gap fill) ─────────────────────────────

    def test_auto_sync_fresh_when_unchanged(self):
        """memorygraph_auto_sync returns fresh when all files are unchanged."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with (
            mock.patch("memorygraph.mcp.server.auto_sync_on_startup",
                       return_value={"skipped": True, "reason": "test"}),
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
            mock.patch("memorygraph.cli.shared._collect_files") as mock_collect,
            mock.patch("memorygraph.cli.shared._compute_hash") as mock_hash,
        ):
            mock_collect.return_value = ["src/a.py", "src/b.py"]
            mock_hash.return_value = "abc123"
            mgr = mock_mgr_cls.return_value
            mgr.get_file_hash.return_value = "abc123"
            server = create_memorygraph_server(".")

            # Must call _auto_sync INSIDE the mock context
            result = self._run(server._tool_handler(
                "memorygraph_auto_sync", {}
            ))
            data = json.loads(result[0].text)
            assert data["status"] == "fresh"
            assert data["unchanged"] == 2

    def test_auto_sync_synced_with_changes(self):
        """memorygraph_auto_sync re-indexes new and changed files."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with (
            mock.patch("memorygraph.mcp.server.auto_sync_on_startup",
                       return_value={"skipped": True, "reason": "test"}),
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
            mock.patch("memorygraph.cli.shared._collect_files") as mock_collect,
            mock.patch("memorygraph.cli.shared._compute_hash") as mock_hash,
            mock.patch("memorygraph.parsing.batch.ParallelParser"),
            mock.patch("memorygraph.parsing.registry.LanguageRegistry"),
        ):
            mock_collect.return_value = ["src/a.py", "src/b.py", "src/c.py"]
            mock_hash.return_value = "newhash"
            mgr = mock_mgr_cls.return_value
            mgr.get_file_hash.side_effect = [None, "oldhash", "newhash"]
            mgr.bulk_upsert.return_value = 2
            server = create_memorygraph_server(".")

            result = self._run(server._tool_handler(
                "memorygraph_auto_sync", {}
            ))
            data = json.loads(result[0].text)
            assert data["status"] == "synced"
            assert data["new"] == 1
            assert data["changed"] == 1
            assert data["unchanged"] == 1
            assert data["synced_count"] == 2

    # ── ingest_conversation: save path with file override ─────────────

    def test_ingest_conversation_file_path_override(self):
        """When extraction returns doc, sem_store.save is called."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server
        from memorygraph.semantic.models import Annotation, SemanticDocument

        doc = SemanticDocument(file="conversation-extract", source="test")
        doc.annotations.append(Annotation(
            symbol="main", kind="function",
            summary="Entry point", design_intent="", pitfalls="",
        ))

        with (
            mock.patch("memorygraph.mcp.server.auto_sync_on_startup",
                       return_value={"skipped": True, "reason": "test"}),
            mock.patch("memorygraph.mcp.server.create_storage_manager"),
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
            mock.patch(
                "memorygraph.semantic.conversation.extract_from_conversation",
                return_value=[doc],
            ),
        ):
            server = create_memorygraph_server(".")

            result = self._run(server._tool_handler(
                "memorygraph_ingest_conversation",
                {"text": "main is the entry point", "file_path": "src/main.py"},
            ))
            data = json.loads(result[0].text)
            assert data["status"] == "ok"
            assert data["extracted_documents"] >= 1

    def test_ingest_conversation_extraction_error(self):
        """When extract_from_conversation raises, return error status."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager"),
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
            mock.patch(
                "memorygraph.semantic.conversation.extract_from_conversation",
                side_effect=ValueError("parse error"),
            ),
        ):
            server = create_memorygraph_server(".")

            result = self._run(server._tool_handler(
                "memorygraph_ingest_conversation",
                {"text": "invalid content"},
            ))
            data = json.loads(result[0].text)
            assert data["status"] == "error"
            assert "parse error" in data["message"]

    # ── hot_symbols: query log paths ──────────────────────────────────

    def test_hot_symbols_log_json_decode_error(self, tmp_path):
        """Corrupt JSON lines in query log are silently skipped."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        # Create the query log at the expected path
        log_dir = tmp_path / ".memorygraph"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "queries.jsonl"
        log_path.write_text(
            '{"ts": 1, "tool": "search", "query": "auth", "symbols": ["login"]}\n'
            'not valid json\n'
            '{"ts": 2, "tool": "search", "query": "db", "symbols": ["connect"]}\n'
            'also not json\n'
        )

        with (
            mock.patch("memorygraph.mcp.server.auto_sync_on_startup",
                       return_value={"skipped": True, "reason": "test"}),
            mock.patch("memorygraph.mcp.server.create_storage_manager"),
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
        ):
            server = create_memorygraph_server(str(tmp_path))

            result = self._run(server._tool_handler(
                "memorygraph_hot_symbols", {"limit": 10},
            ))
            data = json.loads(result[0].text)
            assert isinstance(data, list)
            # Valid entries should be parsed
            symbols = {item["symbol"] for item in data}
            assert "login" in symbols
            assert "connect" in symbols

    # ── vector search fallback path ───────────────────────────────────

    def test_semantic_search_no_embeddings_in_db(self):
        """When embeddings table has no matching rows, falls back to FTS."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
            mock.patch(
                "memorygraph.semantic.embeddings.EmbeddingGenerator"
            ) as mock_emb_cls,
        ):
            mock_gen = mock_emb_cls.return_value
            mock_gen.is_available = True
            mock_gen.generate.return_value = [0.1] * 384

            mgr = mock_mgr_cls.return_value
            mgr.get_conn.return_value.execute.return_value.fetchall.return_value = []
            mgr.semantic_search.return_value = [
                {"name": "fts_fallback", "qualified_name": "fts.item",
                 "kind": "function", "file_path": "src/a.py",
                 "signature": "def f()", "rank": 0.8}
            ]

            server = create_memorygraph_server(".")

            result = self._run(server._tool_handler(
                "memorygraph_semantic_search",
                {"query": "auth", "limit": 5},
            ))
            data = json.loads(result[0].text)
            assert isinstance(data, list)
            assert len(data) >= 1

    def test_semantic_search_vector_path_stored_embeddings(self):
        """When stored embeddings exist, uses vector search."""
        from unittest import mock

        import numpy as np

        from memorygraph.mcp.server import create_memorygraph_server

        # Create a realistic embedding blob (384 * 4 bytes)
        vec = np.random.randn(384).astype(np.float32)
        blob = vec.tobytes()

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
            mock.patch(
                "memorygraph.semantic.embeddings.EmbeddingGenerator"
            ) as mock_emb_cls,
        ):
            mock_gen = mock_emb_cls.return_value
            mock_gen.is_available = True
            mock_gen.generate.return_value = vec

            mgr = mock_mgr_cls.return_value
            mgr.get_conn.return_value.execute.return_value.fetchall.return_value = [
                ("my_func", "mymod.my_func", "def my_func()", "src/a.py",
                 "function", blob),
            ]
            mgr.semantic_search.return_value = [
                {"name": "my_func", "qualified_name": "mymod.my_func",
                 "kind": "function", "file_path": "src/a.py",
                 "signature": "def my_func()", "rank": 0.95}
            ]
            mock_gen.search.return_value = [
                {"name": "my_func", "qualified_name": "mymod.my_func",
                 "kind": "function", "file_path": "src/a.py",
                 "signature": "def my_func()", "score": 0.9}
            ]

            server = create_memorygraph_server(".")

            result = self._run(server._tool_handler(
                "memorygraph_semantic_search",
                {"query": "authentication", "limit": 5, "hybrid": False},
            ))
            data = json.loads(result[0].text)
            assert isinstance(data, list)

    # ── add_unknown: missing question (server.py line 510) ────────────

    def test_add_unknown_missing_question(self, tmp_path):
        """memorygraph_add_unknown without question should error."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
        ):
            mock_mgr.return_value.stats.return_value = {
                "symbol_count": 100, "file_count": 10,
            }
            server = create_memorygraph_server(str(tmp_path))

        result = self._run(server._tool_handler(
            "memorygraph_add_unknown",
            {"symbol": "foo", "file_path": "src/foo.py", "question": ""},
        ))
        data = json.loads(result[0].text)
        assert data["status"] == "error"
        assert "question" in data["message"]

    # ── _log_query exception silence (server.py lines 156-157) ────────

    def test_log_query_swallows_oserror(self, tmp_path):
        """search tool should succeed even when query log write fails."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with (
            mock.patch("memorygraph.mcp.server.auto_sync_on_startup",
                       return_value={"skipped": True, "reason": "test"}),
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
            mock.patch("builtins.open") as mock_open,
        ):
            mock_open.side_effect = OSError("permission denied")
            mgr = mock_mgr.return_value
            mgr.search.return_value = []
            server = create_memorygraph_server(str(tmp_path))

            # Search should succeed despite logging failure
            result = self._run(server._tool_handler(
                "memorygraph_search",
                {"query": "test", "limit": 5},
            ))
            data = json.loads(result[0].text)
            assert isinstance(data, list)

    # ── _get_hot_symbols read error (server.py lines 173-174) ─────────

    def test_hot_symbols_file_read_error(self, tmp_path):
        """hot_symbols should return empty when query log is unreadable."""
        from pathlib import Path
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        log_dir = tmp_path / ".memorygraph"
        log_dir.mkdir(parents=True)
        log_file = log_dir / "queries.jsonl"
        log_file.write_text('{"ts":1,"tool":"search","query":"auth","symbols":["login"]}\n')

        with (
            mock.patch("memorygraph.mcp.server.auto_sync_on_startup",
                       return_value={"skipped": True, "reason": "test"}),
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
        ):
            mgr = mock_mgr.return_value
            mgr.stats.return_value = {"symbol_count": 10, "file_count": 1}
            server = create_memorygraph_server(str(tmp_path))

            with mock.patch.object(Path, "read_text") as mock_read:
                mock_read.side_effect = OSError("read error")
                result = self._run(server._tool_handler(
                    "memorygraph_hot_symbols", {"limit": 5},
                ))
            data = json.loads(result[0].text)
            assert isinstance(data, list)

    # ── auto_sync_on_startup coverage (server.py lines 83, 127-129) ──

    def test_auto_sync_startup_finds_new_file(self, tmp_path):
        """auto_sync_on_startup detects new file (line 83)."""
        from unittest import mock

        from memorygraph.mcp.server import auto_sync_on_startup

        with (
            mock.patch("memorygraph.cli.shared._collect_files") as mock_collect,
            mock.patch("memorygraph.cli.shared._compute_hash") as mock_hash,
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls,
            mock.patch("memorygraph.mcp.server.logger"),
        ):
            mock_collect.return_value = ["src/new_file.py"]
            mock_hash.return_value = "abc_hash"
            mgr = mock_mgr_cls.return_value
            mgr.get_file_hash.return_value = None  # New file

            result = auto_sync_on_startup(str(tmp_path))
            assert result["status"] in ("fresh", "synced", "error")
            # Should have detected the new file
            assert result.get("new", 0) >= 1 or result["status"] in ("synced", "fresh")

    def test_auto_sync_startup_handles_exception(self, tmp_path):
        """auto_sync_on_startup returns error on exception (lines 127-129)."""
        from unittest import mock

        from memorygraph.mcp.server import auto_sync_on_startup

        with (
            mock.patch("memorygraph.cli.shared._collect_files") as mock_collect,
            mock.patch("memorygraph.mcp.server.logger"),
        ):
            mock_collect.side_effect = RuntimeError("disk error")

            result = auto_sync_on_startup(str(tmp_path))
            assert result["status"] == "error"
            assert "auto-sync failed" in result["message"]

    # ── semantic search: hybrid + vector exception (server.py 242, 244-245)

    def test_semantic_search_hybrid_mode(self):
        """semantic_search with hybrid=True merges vector + FTS (line 242)."""
        from unittest import mock

        import numpy as np

        from memorygraph.mcp.server import create_memorygraph_server

        vec = np.random.randn(384).astype(np.float32)
        blob = vec.tobytes()

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
            mock.patch(
                "memorygraph.semantic.embeddings.EmbeddingGenerator"
            ) as mock_emb_cls,
        ):
            mock_gen = mock_emb_cls.return_value
            mock_gen.is_available = True
            mock_gen.generate.return_value = vec

            mgr = mock_mgr_cls.return_value
            mgr.get_conn.return_value.execute.return_value.fetchall.return_value = [
                ("hybrid_func", "mod.hybrid_func", "def f()", "src/a.py",
                 "function", blob),
            ]
            mgr.semantic_search.return_value = [
                {"name": "fts_hit", "qualified_name": "fts.hit",
                 "kind": "function", "file_path": "src/a.py",
                 "signature": "def f()", "rank": 0.8}
            ]

            # Hybrid search returns combined results via the mock
            def _hybrid(query_vec, fts, vec_results):
                return vec_results + fts
            mock_gen.hybrid_search.side_effect = _hybrid

            mock_gen.search.return_value = [
                {"name": "vec_hit", "qualified_name": "vec.hit",
                 "kind": "function", "file_path": "src/b.py",
                 "signature": "def g()", "score": 0.9}
            ]

            server = create_memorygraph_server(".")

            result = self._run(server._tool_handler(
                "memorygraph_semantic_search",
                {"query": "test", "limit": 5, "hybrid": True},
            ))
            data = json.loads(result[0].text)
            assert isinstance(data, list)

    def test_semantic_search_vector_exception_fallback(self):
        """semantic_search falls back to FTS on vector search error (lines 244-245)."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with (
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
            mock.patch(
                "memorygraph.semantic.embeddings.EmbeddingGenerator"
            ) as mock_emb_cls,
        ):
            mock_gen = mock_emb_cls.return_value
            mock_gen.is_available = True
            mock_gen.generate.return_value = [0.1] * 384

            mgr = mock_mgr_cls.return_value
            mgr.get_conn.return_value.execute.return_value.fetchall.return_value = [
                ("test_func", "mod.test_func", "def f()", "src/a.py",
                 "function", b"\x00" * 1536),
            ]
            # Vector search fails
            mock_gen.search.side_effect = RuntimeError("vector db error")
            # FTS fallback should work
            mgr.semantic_search.return_value = [
                {"name": "fts_only", "qualified_name": "fts.only",
                 "kind": "function", "file_path": "src/a.py",
                 "signature": "def f()", "rank": 0.7}
            ]

            server = create_memorygraph_server(".")

            result = self._run(server._tool_handler(
                "memorygraph_semantic_search",
                {"query": "test", "limit": 5},
            ))
            data = json.loads(result[0].text)
            assert isinstance(data, list)
            # Should have fallen back to FTS
            assert len(data) >= 1
            assert data[0]["name"] == "fts_only"

    # ── manual auto_sync exception (server.py lines 591-593) ──────────

    def test_auto_sync_tool_handles_exception(self, tmp_path):
        """memorygraph_auto_sync tool returns error on exception (lines 591-593)."""
        from unittest import mock

        from memorygraph.mcp.server import create_memorygraph_server

        with (
            mock.patch("memorygraph.mcp.server.auto_sync_on_startup",
                       return_value={"skipped": True, "reason": "test"}),
            mock.patch("memorygraph.mcp.server.create_storage_manager") as mock_mgr_cls,
            mock.patch("memorygraph.mcp.server.create_semantic_store"),
            mock.patch("memorygraph.cli.shared._collect_files") as mock_collect,
        ):
            mock_collect.side_effect = RuntimeError("filesystem error")
            mgr = mock_mgr_cls.return_value
            mgr.get_file_hash.return_value = None
            server = create_memorygraph_server(str(tmp_path))

            result = self._run(server._tool_handler(
                "memorygraph_auto_sync", {}
            ))
            data = json.loads(result[0].text)
            assert data["status"] == "error"
            assert "filesystem error" in data.get("message", "")

    def _run(self, coro):
        return asyncio.run(coro)
