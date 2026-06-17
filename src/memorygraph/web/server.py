"""HTTP server with SSE for memorygraph."""
from __future__ import annotations

import contextlib
import json
import logging
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from memorygraph.semantic.store import SemanticStore  # pragma: no cover

from memorygraph.storage import StorageManager, create_storage_manager
from memorygraph.web.api import handle_annotate, handle_api, handle_delete_annotation, handle_health
from memorygraph.web.renderer import render_html

logger = logging.getLogger(__name__)

# Upper bound for in-memory latency samples per worker.
# After this limit, the oldest half are rotated out to prevent
# unbounded memory growth on long-running servers.
_MAX_LATENCY_SAMPLES = 10_000
_MAX_BODY_SIZE = 1_048_576  # 1 MiB — prevent memory exhaustion via large Content-Length


class SSEManager:
    """Manages Server-Sent Events for file change notifications."""

    def __init__(self):
        self._queues: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._queues.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._queues:
                self._queues.remove(q)

    def publish(self, event: str, data: dict) -> None:
        msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        with self._lock:
            for q in self._queues:
                q.put_nowait(msg)


class MemorygraphHandler(BaseHTTPRequestHandler):
    """HTTP request handler for memorygraph web UI and API.

    ``mgr``, ``sse``, and ``sem_store`` are set at class level by
    ``WebServer.start()`` before the first request arrives.  In this
    single-server design the assignment happens once at startup, but a
    class-level lock guards against hypothetical concurrent ``start()``
    calls (e.g. from tests or embedding into another framework).
    """

    mgr: StorageManager | None = None
    sse: SSEManager | None = None
    sem_store: SemanticStore | None = None
    start_time: float = 0.0
    db_path: str = ""
    _project_root: str = ""
    _init_lock = threading.Lock()
    # Metrics counters (incremented across all requests)
    _metrics: dict = {
        "index_count": 0, "query_count": 0, "error_count": 0,
        "request_count": 0, "latencies": [],
    }
    _metrics_lock = threading.Lock()

    # ── Response helpers ──────────────────────────────────────────────

    def _send_json(self, status: int, data: object) -> None:
        """Send a JSON response with the given HTTP status code."""
        payload = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def _send_text(self, status: int, content_type: str, body: bytes) -> None:
        """Send a raw text/binary response."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body)

    def _record_latency(self, latency: float) -> None:
        """Record a request latency sample, rotating out old samples when full."""
        with self._metrics_lock:
            self._metrics["request_count"] += 1
            lats = self._metrics["latencies"]
            if len(lats) >= _MAX_LATENCY_SAMPLES:
                # Rotate: keep most recent half to bound memory
                self._metrics["latencies"] = lats[-_MAX_LATENCY_SAMPLES // 2:]
            self._metrics["latencies"].append(latency)

    def do_GET(self) -> None:
        _start = time.monotonic()
        try:
            path = self.path.split("?")[0]

            if path == "/":
                self._serve_html()
            elif path == "/health":
                self._serve_health()
            elif path == "/metrics":
                self._serve_metrics()
            elif path == "/api/events":
                self._serve_sse()
            elif path.startswith("/api/"):
                self._serve_api(self.path)  # pass full path to preserve query string
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
        finally:
            self._record_latency(time.monotonic() - _start)

    def do_POST(self) -> None:
        """Handle POST requests for annotation editing."""
        _start = time.monotonic()
        try:
            path = self.path.split("?")[0]

            if path == "/api/annotate":
                self._handle_annotate()
            elif path == "/api/annotate/delete":
                self._handle_delete_annotate()
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
        finally:
            self._record_latency(time.monotonic() - _start)

    do_DELETE = do_POST  # noqa: N815 (stdlib HTTP method naming convention)

    def _read_json_body(self):
        """Read and parse JSON request body.

        Returns ``(data, True)`` on success, or ``(None, True)`` after
        sending a 400 error response (caller should return immediately).
        """
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"error": "Empty body"})
            return None, True
        if content_length > _MAX_BODY_SIZE:
            self._send_json(413, {"error": "Request body too large"})
            return None, True
        try:
            body = self.rfile.read(content_length)
            return json.loads(body), True
        except (json.JSONDecodeError, ValueError) as e:
            self._send_json(400, {"error": str(e)})
            return None, True

    def _handle_annotate(self):
        """Handle POST /api/annotate — save semantic annotations."""
        data, _ = self._read_json_body()
        if data is None:
            return
        assert self.mgr is not None and self.sem_store is not None
        try:
            self._send_json(200, handle_annotate(data, self.mgr, self.sem_store))
        except ValueError as e:
            self._send_json(400, {"error": str(e)})

    def _handle_delete_annotate(self):
        """Handle POST /api/annotate/delete — delete a semantic annotation."""
        data, _ = self._read_json_body()
        if data is None:
            return
        assert self.mgr is not None and self.sem_store is not None
        try:
            self._send_json(200, handle_delete_annotation(data, self.mgr, self.sem_store))
        except ValueError as e:
            self._send_json(400, {"error": str(e)})

    def _serve_html(self):
        html = render_html()
        self._send_text(200, "text/html; charset=utf-8", html.encode("utf-8"))

    def _serve_api(self, path):
        assert self.mgr is not None and self.sem_store is not None
        try:
            result = handle_api(path, self.mgr, self.sem_store, self._project_root)
            self._send_json(200, result)
            if "/api/search" in path or "/api/node" in path:
                with self._metrics_lock:
                    self._metrics["query_count"] += 1
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            with self._metrics_lock:
                self._metrics["error_count"] += 1

    def _serve_health(self):
        """Handle GET /health — return server health status as JSON."""
        assert self.mgr is not None
        try:
            with self._metrics_lock:
                metrics_snapshot = dict(self._metrics)
            result = handle_health(self.mgr, self.start_time, self.db_path, metrics_snapshot)
            self._send_json(200, result)
        except Exception as e:
            self._send_json(500, {"status": "error", "error": str(e)})
            with self._metrics_lock:
                self._metrics["error_count"] += 1

    def _serve_metrics(self):
        """Handle GET /metrics — Prometheus text format."""
        with self._metrics_lock:
            request_count = self._metrics.get("request_count", 0)
            query_count = self._metrics.get("query_count", 0)
            error_count = self._metrics.get("error_count", 0)
            index_count = self._metrics.get("index_count", 0)
            latencies = list(self._metrics.get("latencies", []))

        db_file_count = db_symbol_count = db_edge_count = 0
        try:
            if self.mgr is not None:
                st = self.mgr.stats()
                db_file_count = st.get("file_count", 0)
                db_symbol_count = st.get("symbol_count", 0)
                db_edge_count = st.get("edge_count", 0)
        except Exception:  # pragma: no cover — DB stats fetch failure, hard to trigger in tests
            logger.warning("Failed to fetch DB stats for health endpoint", exc_info=True)

        body = _format_prometheus_metrics(
            request_count, query_count, error_count, index_count,
            latencies, db_file_count, db_symbol_count, db_edge_count,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(body)

    def _serve_sse(self):
        assert self.sse is not None
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        q = self.sse.subscribe()
        try:
            while True:
                try:
                    msg = q.get(timeout=30)
                    self.wfile.write(msg.encode())
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(": heartbeat\n\n".encode())
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected during SSE — normal, nothing to do.
            pass
        finally:
            self.sse.unsubscribe(q)

    def log_message(self, fmt, *args) -> None:  # noqa: ARG002
        pass  # Suppress access logs


class WebServer:
    """memorygraph web server wrapper."""

    def __init__(self, project_root: str, port: int = 8765, host: str = "127.0.0.1"):
        self._project_root = project_root
        self._port = port
        self._host = host
        self._httpd: HTTPServer | None = None
        self._sse = SSEManager()
        self._stop_event = threading.Event()   # shutdown signal
        self._ready_event = threading.Event()  # ready signal
        self._mgr: StorageManager | None = None  # store for stop()

    @property
    def sse(self) -> SSEManager:
        return self._sse

    def start(self) -> None:
        from memorygraph.storage.backend import create_semantic_store
        from memorygraph.storage.connection import get_db_path

        mgr = create_storage_manager(self._project_root)
        mgr.initialize()
        sem_store = create_semantic_store(self._project_root)

        with MemorygraphHandler._init_lock:
            MemorygraphHandler.mgr = mgr
            MemorygraphHandler.sse = self._sse
            MemorygraphHandler.sem_store = sem_store
            MemorygraphHandler.start_time = time.time()
            MemorygraphHandler.db_path = get_db_path(self._project_root)
            MemorygraphHandler._project_root = self._project_root

        self._mgr = mgr
        self._httpd = ThreadingHTTPServer((self._host, self._port), MemorygraphHandler)
        self._httpd.socket.settimeout(0.5)  # Periodic wakeup to check _stop_event

        display_host = self._host if self._host != "0.0.0.0" else "localhost"  # nosec B104
        # Startup health self-check (best-effort; non-fatal on failure)
        try:
            health = handle_health(mgr, MemorygraphHandler.start_time, MemorygraphHandler.db_path)
            logger.info("memorygraph web server at http://%s:%d", display_host, self._port)
            logger.info("startup health: %s", json.dumps(health))
        except Exception:
            logger.info("memorygraph web server at http://%s:%d", display_host, self._port)
            logger.debug("Startup health check skipped", exc_info=True)

        self._ready_event.set()

        # Interruptible serve loop instead of serve_forever()
        while not self._stop_event.is_set():
            self._httpd.handle_request()  # pragma: no cover — timing-dependent in thread

    def stop(self) -> None:
        self._stop_event.set()
        if self._httpd:
            with contextlib.suppress(Exception):
                self._httpd.server_close()
        if self._mgr:
            try:
                self._mgr.close()
            except Exception:
                logger.debug("Could not close StorageManager (may be cross-thread)", exc_info=True)

    def wait_ready(self, timeout: float = 5.0) -> bool:
        """Wait for server to be ready (for testing)."""
        return self._ready_event.wait(timeout=timeout)


def _create_metrics_state() -> tuple[dict, threading.Lock]:
    """Create the metrics dict and lock shared across ASGI workers."""
    metrics: dict = {
        "index_count": 0,
        "query_count": 0,
        "error_count": 0,
        "request_count": 0,
        "latencies": [],
    }
    return metrics, threading.Lock()


def create_asgi_app(
    project_root: str,
    mgr: StorageManager,
    sem_store,
    sse: SSEManager,
    start_time: float,
    db_path: str,
) -> Callable:
    """Create an ASGI application for uvicorn.

    Returns an ASGI 3.0 callable that routes requests to the same handler
    functions used by the http.server path.  This gives us true concurrency
    (uvicorn's async event loop) while reusing 100% of the existing logic.
    """
    _metrics, _metrics_lock = _create_metrics_state()

    async def asgi_app(scope, receive, send):
        if scope["type"] != "http":
            return

        method = scope["method"]
        path = scope["path"]
        query_string = scope.get("query_string", b"").decode("latin-1")
        full_path = f"{path}?{query_string}" if query_string else path

        _start = time.monotonic()

        # Read request body
        body = b""
        while True:
            message = await receive()
            if message["type"] == "http.request":
                body += message.get("body", b"")
                if not message.get("more_body", False):
                    break

        # ── Route ──
        status = 200
        headers: list[tuple[bytes, bytes]] = []
        response_body = b""

        async def send_response(status_code: int, content_type: str, data: bytes):
            nonlocal status, headers, response_body
            status = status_code
            headers = [
                (b"content-type", content_type.encode()),
                (b"access-control-allow-origin", b"*"),
            ]
            response_body = data

        try:
            if path == "/":
                if method == "GET":
                    html = render_html()
                    await send_response(200, "text/html; charset=utf-8", html.encode("utf-8"))
                else:
                    await send_response(405, "text/plain", b"Method Not Allowed")

            elif path == "/health":
                if method == "GET":
                    with _metrics_lock:
                        snap = dict(_metrics)
                    result = handle_health(mgr, start_time, db_path, snap)
                    await send_response(200, "application/json", json.dumps(result).encode())
                else:
                    await send_response(405, "text/plain", b"Method Not Allowed")

            elif path == "/metrics":
                if method == "GET":
                    with _metrics_lock:
                        request_count = _metrics.get("request_count", 0)
                        query_count = _metrics.get("query_count", 0)
                        error_count = _metrics.get("error_count", 0)
                        index_count = _metrics.get("index_count", 0)
                        latencies = list(_metrics.get("latencies", []))
                    db_file_count = db_symbol_count = db_edge_count = 0
                    try:
                        if mgr is not None:
                            st = mgr.stats()
                            db_file_count = st.get("file_count", 0)
                            db_symbol_count = st.get("symbol_count", 0)
                            db_edge_count = st.get("edge_count", 0)
                    except Exception:  # pragma: no cover
                        logger.warning("Failed to fetch DB stats for /metrics", exc_info=True)
                    body = _format_prometheus_metrics(
                        request_count, query_count, error_count, index_count,
                        latencies, db_file_count, db_symbol_count, db_edge_count,
                    ).encode()
                    await send_response(200, "text/plain; version=0.0.4", body)
                else:
                    await send_response(405, "text/plain", b"Method Not Allowed")

            elif path == "/api/events":
                # SSE via ASGI — use chunked response
                if method == "GET":
                    await _asgi_sse_handler(send, sse)
                    return  # _asgi_sse_handler manages its own send
                else:
                    await send_response(405, "text/plain", b"Method Not Allowed")

            elif path.startswith("/api/annotate/delete"):
                if method in ("POST", "DELETE"):
                    try:
                        data = json.loads(body) if body else {}
                    except json.JSONDecodeError:
                        await send_response(400, "application/json", json.dumps({"error": "Invalid JSON"}).encode())
                    else:
                        try:
                            result = handle_delete_annotation(data, mgr, sem_store)
                            await send_response(200, "application/json", json.dumps(result).encode())
                        except ValueError as e:
                            await send_response(400, "application/json", json.dumps({"error": str(e)}).encode())
                else:
                    await send_response(405, "text/plain", b"Method Not Allowed")

            elif path == "/api/annotate":
                if method == "POST":
                    try:
                        data = json.loads(body) if body else {}
                    except json.JSONDecodeError:
                        await send_response(400, "application/json", json.dumps({"error": "Invalid JSON"}).encode())
                    else:
                        try:
                            result = handle_annotate(data, mgr, sem_store)
                            await send_response(200, "application/json", json.dumps(result).encode())
                        except ValueError as e:
                            await send_response(400, "application/json", json.dumps({"error": str(e)}).encode())
                else:
                    await send_response(405, "text/plain", b"Method Not Allowed")

            elif path.startswith("/api/"):
                if method == "GET":
                    try:
                        result = handle_api(full_path, mgr, sem_store, project_root)
                        await send_response(200, "application/json", json.dumps(result, default=str).encode())
                        if "/api/search" in path or "/api/node" in path:
                            with _metrics_lock:
                                _metrics["query_count"] += 1
                    except ValueError as e:
                        await send_response(400, "application/json", json.dumps({"error": str(e)}).encode())
                    except Exception as e:
                        await send_response(500, "application/json", json.dumps({"error": str(e)}).encode())
                        with _metrics_lock:
                            _metrics["error_count"] += 1
                else:
                    await send_response(405, "text/plain", b"Method Not Allowed")

            else:
                await send_response(404, "text/plain", b"Not found")

        except Exception as exc:  # pragma: no cover — safety net
            await send_response(500, "application/json", json.dumps({"error": str(exc)}).encode())
            with _metrics_lock:
                _metrics["error_count"] += 1

        finally:
            _latency = time.monotonic() - _start
            with _metrics_lock:
                _metrics["request_count"] += 1
                lats = _metrics["latencies"]
                if len(lats) >= _MAX_LATENCY_SAMPLES:
                    _metrics["latencies"] = lats[-_MAX_LATENCY_SAMPLES // 2:]
                _metrics["latencies"].append(_latency)

        # Send response
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": headers,
        })
        await send({
            "type": "http.response.body",
            "body": response_body,
        })

    return asgi_app


async def _asgi_sse_handler(send, sse):
    """Minimal SSE handler for ASGI — keeps connection open and streams events."""
    q = sse.subscribe()
    # Send response start
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"text/event-stream"),
            (b"cache-control", b"no-cache"),
            (b"connection", b"keep-alive"),
        ],
    })
    try:
        import asyncio
        while True:
            try:
                msg = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)
                await send({
                    "type": "http.response.body",
                    "body": b": heartbeat\n\n",
                    "more_body": True,
                })
                continue
            try:
                await send({
                    "type": "http.response.body",
                    "body": msg.encode(),
                    "more_body": True,
                })
            except Exception:  # pragma: no cover — client disconnect
                break
    except Exception:  # pragma: no cover — client disconnect during SSE
        logger.debug("SSE connection closed by client", exc_info=True)
    finally:
        sse.unsubscribe(q)


def _format_prometheus_metrics(
    request_count: int, query_count: int, error_count: int, index_count: int,
    latencies: list[float],
    db_file_count: int, db_symbol_count: int, db_edge_count: int,
) -> str:
    """Format metrics counters + latency histogram as Prometheus text.

    Extracted from ``_serve_metrics`` and ``_build_metrics_body`` to keep
    the Prometheus exposition format in a single place.
    """
    buckets = [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
    bucket_counts = [0] * len(buckets)
    latency_sum = 0.0
    for lat in latencies:
        latency_sum += lat
        for i, bound in enumerate(buckets):
            if lat <= bound:
                bucket_counts[i] += 1

    lines = [
        "# HELP memorygraph_requests_total Total HTTP requests served.",
        "# TYPE memorygraph_requests_total counter",
        f"memorygraph_requests_total {request_count}",
        "",
        "# HELP memorygraph_queries_total Total API search/node queries.",
        "# TYPE memorygraph_queries_total counter",
        f"memorygraph_queries_total {query_count}",
        "",
        "# HELP memorygraph_errors_total Total HTTP error responses.",
        "# TYPE memorygraph_errors_total counter",
        f"memorygraph_errors_total {error_count}",
        "",
        "# HELP memorygraph_index_operations_total Total index operations.",
        "# TYPE memorygraph_index_operations_total counter",
        f"memorygraph_index_operations_total {index_count}",
        "",
        "# HELP memorygraph_files_indexed Number of indexed source files.",
        "# TYPE memorygraph_files_indexed gauge",
        f"memorygraph_files_indexed {db_file_count}",
        "",
        "# HELP memorygraph_symbols_indexed Total symbols in knowledge graph.",
        "# TYPE memorygraph_symbols_indexed gauge",
        f"memorygraph_symbols_indexed {db_symbol_count}",
        "",
        "# HELP memorygraph_edges_indexed Total call-graph edges.",
        "# TYPE memorygraph_edges_indexed gauge",
        f"memorygraph_edges_indexed {db_edge_count}",
        "",
        "# HELP memorygraph_request_latency_seconds Request latency histogram.",
        "# TYPE memorygraph_request_latency_seconds histogram",
    ]
    cumulative = 0
    for i, bound in enumerate(buckets):
        cumulative += bucket_counts[i]
        lines.append(
            f"memorygraph_request_latency_seconds_bucket{{le=\"{bound}\"}} "
            f"{cumulative}"
        )
    lines.append(
        f"memorygraph_request_latency_seconds_bucket{{le=\"+Inf\"}} "
        f"{len(latencies)}"
    )
    lines.append(
        f"memorygraph_request_latency_seconds_sum {latency_sum:.6f}"
    )
    lines.append(
        f"memorygraph_request_latency_seconds_count {len(latencies)}"
    )
    lines.append("")

    return "\n".join(lines)
