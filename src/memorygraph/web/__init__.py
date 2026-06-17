"""Interactive web visualization and REST API for memorygraph.

Components:
  - WebServer: HTTP server with SSE, health/metrics, and API endpoints
  - SSEManager: publish/subscribe event bus for real-time UI updates
  - MemorygraphHandler: BaseHTTPRequestHandler routing GET/POST/DELETE
  - handle_api / handle_health / handle_annotate: API endpoint handlers
  - render_html: server-side HTML rendering
"""
from memorygraph.web.server import WebServer

__all__ = ["WebServer"]
