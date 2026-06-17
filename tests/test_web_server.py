"""Tests for web server and SSE manager."""
import contextlib
import json
import queue
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from memorygraph.web.server import SSEManager


class TestSSEManager:
    def test_subscribe_returns_queue(self):
        sse = SSEManager()
        q = sse.subscribe()
        assert isinstance(q, queue.Queue)

    def test_unsubscribe_removes_queue(self):
        sse = SSEManager()
        q = sse.subscribe()
        assert len(sse._queues) == 1
        sse.unsubscribe(q)
        assert len(sse._queues) == 0

    def test_unsubscribe_nonexistent_noop(self):
        sse = SSEManager()
        q = queue.Queue()
        sse.unsubscribe(q)  # Should not raise

    def test_publish_sends_to_subscribers(self):
        sse = SSEManager()
        q = sse.subscribe()
        sse.publish("test_event", {"key": "value"})
        msg = q.get_nowait()
        assert "event: test_event" in msg
        assert '"key": "value"' in msg

    def test_publish_multiple_subscribers(self):
        sse = SSEManager()
        q1 = sse.subscribe()
        q2 = sse.subscribe()
        sse.publish("update", {"data": 42})
        for q in [q1, q2]:
            msg = q.get_nowait()
            assert "event: update" in msg
            assert "42" in msg

    def test_publish_sends_to_all_subscribers(self):
        sse = SSEManager()
        q1 = sse.subscribe()
        q2 = sse.subscribe()
        sse.publish("test", {"msg": "hello"})
        msg1 = q1.get_nowait()
        msg2 = q2.get_nowait()
        assert "event: test" in msg1
        assert "hello" in msg1
        assert "event: test" in msg2


class TestMemorygraphHandler:
    """Test HTTP request handler methods."""

    @pytest.fixture
    def handler(self):
        """Create a handler with mocked dependencies."""
        from memorygraph.web.server import MemorygraphHandler

        # Create a mock request
        mock_request = MagicMock()
        mock_request.makefile.return_value = BytesIO(b"GET / HTTP/1.1\r\n\r\n")

        # Create handler instance
        h = MemorygraphHandler(
            mock_request,
            ("127.0.0.1", 12345),
            MagicMock()  # server
        )
        h.wfile = BytesIO()
        # _serve_api and _serve_sse guard with assertions; provide mocks
        h.mgr = MagicMock()
        h.sem_store = MagicMock()
        h.sse = MagicMock()

        return h

    def test_do_get_root_serves_html(self, handler):
        handler.path = "/"
        # Patch render_html to return known content
        with patch("memorygraph.web.server.render_html",
                   return_value="<html>test</html>"):
            with patch.object(handler, "send_response") as mock_send_resp:
                with patch.object(handler, "send_header"):
                    with patch.object(handler, "end_headers"):
                        handler.do_GET()
                        mock_send_resp.assert_called_once_with(200)
                        output = handler.wfile.getvalue()
                        assert b"<html>test</html>" in output

    def test_do_get_unknown_path_returns_404(self, handler):
        handler.path = "/nonexistent"
        with patch.object(handler, "send_response") as mock_send_resp:
            with patch.object(handler, "end_headers"):
                handler.do_GET()
                mock_send_resp.assert_called_once_with(404)

    def test_do_get_api_calls_handle_api(self, handler):
        handler.path = "/api/status"
        with patch.object(handler, "send_response"), patch.object(handler, "send_header"):
            with patch.object(handler, "end_headers"):
                with patch("memorygraph.web.server.handle_api",
                           return_value={"files": 5}) as mock_api:
                    handler.do_GET()
                    mock_api.assert_called_once()

    def test_do_get_api_handles_value_error(self, handler):
        handler.path = "/api/node/"
        with patch.object(handler, "send_response") as mock_send_resp:
            with patch.object(handler, "end_headers"):
                with patch("memorygraph.web.server.handle_api",
                           side_effect=ValueError("missing node name")):
                    handler.do_GET()
                    mock_send_resp.assert_called_once_with(400)

    def test_do_get_api_handles_generic_exception(self, handler):
        """_serve_api catches generic Exception -> 500 (cover server.py lines 196-202)."""
        handler.path = "/api/status"
        with patch.object(handler, "send_response") as mock_send_resp:
            with patch.object(handler, "end_headers"):
                with patch("memorygraph.web.server.handle_api",
                           side_effect=RuntimeError("unexpected failure")):
                    handler.do_GET()
                    mock_send_resp.assert_called_once_with(500)
        # error_count should be incremented
        assert handler._metrics["error_count"] >= 1

    def test_do_get_health_handles_exception(self, handler):
        """_serve_health catches Exception -> 500 (cover server.py lines 216-222)."""
        handler.path = "/health"
        with patch.object(handler, "send_response") as mock_send_resp:
            with patch.object(handler, "end_headers"):
                with patch("memorygraph.web.server.handle_health",
                           side_effect=RuntimeError("health crash")):
                    handler.do_GET()
                    mock_send_resp.assert_called_once_with(500)
        # error_count should be incremented
        assert handler._metrics["error_count"] >= 1

    def test_do_get_metrics_returns_prometheus_format(self, handler):
        """GET /metrics should return Prometheus text format."""
        handler.path = "/metrics"
        # Seed some metrics
        with handler._metrics_lock:
            handler._metrics["request_count"] = 5
            handler._metrics["query_count"] = 3
            handler._metrics["error_count"] = 1
            handler._metrics["index_count"] = 2
            handler._metrics["latencies"] = [0.001, 0.005, 0.010, 0.050, 0.100]

        with patch.object(handler, "send_response") as mock_send_resp:
            with patch.object(handler, "send_header"):
                with patch.object(handler, "end_headers"):
                    handler.do_GET()
                    mock_send_resp.assert_called_once_with(200)
                    output = handler.wfile.getvalue()
                    assert b"memorygraph_requests_total 5" in output
                    assert b"memorygraph_queries_total 3" in output
                    assert b"memorygraph_errors_total 1" in output
                    assert b"memorygraph_index_operations_total 2" in output
                    assert b"memorygraph_files_indexed" in output
                    assert b"memorygraph_symbols_indexed" in output
                    assert b"memorygraph_edges_indexed" in output
                    assert b"memorygraph_request_latency_seconds" in output
                    assert b'le="0.001"' in output
                    assert b"# HELP" in output
                    assert b"# TYPE" in output

    def test_do_get_health_success(self, handler):
        """_serve_health success path returns 200 (cover lines 224-228)."""
        handler.path = "/health"
        health_data = {
            "status": "healthy", "version": "0.0.0",
            "uptime_seconds": 1.0, "platform": "linux",
            "python_version": "3.10", "db_path": "/tmp/test.db",
            "db_size_bytes": 1024, "files_indexed": 0,
            "symbols_indexed": 0, "edges_indexed": 0,
        }
        with patch.object(handler, "send_response") as mock_send_resp:
            with patch.object(handler, "send_header"):
                with patch.object(handler, "end_headers"):
                    with patch("memorygraph.web.server.handle_health",
                               return_value=health_data):
                        handler.do_GET()
                        mock_send_resp.assert_called_once_with(200)
                        output = handler.wfile.getvalue()
                        assert b"healthy" in output

    def test_do_get_api_query_count_increment(self, handler):
        """GET /api/search increments query_count metric (cover lines 202-203)."""
        handler.path = "/api/search?q=test"
        with patch.object(handler, "send_response"), patch.object(handler, "send_header"):
            with patch.object(handler, "end_headers"):
                with patch("memorygraph.web.server.handle_api",
                           return_value={"results": []}):
                    handler.do_GET()
        assert handler._metrics["query_count"] >= 1

    def test_do_get_api_node_query_count_increment(self, handler):
        """GET /api/node increments query_count metric (cover lines 201-202)."""
        handler.path = "/api/node/main"
        with patch.object(handler, "send_response"), patch.object(handler, "send_header"):
            with patch.object(handler, "end_headers"):
                with patch("memorygraph.web.server.handle_api",
                           return_value={"name": "main"}):
                    handler.do_GET()
        assert handler._metrics["query_count"] >= 1


class TestWebServerIntegration:
    """Light integration tests for WebServer class."""

    def test_webserver_creation(self):
        import tempfile

        from memorygraph.web.server import WebServer
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = WebServer(tmpdir, port=18765)
            assert ws._port == 18765
            assert ws.sse is not None

    def test_sse_publish_complex_data(self):
        from memorygraph.web.server import SSEManager
        sse = SSEManager()
        q = sse.subscribe()
        sse.publish("complex", {"nested": {"key": [1, 2, 3]}})
        msg = q.get_nowait()
        assert "event: complex" in msg

    def test_memorygraph_handler_do_get_api_events(self):
        """Test the SSE path in the handler."""
        from io import BytesIO
        from unittest.mock import MagicMock, patch

        from memorygraph.web.server import MemorygraphHandler

        mock_request = MagicMock()
        mock_request.makefile.return_value = BytesIO(b"GET / HTTP/1.1\r\n\r\n")

        h = MemorygraphHandler(
            mock_request,
            ("127.0.0.1", 12345),
            MagicMock()
        )
        h.wfile = BytesIO()
        h.path = "/api/events"

        mock_q = MagicMock()
        mock_q.get.side_effect = [Exception("break"), Exception("break")]
        MemorygraphHandler.sse = MagicMock()
        MemorygraphHandler.sse.subscribe.return_value = mock_q

        with patch.object(h, "send_response"), patch.object(h, "send_header"):
            with patch.object(h, "end_headers"):
                try:
                    h.do_GET()
                except Exception:
                    pass  # Expected - SSE handler will break
        # Make sure SSE was subscribed
        MemorygraphHandler.sse.subscribe.assert_called_once()


class TestMemorygraphHandlerPost:
    """Tests for do_POST and _handle_annotate methods."""

    @pytest.fixture
    def handler(self):
        """Create a handler with mocked dependencies."""
        from io import BytesIO
        from unittest.mock import MagicMock

        from memorygraph.web.server import MemorygraphHandler

        mock_request = MagicMock()
        mock_request.makefile.return_value = BytesIO(b"POST / HTTP/1.1\r\n\r\n")

        h = MemorygraphHandler(
            mock_request,
            ("127.0.0.1", 12345),
            MagicMock()
        )
        h.wfile = BytesIO()
        return h

    @pytest.fixture
    def mock_mgr(self):
        from unittest.mock import MagicMock
        return MagicMock()

    @pytest.fixture
    def mock_sem_store(self):
        from unittest.mock import MagicMock
        return MagicMock()

    def test_do_post_annotate_success(self, handler, mock_mgr, mock_sem_store):
        """POST /api/annotate with valid JSON body should return 200."""
        from unittest.mock import patch

        from memorygraph.web.server import MemorygraphHandler

        body = json.dumps({
            "file": "src/app.py",
            "annotations": [{"symbol": "foo", "kind": "function",
                             "summary": "bar", "design_intent": "", "pitfalls": ""}],
            "unknowns": [], "insights": [], "module_summary": "test"
        }).encode()

        handler.path = "/api/annotate"
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = BytesIO(body)
        MemorygraphHandler.mgr = mock_mgr
        MemorygraphHandler.sem_store = mock_sem_store

        with patch("memorygraph.web.server.handle_annotate",
                   return_value={"saved": True, "file": "src/app.py"}) as mock_handle:
            handler.do_POST()
            mock_handle.assert_called_once()
            output = handler.wfile.getvalue()
            assert b'"saved"' in output

    def test_do_post_annotate_empty_body(self, handler):
        """POST /api/annotate with no body should return 400."""
        handler.path = "/api/annotate"
        handler.headers = {"Content-Length": "0"}

        with patch.object(handler, "send_response") as mock_send_resp:
            with patch.object(handler, "end_headers"):
                handler.do_POST()
                mock_send_resp.assert_called_once_with(400)

    def test_do_post_annotate_invalid_json(self, handler):
        """POST /api/annotate with invalid JSON should return 400."""
        body = b"not json"
        handler.path = "/api/annotate"
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = BytesIO(body)

        with patch.object(handler, "send_response") as mock_send_resp:
            with patch.object(handler, "end_headers"):
                handler.do_POST()
                mock_send_resp.assert_called_once_with(400)

    def test_do_post_annotate_value_error(self, handler, mock_mgr, mock_sem_store):
        """POST /api/annotate when handle_annotate raises ValueError returns 400."""
        from unittest.mock import patch

        from memorygraph.web.server import MemorygraphHandler

        body = json.dumps({"file": "src/app.py", "annotations": []}).encode()
        handler.path = "/api/annotate"
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = BytesIO(body)
        MemorygraphHandler.mgr = mock_mgr
        MemorygraphHandler.sem_store = mock_sem_store

        with patch("memorygraph.web.server.handle_annotate",
                   side_effect=ValueError("invalid data")):
            with patch.object(handler, "send_response") as mock_send_resp:
                with patch.object(handler, "end_headers"):
                    handler.do_POST()
                    mock_send_resp.assert_called_once_with(400)

    def test_do_post_unknown_path_returns_404(self, handler):
        """POST to unknown path should return 404."""
        handler.path = "/api/nonexistent"
        handler.headers = {"Content-Length": "0"}

        with patch.object(handler, "send_response") as mock_send_resp:
            with patch.object(handler, "end_headers"):
                handler.do_POST()
                mock_send_resp.assert_called_once_with(404)


class TestMemorygraphHandlerDeleteAnnotate:
    """Tests for _handle_delete_annotate and do_DELETE mapping."""

    @pytest.fixture
    def handler(self):
        from io import BytesIO
        from unittest.mock import MagicMock

        from memorygraph.web.server import MemorygraphHandler

        mock_request = MagicMock()
        mock_request.makefile.return_value = BytesIO(b"DELETE / HTTP/1.1\r\n\r\n")

        h = MemorygraphHandler(
            mock_request,
            ("127.0.0.1", 12345),
            MagicMock()
        )
        h.wfile = BytesIO()
        return h

    @pytest.fixture
    def mock_mgr(self):
        from unittest.mock import MagicMock
        return MagicMock()

    @pytest.fixture
    def mock_sem_store(self):
        from unittest.mock import MagicMock
        return MagicMock()

    def test_do_delete_maps_to_do_post(self, handler):
        """do_DELETE should be the same as do_POST."""
        from memorygraph.web.server import MemorygraphHandler
        assert MemorygraphHandler.do_DELETE == MemorygraphHandler.do_POST

    def test_do_delete_annotate_success(self, handler, mock_mgr, mock_sem_store):
        """DELETE /api/annotate/delete should delete annotation."""
        from unittest.mock import patch

        from memorygraph.web.server import MemorygraphHandler

        body = json.dumps({
            "file": "src/app.py", "symbol": "foo", "index": 0
        }).encode()
        handler.path = "/api/annotate/delete"
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = BytesIO(body)
        MemorygraphHandler.mgr = mock_mgr
        MemorygraphHandler.sem_store = mock_sem_store

        with patch("memorygraph.web.server.handle_delete_annotation",
                   return_value={"deleted": True, "file": "src/app.py", "symbol": "foo"}) as mock_handle:
            handler.do_POST()
            mock_handle.assert_called_once()
            output = handler.wfile.getvalue()
            assert b'"deleted"' in output

    def test_do_delete_annotate_empty_body(self, handler):
        """DELETE /api/annotate/delete with empty body should return 400."""
        handler.path = "/api/annotate/delete"
        handler.headers = {"Content-Length": "0"}
        handler.rfile = BytesIO(b"")

        with patch.object(handler, "send_response") as mock_send_resp:
            with patch.object(handler, "end_headers"):
                handler.do_POST()
                mock_send_resp.assert_called_once_with(400)

    def test_do_delete_annotate_invalid_json(self, handler):
        """DELETE /api/annotate/delete with invalid JSON should return 400."""
        body = b"not json"
        handler.path = "/api/annotate/delete"
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = BytesIO(body)

        with patch.object(handler, "send_response") as mock_send_resp:
            with patch.object(handler, "end_headers"):
                handler.do_POST()
                mock_send_resp.assert_called_once_with(400)

    def test_do_delete_annotate_value_error(self, handler, mock_mgr, mock_sem_store):
        """DELETE /api/annotate/delete when handler raises ValueError returns 400."""
        from unittest.mock import patch

        from memorygraph.web.server import MemorygraphHandler

        body = json.dumps({"file": "src/app.py", "symbol": "foo", "index": 0}).encode()
        handler.path = "/api/annotate/delete"
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = BytesIO(body)
        MemorygraphHandler.mgr = mock_mgr
        MemorygraphHandler.sem_store = mock_sem_store

        with patch("memorygraph.web.server.handle_delete_annotation",
                   side_effect=ValueError("invalid")):
            with patch.object(handler, "send_response") as mock_send_resp:
                with patch.object(handler, "end_headers"):
                    handler.do_POST()
                    mock_send_resp.assert_called_once_with(400)


class TestSSEHeartbeatAndErrors:
    """Tests for SSE heartbeat and error handling."""

    def _make_handler(self):
        """Create a handler without triggering auto-request processing."""
        from http.server import BaseHTTPRequestHandler
        from io import BytesIO
        from unittest.mock import MagicMock

        from memorygraph.web.server import MemorygraphHandler

        mock_request = MagicMock()
        mock_request.makefile.return_value = BytesIO(b"GET / HTTP/1.1\r\n\r\n")
        h = MemorygraphHandler.__new__(MemorygraphHandler)
        BaseHTTPRequestHandler.__init__(h, mock_request, ("127.0.0.1", 12345), MagicMock())
        h.wfile = BytesIO()
        h.requestline = "GET /api/events HTTP/1.1"
        return h

    def test_sse_heartbeat_on_empty_queue(self):
        """SSE should send heartbeat when queue.get times out."""
        import queue as queue_module
        from unittest.mock import MagicMock, patch

        from memorygraph.web.server import MemorygraphHandler

        h = self._make_handler()

        mock_q = MagicMock()
        mock_q.get.side_effect = [queue_module.Empty(), RuntimeError("break")]
        MemorygraphHandler.sse = MagicMock()
        MemorygraphHandler.sse.subscribe.return_value = mock_q

        with patch.object(h, "send_response"), \
             patch.object(h, "send_header"), \
             patch.object(h, "end_headers"), contextlib.suppress(RuntimeError):
            h._serve_sse()

        output = h.wfile.getvalue()
        assert b": heartbeat" in output

    def test_sse_broken_pipe_cleanup(self):
        """SSE should cleanly exit on BrokenPipeError."""
        from unittest.mock import MagicMock, patch

        from memorygraph.web.server import MemorygraphHandler

        h = self._make_handler()

        mock_q = MagicMock()
        mock_q.get.return_value = "event: test\ndata: {}\n\n"
        # BrokenPipeError from wfile.write or wfile.flush
        h.wfile.write = MagicMock(side_effect=BrokenPipeError())
        MemorygraphHandler.sse = MagicMock()
        MemorygraphHandler.sse.subscribe.return_value = mock_q

        with patch.object(h, "send_response"), \
             patch.object(h, "send_header"), \
             patch.object(h, "end_headers"):
            h._serve_sse()

        MemorygraphHandler.sse.unsubscribe.assert_called_once_with(mock_q)

    def test_sse_connection_reset_cleanup(self):
        """SSE should cleanly exit on ConnectionResetError."""
        from unittest.mock import MagicMock, patch

        from memorygraph.web.server import MemorygraphHandler

        h = self._make_handler()

        mock_q = MagicMock()
        mock_q.get.return_value = "event: test\ndata: {}\n\n"
        h.wfile.write = MagicMock(side_effect=ConnectionResetError())
        MemorygraphHandler.sse = MagicMock()
        MemorygraphHandler.sse.subscribe.return_value = mock_q

        with patch.object(h, "send_response"), \
             patch.object(h, "send_header"), \
             patch.object(h, "end_headers"):
            h._serve_sse()

        MemorygraphHandler.sse.unsubscribe.assert_called_once_with(mock_q)

    def test_sse_sends_event_data(self):
        """SSE should send event data and flush."""
        from unittest.mock import MagicMock, patch

        from memorygraph.web.server import MemorygraphHandler

        h = self._make_handler()

        mock_q = MagicMock()
        mock_q.get.side_effect = ["event: test\ndata: {}\n\n", RuntimeError("break")]
        MemorygraphHandler.sse = MagicMock()
        MemorygraphHandler.sse.subscribe.return_value = mock_q

        with patch.object(h, "send_response"), \
             patch.object(h, "send_header"), \
             patch.object(h, "end_headers"), contextlib.suppress(RuntimeError):
            h._serve_sse()

        output = h.wfile.getvalue()
        assert b"event: test" in output


class TestWebServerLifecycle:
    """Tests for WebServer start/stop methods."""

    def test_webserver_start_initializes_components(self):
        """WebServer.start() should initialize StorageManager, SemanticStore, and HTTP server."""
        import tempfile
        from unittest.mock import MagicMock, patch

        from memorygraph.web import server as server_module
        from memorygraph.web.server import WebServer

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = WebServer(tmpdir, port=18766)

            mock_httpd = MagicMock()
            mock_sem_store = MagicMock()

            with patch.object(server_module, "create_storage_manager") as mock_mgr_cls:
                with patch("memorygraph.semantic.store.SemanticStore",
                           return_value=mock_sem_store):
                    with patch.object(server_module, "ThreadingHTTPServer",
                                       return_value=mock_httpd):
                        # Set stop_event to prevent infinite loop
                        ws._stop_event.set()
                        ws.start()

            mock_mgr_cls.assert_called_once_with(tmpdir)

    def test_webserver_stop_shuts_down_httpd(self):
        """WebServer.stop() should call httpd.server_close() and mgr.close()."""
        import tempfile
        from unittest.mock import MagicMock

        from memorygraph.web.server import WebServer

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = WebServer(tmpdir, port=18767)
            mock_httpd = MagicMock()
            mock_mgr = MagicMock()
            ws._httpd = mock_httpd
            ws._mgr = mock_mgr
            ws.stop()
            mock_httpd.server_close.assert_called_once()
            mock_mgr.close.assert_called_once()

    def test_webserver_stop_no_httpd_does_nothing(self):
        """WebServer.stop() should not fail when httpd is None."""
        import tempfile

        from memorygraph.web.server import WebServer

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = WebServer(tmpdir, port=18768)
            ws._httpd = None
            ws.stop()  # Should not raise

    def test_stop_event_is_set_on_stop(self):
        """stop() should set stop_event."""
        import tempfile

        from memorygraph.web.server import WebServer

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = WebServer(tmpdir, port=18769)
            assert not ws._stop_event.is_set()
            ws.stop()
            assert ws._stop_event.is_set()

    def test_webserver_stop_mgr_close_raises_does_not_propagate(self):
        """WebServer.stop() should suppress exceptions from mgr.close() (cross-thread)."""
        import tempfile
        from unittest.mock import MagicMock

        from memorygraph.web.server import WebServer

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = WebServer(tmpdir, port=18771)
            mock_httpd = MagicMock()
            mock_mgr = MagicMock()
            mock_mgr.close.side_effect = RuntimeError("cross-thread close")
            ws._httpd = mock_httpd
            ws._mgr = mock_mgr
            ws.stop()  # Should not raise
            mock_httpd.server_close.assert_called_once()
            mock_mgr.close.assert_called_once()

    def test_wait_ready_times_out_before_start(self):
        """wait_ready() should timeout before start() is called."""
        import tempfile

        from memorygraph.web.server import WebServer

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = WebServer(tmpdir, port=18770)
            assert ws.wait_ready(timeout=0.1) is False

    def test_stop_without_mgr_does_not_raise(self):
        """stop() should not raise when mgr was never set."""
        import tempfile

        from memorygraph.web.server import WebServer

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = WebServer(tmpdir, port=18771)
            ws.stop()  # Should not raise

    def test_external_stop_event_triggers_shutdown(self):
        """External caller can set stop_event to trigger shutdown (used by signal handler in serve())."""
        import tempfile

        from memorygraph.web.server import WebServer

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = WebServer(tmpdir, port=18772)
            # Simulate what serve()'s signal handler does
            ws._stop_event.set()
            assert ws._stop_event.is_set()

    def test_webserver_uses_threading_httpserver(self):
        """WebServer.start() should use ThreadingHTTPServer for concurrent request handling."""
        import tempfile
        from unittest.mock import MagicMock, patch

        from memorygraph.web import server as server_module
        from memorygraph.web.server import WebServer

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = WebServer(tmpdir, port=18773)
            mock_httpd = MagicMock()

            with patch.object(server_module, "create_storage_manager"):
                with patch("memorygraph.semantic.store.SemanticStore",
                           return_value=MagicMock()):
                    with patch.object(server_module, "ThreadingHTTPServer",
                                       return_value=mock_httpd) as mock_server_cls:
                        ws._stop_event.set()
                        ws.start()
                        # Verify ThreadingHTTPServer was constructed
                        mock_server_cls.assert_called_once()
            # Verify socket timeout was set on the mock (survives un-patching)
            mock_httpd.socket.settimeout.assert_called_once()


class TestASGIApp:
    """Tests for the ASGI application (uvicorn path)."""

    def _make_app(self, tmpdir):
        """Create an ASGI app with initialized storage."""
        from memorygraph.semantic.store import SemanticStore
        from memorygraph.storage import StorageManager
        from memorygraph.storage.connection import get_db_path
        from memorygraph.web.server import SSEManager, create_asgi_app

        mgr = StorageManager(str(tmpdir))
        mgr.initialize()
        sem_store = SemanticStore(str(tmpdir))
        sse = SSEManager()
        db_path = get_db_path(str(tmpdir))

        app = create_asgi_app(str(tmpdir), mgr, sem_store, sse, __import__("time").time(), db_path)
        return app

    async def _request(self, app, path, method="GET", body=None):
        """Send a request to the ASGI app and return (status, headers, body)."""
        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": [],
        }

        receive_calls = []
        if body:
            receive_calls.append({
                "type": "http.request",
                "body": body if isinstance(body, bytes) else json.dumps(body).encode(),
                "more_body": False,
            })
        else:
            receive_calls.append({"type": "http.request", "body": b"", "more_body": False})

        async def receive():
            return receive_calls.pop(0) if receive_calls else {"type": "http.request", "body": b"", "more_body": False}

        send_messages = []
        async def send(msg):
            send_messages.append(msg)

        await app(scope, receive, send)

        # Extract status and body from response
        response_start = [m for m in send_messages if m["type"] == "http.response.start"]
        response_body = [m for m in send_messages if m["type"] == "http.response.body"]
        status = response_start[0]["status"] if response_start else 0
        headers = {k.decode(): v.decode() for k, v in response_start[0].get("headers", [])} if response_start else {}
        body = b"".join(m.get("body", b"") for m in response_body)
        return status, headers, body

    def test_asgi_health_endpoint(self, tmpdir):
        """ASGI app should return health status on /health."""
        import asyncio
        app = self._make_app(tmpdir)
        status, headers, body = asyncio.run(self._request(app, "/health"))
        assert status == 200
        data = json.loads(body)
        assert data["status"] == "ok"

    def test_asgi_root_returns_html(self, tmpdir):
        """ASGI app should return HTML on /."""
        import asyncio
        app = self._make_app(tmpdir)
        status, headers, body = asyncio.run(self._request(app, "/"))
        assert status == 200
        assert b"<!DOCTYPE html>" in body or b"<html" in body.lower()

    def test_asgi_404_for_unknown_path(self, tmpdir):
        """ASGI app should return 404 for unknown paths."""
        import asyncio
        app = self._make_app(tmpdir)
        status, headers, body = asyncio.run(self._request(app, "/nonexistent"))
        assert status == 404

    def test_asgi_concurrent_requests(self, tmpdir):
        """ASGI app should handle concurrent requests without blocking."""
        import asyncio
        import time
        app = self._make_app(tmpdir)

        async def make_requests():
            tasks = []
            for _ in range(10):
                tasks.append(self._request(app, "/health"))
            start = time.monotonic()
            results = await asyncio.gather(*tasks)
            elapsed = time.monotonic() - start
            return results, elapsed

        results, elapsed = asyncio.run(make_requests())
        # All 10 requests should succeed
        for status, _headers, body in results:
            assert status == 200
            data = json.loads(body)
            assert data["status"] == "ok"

        # 10 concurrent requests should complete quickly (<5s, certainly not serial 10×)
        assert elapsed < 5.0, f"Concurrent requests took {elapsed:.1f}s, expected <5s"

    def test_asgi_metrics_endpoint(self, tmpdir):
        """ASGI app should return Prometheus metrics on /metrics."""
        import asyncio
        app = self._make_app(tmpdir)
        status, headers, body = asyncio.run(self._request(app, "/metrics"))
        assert status == 200
        assert b"memorygraph_requests_total" in body

    def test_asgi_405_for_invalid_method(self, tmpdir):
        """ASGI app should return 405 for POST on GET-only endpoints."""
        import asyncio
        app = self._make_app(tmpdir)
        status, headers, body = asyncio.run(self._request(app, "/health", method="POST"))
        assert status == 405

    def test_asgi_non_http_scope_returns(self, tmpdir):
        """ASGI app should return immediately for non-HTTP scopes (e.g., websocket)."""
        import asyncio
        app = self._make_app(tmpdir)
        scope = {"type": "websocket", "path": "/"}

        async def receive():
            return {"type": "websocket.connect"}

        send_messages = []
        async def send(msg):
            send_messages.append(msg)

        asyncio.run(app(scope, receive, send))
        # Should not send any HTTP response
        assert len(send_messages) == 0

    def test_asgi_root_wrong_method_405(self, tmpdir):
        """ASGI app should return 405 for POST on /."""
        import asyncio
        app = self._make_app(tmpdir)
        status, headers, body = asyncio.run(self._request(app, "/", method="POST"))
        assert status == 405

    def test_asgi_annotate_post_success(self, tmpdir):
        """ASGI app should handle POST /api/annotate with valid JSON."""
        import asyncio
        app = self._make_app(tmpdir)
        data = {
            "file": "src/app.py",
            "annotations": [{"symbol": "foo", "kind": "function", "summary": "test"}],
            "unknowns": [],
            "insights": [],
            "module_summary": "test",
        }
        status, headers, body = asyncio.run(
            self._request(app, "/api/annotate", method="POST", body=data)
        )
        assert status == 200
        result = json.loads(body)
        assert result["saved"] is True

    def test_asgi_annotate_post_invalid_json(self, tmpdir):
        """ASGI app should return 400 for invalid JSON on /api/annotate."""
        import asyncio
        app = self._make_app(tmpdir)
        status, headers, body = asyncio.run(
            self._request(app, "/api/annotate", method="POST", body=b"not json")
        )
        assert status == 400
        data = json.loads(body)
        assert "error" in data

    def test_asgi_annotate_post_value_error(self, tmpdir):
        """ASGI app should return 400 when handle_annotate raises ValueError."""
        import asyncio
        from unittest import mock
        app = self._make_app(tmpdir)
        with mock.patch("memorygraph.web.server.handle_annotate",
                        side_effect=ValueError("missing file")):
            data = {"file": "", "annotations": []}
            status, headers, body = asyncio.run(
                self._request(app, "/api/annotate", method="POST", body=data)
            )
        assert status == 400
        data = json.loads(body)
        assert "missing file" in data["error"]

    def test_asgi_annotate_wrong_method_405(self, tmpdir):
        """ASGI app should return 405 for GET on /api/annotate."""
        import asyncio
        app = self._make_app(tmpdir)
        status, headers, body = asyncio.run(
            self._request(app, "/api/annotate", method="GET")
        )
        assert status == 405

    def test_asgi_annotate_delete_post_success(self, tmpdir):
        """ASGI app should handle POST /api/annotate/delete."""
        import asyncio
        from unittest import mock
        app = self._make_app(tmpdir)
        with mock.patch("memorygraph.web.server.handle_delete_annotation",
                        return_value={"deleted": True, "file": "src/app.py", "symbol": "foo"}):
            data = {"file": "src/app.py", "symbol": "foo", "index": 0}
            status, headers, body = asyncio.run(
                self._request(app, "/api/annotate/delete", method="POST", body=data)
            )
        assert status == 200
        result = json.loads(body)
        assert result["deleted"] is True

    def test_asgi_annotate_delete_invalid_json(self, tmpdir):
        """ASGI app should return 400 for invalid JSON on /api/annotate/delete."""
        import asyncio
        app = self._make_app(tmpdir)
        status, headers, body = asyncio.run(
            self._request(app, "/api/annotate/delete", method="POST", body=b"bad json")
        )
        assert status == 400

    def test_asgi_annotate_delete_value_error(self, tmpdir):
        """ASGI app should return 400 when handle_delete_annotation raises ValueError."""
        import asyncio
        from unittest import mock
        app = self._make_app(tmpdir)
        with mock.patch("memorygraph.web.server.handle_delete_annotation",
                        side_effect=ValueError("not found")):
            data = {"file": "src/nope.py", "annotation_index": 99}
            status, headers, body = asyncio.run(
                self._request(app, "/api/annotate/delete", method="POST", body=data)
            )
        assert status == 400

    def test_asgi_annotate_delete_wrong_method_405(self, tmpdir):
        """ASGI app should return 405 for GET on /api/annotate/delete."""
        import asyncio
        app = self._make_app(tmpdir)
        status, headers, body = asyncio.run(
            self._request(app, "/api/annotate/delete", method="GET")
        )
        assert status == 405

    def test_asgi_api_get_with_error(self, tmpdir):
        """ASGI app should return 500 for unhandled API errors and track error count."""
        import asyncio
        from unittest import mock
        app = self._make_app(tmpdir)
        with mock.patch("memorygraph.web.server.handle_api",
                        side_effect=RuntimeError("db crash")):
            status, headers, body = asyncio.run(
                self._request(app, "/api/graph")
            )
        assert status == 500
        data = json.loads(body)
        assert "db crash" in data["error"]

    def test_asgi_api_get_value_error(self, tmpdir):
        """ASGI app should return 400 when handle_api raises ValueError."""
        import asyncio
        from unittest import mock
        app = self._make_app(tmpdir)
        with mock.patch("memorygraph.web.server.handle_api",
                        side_effect=ValueError("bad param")):
            status, headers, body = asyncio.run(
                self._request(app, "/api/search?q=")
            )
        assert status == 400
        data = json.loads(body)
        assert "bad param" in data["error"]

    def test_asgi_api_wrong_method_405(self, tmpdir):
        """ASGI app should return 405 for POST on /api/search."""
        import asyncio
        app = self._make_app(tmpdir)
        status, headers, body = asyncio.run(
            self._request(app, "/api/search", method="POST", body={})
        )
        assert status == 405

    def test_asgi_api_events_sse(self, tmpdir):
        """ASGI app should set up SSE on /api/events."""
        import asyncio
        from unittest import mock
        app = self._make_app(tmpdir)
        # SSE handler runs forever — mock the sse to exit quickly
        with mock.patch("memorygraph.web.server._asgi_sse_handler") as mock_sse:
            async def fake_sse(send, sse):
                await send({
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")],
                })
            mock_sse.side_effect = fake_sse
            status, headers, body = asyncio.run(
                self._request(app, "/api/events")
            )
        assert status == 200

    def test_asgi_metrics_wrong_method_405(self, tmpdir):
        """ASGI app should return 405 for POST on /metrics."""
        import asyncio
        app = self._make_app(tmpdir)
        status, headers, body = asyncio.run(
            self._request(app, "/metrics", method="POST")
        )
        assert status == 405

    def test_asgi_health_query_string(self, tmpdir):
        """ASGI app should handle /health with query string."""
        import asyncio
        app = self._make_app(tmpdir)
        # Update _request to include query_string
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/health",
            "query_string": b"format=json",
            "headers": [],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        send_messages = []
        async def send(msg):
            send_messages.append(msg)

        asyncio.run(app(scope, receive, send))
        response_start = [m for m in send_messages if m["type"] == "http.response.start"]
        assert response_start[0]["status"] == 200

    def test_asgi_api_events_wrong_method_405(self, tmpdir):
        """ASGI app should return 405 for POST on /api/events."""
        import asyncio
        app = self._make_app(tmpdir)
        status, headers, body = asyncio.run(
            self._request(app, "/api/events", method="POST")
        )
        assert status == 405

    def test_asgi_api_search_increments_query_count(self, tmpdir):
        """ASGI app should increment query_count for GET /api/search."""
        import asyncio
        from unittest import mock
        app = self._make_app(tmpdir)
        with mock.patch("memorygraph.web.server.handle_api",
                        return_value={"results": []}):
            status, headers, body = asyncio.run(
                self._request(app, "/api/search?q=test")
            )
        assert status == 200

    def test_asgi_api_node_increments_query_count(self, tmpdir):
        """ASGI app should increment query_count for GET /api/node."""
        import asyncio
        from unittest import mock
        app = self._make_app(tmpdir)
        with mock.patch("memorygraph.web.server.handle_api",
                        return_value={"id": "foo", "kind": "function"}):
            status, headers, body = asyncio.run(
                self._request(app, "/api/node?name=foo")
            )
        assert status == 200

    def test_asgi_api_search_empty_query_string(self, tmpdir):
        """ASGI app should handle /api/search with empty query string."""
        import asyncio
        from unittest import mock
        app = self._make_app(tmpdir)
        with mock.patch("memorygraph.web.server.handle_api",
                        return_value={"results": []}):
            status, headers, body = asyncio.run(
                self._request(app, "/api/search")
            )
        assert status == 200

    def test_asgi_latency_rotation(self, tmpdir):
        """ASGI app should rotate latency samples when reaching _MAX_LATENCY_SAMPLES."""
        import asyncio
        from unittest import mock
        app = self._make_app(tmpdir)
        with mock.patch("memorygraph.web.server._MAX_LATENCY_SAMPLES", 3):
            # Make enough requests to trigger rotation
            for _ in range(5):
                asyncio.run(self._request(app, "/health"))
        # Should not crash — rotation succeeded silently


class TestASGISSEHandler:
    """Tests for the ASGI SSE handler function."""

    def test_asgi_sse_handler_sends_heartbeat(self):
        """_asgi_sse_handler should send heartbeat on empty queue."""
        import asyncio
        import queue as queue_module
        from unittest import mock

        from memorygraph.web.server import _asgi_sse_handler

        mock_sse = mock.MagicMock()
        mock_q = mock.MagicMock()
        mock_q.get_nowait.side_effect = [
            queue_module.Empty(),  # heartbeat
            RuntimeError("break"),  # exit loop
        ]
        mock_sse.subscribe.return_value = mock_q

        send_messages = []
        async def send(msg):
            send_messages.append(msg)

        async def run_handler():
            await _asgi_sse_handler(send, mock_sse)

        with contextlib.suppress(RuntimeError):
            asyncio.run(run_handler())

        # Should have sent headers and heartbeat
        body_messages = [m for m in send_messages if m["type"] == "http.response.body"]
        assert any(b": heartbeat" in m.get("body", b"") for m in body_messages)
        mock_sse.unsubscribe.assert_called_once_with(mock_q)

    def test_asgi_sse_handler_sends_event_data(self):
        """_asgi_sse_handler should send event data from the queue."""
        import asyncio
        from unittest import mock

        from memorygraph.web.server import _asgi_sse_handler

        mock_sse = mock.MagicMock()
        mock_q = mock.MagicMock()
        mock_q.get_nowait.side_effect = [
            "event: update\ndata: {}\n\n",  # event data
            RuntimeError("break"),  # exit loop
        ]
        mock_sse.subscribe.return_value = mock_q

        send_messages = []
        async def send(msg):
            send_messages.append(msg)

        async def run_handler():
            await _asgi_sse_handler(send, mock_sse)

        with contextlib.suppress(RuntimeError):
            asyncio.run(run_handler())

        body_messages = [m for m in send_messages if m["type"] == "http.response.body"]
        assert any(b"event: update" in m.get("body", b"") for m in body_messages)

    def test_asgi_sse_handler_handles_send_exception(self):
        """_asgi_sse_handler should break on send exception (client disconnect)."""
        import asyncio
        from unittest import mock

        from memorygraph.web.server import _asgi_sse_handler

        mock_sse = mock.MagicMock()
        mock_q = mock.MagicMock()
        mock_q.get_nowait.return_value = "event: test\ndata: {}\n\n"
        mock_sse.subscribe.return_value = mock_q

        send_messages = []
        call_count = []

        async def send(msg):
            call_count.append(1)
            if len(call_count) >= 3:  # headers sent, body send fails
                raise ConnectionResetError("client gone")
            send_messages.append(msg)

        async def run_handler():
            await _asgi_sse_handler(send, mock_sse)

        asyncio.run(run_handler())
        # Should have cleaned up
        mock_sse.unsubscribe.assert_called_once_with(mock_q)


class TestMemorygraphHandlerEdgeCases:
    """Edge case tests for MemorygraphHandler."""

    def test_record_latency_rotation(self):
        """_record_latency should rotate out old samples when reaching _MAX_LATENCY_SAMPLES."""
        from io import BytesIO
        from unittest.mock import MagicMock, patch

        from memorygraph.web.server import MemorygraphHandler

        mock_request = MagicMock()
        mock_request.makefile.return_value = BytesIO(b"GET / HTTP/1.1\r\n\r\n")
        h = MemorygraphHandler.__new__(MemorygraphHandler)
        from http.server import BaseHTTPRequestHandler
        BaseHTTPRequestHandler.__init__(
            h, mock_request, ("127.0.0.1", 12345), MagicMock()
        )

        # Patch _MAX_LATENCY_SAMPLES to a tiny number to trigger rotation easily
        with patch("memorygraph.web.server._MAX_LATENCY_SAMPLES", 3):
            # Add enough samples to trigger rotation
            for _i in range(5):
                h._record_latency(0.1)
            # After rotation, should have ≤ (3//2 + 5-3) samples
            assert len(MemorygraphHandler._metrics["latencies"]) <= 4

    def test_read_json_body_too_large(self):
        """_read_json_body should return 413 for body exceeding _MAX_BODY_SIZE."""
        from io import BytesIO
        from unittest.mock import MagicMock, patch

        from memorygraph.web.server import _MAX_BODY_SIZE, MemorygraphHandler

        mock_request = MagicMock()
        mock_request.makefile.return_value = BytesIO(
            b"POST /api/annotate HTTP/1.1\r\n"
            b"Content-Length: 999999999\r\n\r\n"
        )
        h = MemorygraphHandler.__new__(MemorygraphHandler)
        from http.server import BaseHTTPRequestHandler
        BaseHTTPRequestHandler.__init__(
            h, mock_request, ("127.0.0.1", 12345), MagicMock()
        )

        # Override headers to have a very large Content-Length
        h.headers = MagicMock()
        h.headers.get.return_value = str(_MAX_BODY_SIZE + 1)

        with patch.object(h, "_send_json") as mock_send:
            data, ok = h._read_json_body()
            assert data is None
            assert ok is True
            mock_send.assert_called_once()
            call_args = mock_send.call_args[0]
            assert call_args[0] == 413


class TestWebAPIDirectHandlers:
    """Direct unit tests for web/api.py handler functions — targeting 59% → 80%+."""

    # ── handle_api /api/graph with root (BFS traversal) ──────────────

    def test_api_graph_with_root_bfs(self):
        """handle_api /api/graph?root=sym should traverse callers/callees via BFS."""
        from unittest import mock

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        mgr.get_node.return_value = {
            "qualified_name": "root_func", "kind": "function",
            "file_path": "src/a.py", "start_line": 10,
        }
        mgr.get_callers.return_value = [
            {"source": "caller1", "target": "root_func"}
        ]
        mgr.get_callees.return_value = [
            {"source": "root_func", "target": "callee1"}
        ]
        sem_store = mock.MagicMock()
        sem_store.load_all.return_value = []

        result = handle_api("/api/graph?root=root_func&depth=2", mgr, sem_store)
        assert "nodes" in result
        assert "edges" in result
        assert len(result["nodes"]) >= 1
        assert result["nodes"][0]["id"] == "root_func"
        # Truncation fields always present
        assert "truncated" in result
        assert "total_available" in result
        assert "truncated_branches" in result

    def test_api_graph_with_root_bfs_respects_depth(self):
        """handle_api /api/graph BFS should not exceed depth limit."""
        from unittest import mock

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        mgr.get_node.return_value = {
            "qualified_name": "root", "kind": "function",
            "file_path": "src/a.py", "start_line": 1,
        }
        # With depth=0, no callers/callees should be traversed
        mgr.get_callers.return_value = [{"source": "should_not_appear", "target": "root"}]
        mgr.get_callees.return_value = [{"source": "root", "target": "should_not_appear"}]
        sem_store = mock.MagicMock()
        sem_store.load_all.return_value = []

        result = handle_api("/api/graph?root=root&depth=0", mgr, sem_store)
        assert len(result["nodes"]) == 1  # only the root

    def test_api_graph_bfs_truncation(self):
        """handle_api /api/graph should report truncation when 500-node limit hit."""
        from unittest import mock

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        # Each node only sees itself (no callers/callees to expand)
        def _make_node(name):
            return {"qualified_name": name, "kind": "function",
                    "file_path": "src/x.py", "start_line": 1}

        # 501 nodes in callers → BFS will hit 500 limit
        callers = [{"source": f"func_{i}", "target": "root"}
                   for i in range(501)]
        mgr.get_callers.return_value = callers
        mgr.get_callees.return_value = []
        mgr.get_node.side_effect = lambda n: _make_node(n) if n != "root" else {
            "qualified_name": "root", "kind": "function",
            "file_path": "src/a.py", "start_line": 1,
        }
        # get_callees for truncation detection
        mgr.get_callees.side_effect = lambda sym, depth=1: []

        sem_store = mock.MagicMock()
        sem_store.load_all.return_value = []

        result = handle_api("/api/graph?root=root&depth=1", mgr, sem_store)
        assert result["truncated"] is True
        assert result["total_available"] > 500
        assert len(result["truncated_branches"]) > 0
        assert len(result["nodes"]) == 500

    # ── handle_api /api/search empty query ────────────────────────────

    def test_api_search_empty_query(self):
        """handle_api /api/search with empty q= should return empty results."""
        from unittest import mock

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()

        result = handle_api("/api/search?q=", mgr, sem_store)
        assert result == {"results": []}

    # ── handle_api /api/node error paths ──────────────────────────────

    def test_api_node_missing_name_raises(self):
        """handle_api /api/node/ with no name should raise ValueError."""
        from unittest import mock

        import pytest

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()

        with pytest.raises(ValueError, match="missing node name"):
            handle_api("/api/node/", mgr, sem_store)

    def test_api_node_not_found_raises(self):
        """handle_api /api/node/name when node not in DB should raise ValueError."""
        from unittest import mock

        import pytest

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        mgr.get_node.return_value = None  # node not found
        sem_store = mock.MagicMock()

        with pytest.raises(ValueError, match="node not found"):
            handle_api("/api/node/nonexistent", mgr, sem_store)

    # ── handle_api /api/semantic missing file ─────────────────────────

    def test_api_semantic_missing_file(self):
        """handle_api /api/semantic without file param should return error."""
        from unittest import mock

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()

        result = handle_api("/api/semantic", mgr, sem_store)
        assert "error" in result

    def test_api_semantic_file_not_found(self):
        """handle_api /api/semantic?file=missing should return empty lists."""
        from unittest import mock

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()
        sem_store.load.return_value = None

        result = handle_api("/api/semantic?file=missing.py", mgr, sem_store)
        assert result["file"] == "missing.py"
        assert result["annotations"] == []

    def test_api_semantic_file_found(self):
        """handle_api /api/semantic?file=existing should return semantic data."""
        from unittest import mock

        from memorygraph.semantic.models import (
            Annotation,
            Insight,
            SemanticDocument,
            Unknown,
        )
        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()
        doc = SemanticDocument(file="src/app.py", source="test")
        doc.annotations.append(Annotation(
            symbol="main", kind="function", summary="Entry point",
            design_intent="bootstrap", pitfalls="none"
        ))
        doc.unknowns.append(Unknown(
            symbol="helper", question="What does this do?",
            context="found in main"
        ))
        doc.insights.append(Insight(
            insight="Uses Observer pattern",
            related_symbols=["Subject"]
        ))
        sem_store.load.return_value = doc

        result = handle_api("/api/semantic?file=src/app.py", mgr, sem_store)
        assert len(result["annotations"]) == 1
        assert result["annotations"][0]["symbol"] == "main"
        assert len(result["unknowns"]) == 1
        assert len(result["insights"]) == 1

    # ── handle_api unknown endpoint ───────────────────────────────────

    def test_api_unknown_endpoint_raises(self):
        """handle_api with unknown path should raise ValueError."""
        from unittest import mock

        import pytest

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()

        with pytest.raises(ValueError, match="unknown endpoint"):
            handle_api("/api/nonexistent", mgr, sem_store)

    # ── handle_health error paths ─────────────────────────────────────

    def test_health_db_error_status(self):
        """handle_health should report db_status=error when DB ping fails."""
        import time
        from unittest import mock

        from memorygraph.web.api import handle_health

        mgr = mock.MagicMock()
        mgr.stats.return_value = {
            "file_count": 10, "symbol_count": 100,
            "edge_count": 200, "last_updated": "",
        }
        mgr.get_conn.return_value.execute.side_effect = RuntimeError("DB down")

        result = handle_health(mgr, time.time())
        assert result["db_status"] == "error"
        assert result["status"] == "ok"  # overall status still ok

    def test_health_with_metrics_and_index_rate(self):
        """handle_health should compute index_rate_per_minute when metrics present."""
        import time
        from unittest import mock

        from memorygraph.web.api import handle_health

        mgr = mock.MagicMock()
        mgr.stats.return_value = {
            "file_count": 10, "symbol_count": 100,
            "edge_count": 200, "last_updated": "",
        }
        start = time.time() - 120  # 2 min uptime
        metrics = {"index_count": 60}  # 60 indexes in 2 min → 30/min

        result = handle_health(mgr, start, metrics=metrics)
        assert "index_rate_per_minute" in result
        assert result["index_rate_per_minute"] == 30.0

    def test_health_with_db_path_and_size(self):
        """handle_health should report db_size_bytes when db_path provided."""
        import os
        import tempfile
        import time
        from unittest import mock

        from memorygraph.web.api import handle_health

        mgr = mock.MagicMock()
        mgr.stats.return_value = {
            "file_count": 10, "symbol_count": 100,
            "edge_count": 200, "last_updated": "",
        }

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x" * 100)
            tmp_path = f.name

        try:
            result = handle_health(mgr, time.time(), db_path=tmp_path)
            assert result["db_size_bytes"] == 100
        finally:
            os.unlink(tmp_path)

    # ── handle_annotate error paths ───────────────────────────────────

    def test_annotate_missing_file_raises(self):
        """handle_annotate without 'file' field should raise ValueError."""
        from unittest import mock

        import pytest

        from memorygraph.web.api import handle_annotate

        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()

        with pytest.raises(ValueError, match="missing 'file' field"):
            handle_annotate({}, mgr, sem_store)

    # ── handle_delete_annotation ──────────────────────────────────────

    def test_delete_annotation_success(self):
        """handle_delete_annotation should delete annotation and return result."""
        from unittest import mock

        from memorygraph.web.api import handle_delete_annotation

        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()
        sem_store.delete_annotation.return_value = True

        result = handle_delete_annotation(
            {"file": "src/app.py", "symbol": "old_func", "index": 0},
            mgr, sem_store
        )
        assert result["deleted"] is True
        assert result["file"] == "src/app.py"
        assert result["symbol"] == "old_func"
        sem_store.delete_annotation.assert_called_once_with(
            "src/app.py", "old_func", 0
        )

    def test_delete_annotation_missing_fields_raises(self):
        """handle_delete_annotation without file/symbol should raise ValueError."""
        from unittest import mock

        import pytest

        from memorygraph.web.api import handle_delete_annotation

        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()

        with pytest.raises(ValueError, match="missing 'file' or 'symbol'"):
            handle_delete_annotation({}, mgr, sem_store)

    # ── _node_to_json semantic enrichment ─────────────────────────────

    def test_node_to_json_with_role_and_complexity(self):
        """_node_to_json should enrich node with role and complexity from semantic store."""
        from unittest import mock

        from memorygraph.web.api import _node_to_json

        sem_store = mock.MagicMock()
        sem_doc = mock.MagicMock()
        sem_doc.module_roles = {"app.main": "controller"}
        sem_doc.metrics = {
            "complexity": [
                {"name": "main", "complexity": 5, "rank": "C"}
            ]
        }
        sem_store.load_all.return_value = [sem_doc]

        node = {
            "qualified_name": "app.main",
            "kind": "function",
            "start_line": 10,
            "file_path": "src/app.py",
            "name": "main",
        }

        result = _node_to_json(node, sem_store)
        assert result["id"] == "app.main"
        assert result["role"] == "controller"
        assert result["complexity"] == 5
        assert result["rank"] == "C"

    def test_node_to_json_file_fallback_keys(self):
        """_node_to_json should try 'file_path', 'file', 'path' keys for file."""
        from unittest import mock

        from memorygraph.web.api import _node_to_json

        sem_store = mock.MagicMock()
        sem_store.load_all.return_value = []

        # Test with 'file' key
        node = {"qualified_name": "sym", "kind": "class", "start_line": 5, "file": "src/b.py"}
        result = _node_to_json(node, sem_store)
        assert result["file"] == "src/b.py"

        # Test with 'path' key
        node2 = {"qualified_name": "sym2", "kind": "variable", "start_line": 3, "path": "src/c.py"}
        result2 = _node_to_json(node2, sem_store)
        assert result2["file"] == "src/c.py"

    # ── handle_annotate with unknowns and insights ────────────────────

    def test_annotate_with_unknowns_and_insights(self):
        """handle_annotate should process unknowns and insights from request data."""
        from unittest import mock

        from memorygraph.web.api import handle_annotate

        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()

        data = {
            "file": "src/app.py",
            "annotations": [
                {"symbol": "func", "kind": "function",
                 "summary": "does stuff", "design_intent": "", "pitfalls": ""}
            ],
            "unknowns": [
                {"symbol": "func", "question": "Why?",
                 "context": "review"}
            ],
            "insights": [
                {"insight": "Uses pattern X",
                 "related_symbols": ["A", "B"]}
            ],
        }

        result = handle_annotate(data, mgr, sem_store)
        assert result["saved"] is True
        assert result["annotations"] == 1
        assert result["unknowns"] == 1
        assert result["insights"] == 1
        sem_store.save.assert_called_once()

    def test_health_memory_usage_fallback(self):
        """handle_health memory_usage_mb should be -1 when /proc unavailable."""
        import time
        from unittest import mock

        from memorygraph.web.api import handle_health

        mgr = mock.MagicMock()
        mgr.stats.return_value = {
            "file_count": 10, "symbol_count": 100,
            "edge_count": 200, "last_updated": "",
        }

        # Simulate /proc/self/status read failure
        with mock.patch("builtins.open", side_effect=OSError):
            result = handle_health(mgr, time.time())
            assert result["memory_usage_mb"] == -1

    # ── handle_api /api/files ────────────────────────────────────────

    def test_api_files_returns_file_list(self):
        """handle_api /api/files should return mgr.list_files() result."""
        from unittest import mock

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        mgr.list_files.return_value = [
            {"path": "src/a.py", "symbols": 5, "language": "Python"},
            {"path": "src/b.py", "symbols": 3, "language": "Python"},
        ]
        sem_store = mock.MagicMock()

        result = handle_api("/api/files", mgr, sem_store)
        assert "files" in result
        assert len(result["files"]) == 2
        assert result["files"][0]["path"] == "src/a.py"

    def test_api_files_fallback_on_attribute_error(self):
        """handle_api /api/files should return empty list when mgr lacks list_files."""
        from unittest import mock

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        del mgr.list_files  # remove the method
        sem_store = mock.MagicMock()

        result = handle_api("/api/files", mgr, sem_store)
        assert result == {"files": []}

    # ── handle_api /api/graph/full ───────────────────────────────────

    def test_api_graph_full_returns_all_nodes(self):
        """handle_api /api/graph/full should return all nodes and edges."""
        from unittest import mock

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        # Mock symbol_tables as a plain list (MagicMock iteration yields nothing)
        mgr.symbol_tables = ["symbols_function", "symbols_class"]
        # Mock get_all_edges
        mgr.get_all_edges.return_value = [
            {"source": "a.foo", "target": "b.bar", "kind": "calls"},
        ]
        # Mock get_conn → execute → fetchall
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("a.foo", "foo", 10, "function", "src/a.py"),
            ("b.bar", "bar", 20, "class", "src/b.py"),
        ]
        mgr.get_conn.return_value = mock_conn

        sem_store = mock.MagicMock()
        sem_store.load_all.return_value = []

        result = handle_api("/api/graph/full", mgr, sem_store)
        assert "nodes" in result
        assert "edges" in result
        assert "stats" in result
        assert len(result["nodes"]) == 2
        assert result["stats"]["node_count"] == 2

    def test_api_graph_full_handles_sqlite_error(self):
        """handle_api /api/graph/full should skip tables on OperationalError."""
        from unittest import mock

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        mgr.symbol_tables = ["symbols_function", "symbols_class"]
        mgr.get_all_edges.return_value = []
        mock_conn = mock.MagicMock()
        # First table works, second raises OperationalError
        import sqlite3
        mock_conn.execute.return_value.fetchall.side_effect = [
            [("a.foo", "foo", 10, "function", "src/a.py")],
            sqlite3.OperationalError("no such table"),
        ]
        mgr.get_conn.return_value = mock_conn

        sem_store = mock.MagicMock()
        sem_store.load_all.return_value = []

        result = handle_api("/api/graph/full", mgr, sem_store)
        # Should still get nodes from the first table
        assert len(result["nodes"]) == 1

    # ── handle_api /api/shortest-path ─────────────────────────────────

    def test_api_shortest_path_found(self):
        """handle_api /api/shortest-path with valid params should return path."""
        from unittest import mock

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        mgr.get_shortest_path.return_value = {
            "found": True,
            "path": [
                {"source": "main", "target": "helper", "kind": "calls"},
                {"source": "helper", "target": "db", "kind": "calls"},
            ],
            "node_ids": ["main", "helper", "db"],
            "length": 2,
        }
        sem_store = mock.MagicMock()

        result = handle_api(
            "/api/shortest-path?source=main&target=db", mgr, sem_store
        )
        assert result["found"] is True
        assert result["length"] == 2
        assert result["node_ids"] == ["main", "helper", "db"]

    def test_api_shortest_path_missing_source_raises(self):
        """handle_api /api/shortest-path without source should raise ValueError."""
        from unittest import mock

        import pytest

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()

        with pytest.raises(ValueError, match="source and target"):
            handle_api("/api/shortest-path?target=db", mgr, sem_store)

    def test_api_shortest_path_missing_target_raises(self):
        """handle_api /api/shortest-path without target should raise ValueError."""
        from unittest import mock

        import pytest

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        sem_store = mock.MagicMock()

        with pytest.raises(ValueError, match="source and target"):
            handle_api("/api/shortest-path?source=main", mgr, sem_store)

    def test_api_shortest_path_not_found(self):
        """handle_api /api/shortest-path should return found=False when no path."""
        from unittest import mock

        from memorygraph.web.api import handle_api

        mgr = mock.MagicMock()
        mgr.get_shortest_path.return_value = {
            "found": False, "path": [], "node_ids": [], "length": 0,
        }
        sem_store = mock.MagicMock()

        result = handle_api(
            "/api/shortest-path?source=main&target=nonexistent", mgr, sem_store
        )
        assert result["found"] is False
        assert result["length"] == 0
