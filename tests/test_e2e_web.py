"""End-to-end Web API tests: init → index → serve → HTTP → verify."""

import json
import threading
import time
import urllib.error
import urllib.request

import pytest


def _http_get(port: int, path: str) -> tuple[int, dict]:
    """Make an HTTP GET request and return (status_code, parsed_json_body)."""
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = json.loads(resp.read().decode())
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, {}


def test_e2e_web_health_and_status(git_repo):
    """Start the web server, hit /health and /api/status, verify responses."""
    from click.testing import CliRunner

    from memorygraph.cli.main import cli
    from memorygraph.web.server import WebServer

    # Setup: init + index
    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--project-root", str(git_repo)])
    assert result.exit_code == 0
    result = runner.invoke(cli, ["index", "--project-root", str(git_repo)])
    assert result.exit_code == 0

    port = 18765  # Non-standard port to avoid conflicts

    # Start server in background thread
    server = WebServer(str(git_repo), port=port)

    def _serve():
        server.start()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()

    # Wait for server to be ready (poll /health)
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5)
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.1)
    else:
        server.stop()
        pytest.fail("Server did not start within 3 seconds")

    try:
        # Test /health
        status, health = _http_get(port, "/health")
        assert status == 200, f"/health returned {status}"
        assert health["status"] == "ok", f"health status: {health}"
        from memorygraph import __version__
        assert health["version"] == __version__
        assert health["file_count"] > 0, f"file_count expected >0: {health}"
        assert health["symbol_count"] > 0, f"symbol_count expected >0: {health}"
        assert "uptime_seconds" in health
        assert "db_size_bytes" in health

        # Test /api/status
        status, api_status = _http_get(port, "/api/status")
        assert status == 200, f"/api/status returned {status}"
        assert api_status["files"] > 0
        assert api_status["symbols"] > 0

        # Test /api/search
        status, search = _http_get(port, "/api/search?q=greet")
        assert status == 200, f"/api/search returned {status}"
        assert "results" in search, "/api/search missing 'results' key"

        # Test /api/node — direct symbol lookup
        status, node_data = _http_get(port, "/api/node/greet")
        assert status == 200, f"/api/node/greet returned {status}"
        assert "symbol" in node_data
        assert "greet" in node_data["symbol"].lower()

        # Test /api/graph
        status, graph = _http_get(port, "/api/graph")
        assert status == 200, f"/api/graph returned {status}"
        assert "nodes" in graph
        assert "edges" in graph

        # Test /health again (uptime should have increased)
        status, health2 = _http_get(port, "/health")
        assert status == 200
        assert health2["uptime_seconds"] >= health["uptime_seconds"]

        # Test 404 for unknown endpoint
        status, err = _http_get(port, "/nonexistent")
        assert status == 404, f"expected 404, got {status}"

    finally:
        server.stop()


def test_e2e_web_metrics_endpoint(git_repo):
    """Start web server, hit /metrics, verify Prometheus format metrics."""
    from click.testing import CliRunner

    from memorygraph.cli.main import cli
    from memorygraph.web.server import WebServer

    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--project-root", str(git_repo)])
    assert result.exit_code == 0
    result = runner.invoke(cli, ["index", "--project-root", str(git_repo)])
    assert result.exit_code == 0

    port = 18766
    server = WebServer(str(git_repo), port=port)

    def _serve():
        server.start()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()

    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5)
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.1)
    else:
        server.stop()
        pytest.fail("Server did not start within 3 seconds")

    try:
        # Hit a few endpoints to generate metrics
        _http_get(port, "/api/status")
        _http_get(port, "/api/search?q=greet")
        _http_get(port, "/api/node/greet")

        # GET /metrics (Prometheus text format)
        url = f"http://127.0.0.1:{port}/metrics"
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode()
            assert resp.status == 200
            # Verify essential Prometheus format elements
            assert "memorygraph_requests_total" in body
            assert "memorygraph_queries_total" in body
            assert "memorygraph_errors_total" in body
            assert "memorygraph_index_operations_total" in body
            assert "memorygraph_files_indexed" in body
            assert "memorygraph_symbols_indexed" in body
            assert "memorygraph_edges_indexed" in body
            assert "memorygraph_request_latency_seconds" in body
            assert "# HELP" in body
            assert "# TYPE" in body
            # Verify latency histogram has expected buckets
            assert 'le="0.001"' in body
            assert 'le="+Inf"' in body

    finally:
        server.stop()


def test_e2e_web_annotate_roundtrip(git_repo):
    """POST annotation → GET /api/semantic → verify saved data round-trips."""
    from click.testing import CliRunner

    from memorygraph.cli.main import cli
    from memorygraph.web.server import WebServer

    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--project-root", str(git_repo)])
    assert result.exit_code == 0
    result = runner.invoke(cli, ["index", "--project-root", str(git_repo)])
    assert result.exit_code == 0

    port = 18767
    server = WebServer(str(git_repo), port=port)

    def _serve():
        server.start()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()

    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5)
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.1)
    else:
        server.stop()
        pytest.fail("Server did not start within 3 seconds")

    try:
        # POST annotation
        data = json.dumps({
            "file": "greet.py",
            "annotations": [
                {"symbol": "greet", "kind": "function",
                 "summary": "Greets user", "design_intent": "",
                 "pitfalls": ""}
            ],
            "unknowns": [],
            "insights": [],
            "module_summary": "Greeting module"
        }).encode()
        url = f"http://127.0.0.1:{port}/api/annotate"
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode())
            assert body["saved"] is True
            assert body["file"] == "greet.py"

        # GET /api/semantic — verify saved data
        status, semantic = _http_get(port, "/api/semantic?file=greet.py")
        assert status == 200
        assert semantic["file"] == "greet.py"
        assert len(semantic["annotations"]) == 1
        assert semantic["annotations"][0]["summary"] == "Greets user"
        assert semantic["annotations"][0]["symbol"] == "greet"
    finally:
        server.stop()
