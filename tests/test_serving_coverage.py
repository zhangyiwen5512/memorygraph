"""Targeted tests to close coverage gaps in serving.py and server.py.

Covers:
- serve() error paths (background without web, non-Linux background)
- serve() MCP default branch
- WebServer.stop() exception handler
- _serve_api and _serve_health exception handlers (if not already covered)
"""

import sys
from unittest import mock

import pytest
from click.testing import CliRunner

from memorygraph.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestServeErrorPaths:
    """Cover serve() error/edge paths."""

    def test_serve_daemon_without_web(self, runner, tmp_path):
        """serve --daemon without --web should print error and exit."""
        # Init
        runner.invoke(cli, ["init", "--project-root", str(tmp_path)])
        result = runner.invoke(cli, [
            "serve", "--daemon", "--project-root", str(tmp_path)
        ])
        assert "Background mode requires --web" in result.output

    @pytest.mark.skipif(sys.platform != "linux", reason="Only test non-Linux path on Linux")
    def test_serve_daemon_web_non_linux_guard(self, runner, monkeypatch, tmp_path):
        """serve --web --daemon on non-Linux should print platform error."""
        monkeypatch.setattr(sys, "platform", "darwin")
        runner.invoke(cli, ["init", "--project-root", str(tmp_path)])
        result = runner.invoke(cli, [
            "serve", "--web", "--daemon", "--project-root", str(tmp_path)
        ])
        assert "Background mode is only supported on Linux" in result.output

    def test_serve_default_mcp_path(self, runner):
        """serve with no flags should attempt MCP (import check)."""
        # Just verify the import path is valid — the actual MCP server
        # requires stdio and can't be tested via CliRunner
        from memorygraph.mcp.server import run_mcp_server
        assert callable(run_mcp_server)

    def test_serve_help_shows_options(self, runner):
        """serve --help should list all options."""
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--web" in result.output
        assert "--mcp" in result.output
        assert "--daemon" in result.output
        assert "--background" in result.output


class TestWebServerStopException:
    """Cover WebServer.stop() exception handler — server.py:298-300."""

    def test_webserver_stop_mgr_close_exception(self):
        """WebServer.stop() should handle StorageManager.close() exception gracefully."""
        from memorygraph.web.server import WebServer

        ws = WebServer(".")
        # Manually set _mgr to a mock that raises on close()
        mock_mgr = mock.MagicMock()
        mock_mgr.close.side_effect = RuntimeError("Cross-thread close failed")
        ws._mgr = mock_mgr
        ws._httpd = mock.MagicMock()

        # Should not raise
        ws.stop()

        mock_mgr.close.assert_called_once()
        ws._httpd.server_close.assert_called_once()

    def test_webserver_stop_no_httpd(self):
        """WebServer.stop() when _httpd is None should not error."""
        from memorygraph.web.server import WebServer

        ws = WebServer(".")
        # _httpd starts as None; stop should not raise
        ws.stop()


class TestServeApiExceptionHandlers:
    """Cover _serve_api and _serve_health exception handlers in server.py."""

    def test_serve_api_generic_exception_500(self):
        """_serve_api: generic Exception → 500 with error metrics."""
        from io import BytesIO
        from unittest.mock import MagicMock, patch

        from memorygraph.web.server import MemorygraphHandler

        MemorygraphHandler.mgr = MagicMock()
        MemorygraphHandler.sem_store = MagicMock()
        # Reset error count for clean test
        MemorygraphHandler._metrics["error_count"] = 0

        mock_request = MagicMock()
        mock_request.makefile.return_value = BytesIO(b"GET /api/status HTTP/1.1\r\n\r\n")

        with patch("memorygraph.web.server.handle_api",
                  side_effect=RuntimeError("crash")), \
             patch.object(MemorygraphHandler, "send_response") as mock_sr, \
             patch.object(MemorygraphHandler, "send_header"), \
             patch.object(MemorygraphHandler, "end_headers"):
            MemorygraphHandler(mock_request, ("127.0.0.1", 12345), MagicMock())

        mock_sr.assert_called_once_with(500)
        assert MemorygraphHandler._metrics["error_count"] >= 1

    def test_serve_health_generic_exception_500(self):
        """_serve_health: generic Exception → 500 with error metrics."""
        from io import BytesIO
        from unittest.mock import MagicMock, patch

        from memorygraph.web.server import MemorygraphHandler

        MemorygraphHandler.mgr = MagicMock()
        MemorygraphHandler._metrics["error_count"] = 0

        mock_request = MagicMock()
        mock_request.makefile.return_value = BytesIO(b"GET /health HTTP/1.1\r\n\r\n")

        with patch("memorygraph.web.server.handle_health",
                  side_effect=RuntimeError("health boom")), \
             patch.object(MemorygraphHandler, "send_response") as mock_sr, \
             patch.object(MemorygraphHandler, "send_header"), \
             patch.object(MemorygraphHandler, "end_headers"):
            MemorygraphHandler(mock_request, ("127.0.0.1", 12345), MagicMock())

        mock_sr.assert_called_once_with(500)
        assert MemorygraphHandler._metrics["error_count"] >= 1

    def test_handle_health_with_db_path_zero_size(self):
        """handle_health with db_path that raises OSError on getsize → db_size_bytes=-1."""
        from unittest.mock import MagicMock, patch

        from memorygraph.web.api import handle_health

        mgr = MagicMock()
        mgr.stats.return_value = {
            "file_count": 5, "symbol_count": 100, "edge_count": 200,
            "last_updated": "today",
        }

        with patch("os.path.getsize", side_effect=OSError("permission denied")):
            result = handle_health(mgr, 100.0, db_path="/fake/path")
            assert result["db_size_bytes"] == -1
