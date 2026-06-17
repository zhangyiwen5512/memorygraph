"""REST API handlers for memorygraph web server."""
import os
import time
from collections import deque
from urllib.parse import parse_qs, urlparse

from memorygraph.semantic.models import (
    Annotation,
    Insight,
    SemanticDocument,
    Unknown,
)
from memorygraph.semantic.store import SemanticStore
from memorygraph.storage import StorageManager


def handle_api(
    path: str,
    mgr: StorageManager,
    sem_store: SemanticStore,
    project_root: str = "",
) -> dict:
    """Dispatch a REST API request to the appropriate handler.

    Routes URL paths (``/api/graph``, ``/api/search``, ``/api/node``,
    ``/api/status``, ``/api/semantic``) to the corresponding graph-traversal,
    search, node-lookup, status, or semantic-data handler.

    Args:
        path: Raw URL path including query string (e.g. ``/api/search?q=foo``).
        mgr: A :class:`StorageManager` instance for graph queries.
        sem_store: A :class:`SemanticStore` instance for semantic data.
        project_root: Filesystem path to the project root (for tours, etc.).

    Returns:
        A JSON-serializable dict with endpoint-specific keys.

    Raises:
        ValueError: If the path does not match a known endpoint.
    """
    parsed = urlparse(path)
    params = parse_qs(parsed.query)

    if path.startswith("/api/graph/full"):
        full_nodes, full_edges = _fetch_all_nodes(mgr, sem_store)
        return {"nodes": full_nodes, "edges": full_edges,
                "stats": {"node_count": len(full_nodes), "edge_count": len(full_edges)}}

    elif path.startswith("/api/graph"):
        root = params.get("root", [None])[0]
        depth = int(params.get("depth", ["2"])[0])
        nodes: list[dict] = []
        edges_list: list[dict] = []
        seen_nodes: set[str] = set()
        # Truncation tracking (P1: truncation-aware BFS)
        max_bfs_nodes = 500
        truncated_branches: list[dict] = []

        if root:
            queue: deque[tuple[str, int]] = deque([(root, 0)])
            while queue and len(nodes) < max_bfs_nodes:
                current, d = queue.popleft()
                if current in seen_nodes:
                    continue
                seen_nodes.add(current)
                node = mgr.get_node(current)
                if node:
                    nodes.append(_node_to_json(node, sem_store))
                if d < depth:
                    for c in mgr.get_callers(current, depth=1):
                        if c["source"] not in seen_nodes:
                            queue.append((c["source"], d + 1))
                        edges_list.append({"source": c["source"], "target": c["target"], "kind": "calls"})
                    for c in mgr.get_callees(current, depth=1):
                        if c["target"] not in seen_nodes:
                            queue.append((c["target"], d + 1))
                        edges_list.append({"source": c["source"], "target": c["target"], "kind": "calls"})

            # Collect truncation info for remaining queue items
            if queue and len(nodes) >= max_bfs_nodes:
                remaining: dict[str, tuple[int, str]] = {}
                for sym, _d in queue:
                    if sym not in seen_nodes:
                        remaining[sym] = (_d, "caller" if any(
                            c["target"] == sym for c in mgr.get_callees(sym, depth=1)
                        ) else "callee")
                truncated_branches = [
                    {"symbol": s, "depth": dd, "direction": direc}
                    for s, (dd, direc) in remaining.items()
                ]

        return {
            "nodes": nodes,
            "edges": edges_list,
            "truncated": len(truncated_branches) > 0,
            "total_available": len(seen_nodes) + len(truncated_branches),
            "truncated_branches": truncated_branches[:20],  # cap at 20
        }

    elif path.startswith("/api/search"):
        q = params.get("q", [""])[0]
        from memorygraph.config import DEFAULT_QUERY_LIMIT
        limit = int(params.get("limit", [str(DEFAULT_QUERY_LIMIT)])[0])
        if not q:
            return {"results": []}
        results = mgr.semantic_search(q, limit=limit)
        return {"results": [{
            "symbol": r["qualified_name"], "kind": r["kind"],
            "file": r["file_path"], "line": r.get("start_line")
        } for r in results]}

    elif path.startswith("/api/node"):
        name = path.split("/api/node/", 1)[-1]
        if not name:
            raise ValueError("missing node name")
        node = mgr.get_node(name)
        if not node:
            raise ValueError(f"node not found: {name}")
        callers = mgr.get_callers(name, depth=1)
        callees = mgr.get_callees(name, depth=1)
        return {
            "symbol": name, "node": dict(node),
            "callers": [{"source": c["source"], "depth": c["depth"]} for c in callers],
            "callees": [{"target": c["target"], "depth": c["depth"]} for c in callees],
        }

    elif path == "/api/status":
        stats = mgr.stats()
        coverage = sem_store.get_coverage(
            total_symbols=stats["symbol_count"],
            file_count=stats["file_count"]
        )
        return {"files": stats["file_count"], "symbols": stats["symbol_count"],
                "edges": stats["edge_count"], "coverage": coverage,
                "last_updated": stats["last_updated"]}

    elif path.startswith("/api/semantic"):
        # GET /api/semantic?file=path/to/file.py
        file_path = params.get("file", [None])[0]
        if file_path:
            doc = sem_store.load(file_path)
            if doc:
                return {
                    "file": doc.file,
                    "module_summary": doc.module_summary,
                    "annotations": [
                        {"symbol": a.symbol, "kind": a.kind,
                         "summary": a.summary, "design_intent": a.design_intent,
                         "pitfalls": a.pitfalls}
                        for a in doc.annotations
                    ],
                    "unknowns": [
                        {"symbol": u.symbol, "question": u.question,
                         "context": u.context}
                        for u in doc.unknowns
                    ],
                    "insights": [
                        {"insight": i.insight,
                         "related_symbols": i.related_symbols}
                        for i in doc.insights
                    ],
                }
            return {"file": file_path, "annotations": [], "unknowns": [], "insights": []}
        return {"error": "missing file parameter"}

    elif path == "/api/files":
        try:
            file_list = mgr.list_files()
            return {"files": file_list}
        except AttributeError:
            return {"files": []}

    elif path.startswith("/api/shortest-path"):
        source = params.get("source", [None])[0]
        target = params.get("target", [None])[0]
        if not source or not target:
            raise ValueError("source and target query params are required")
        result = mgr.get_shortest_path(source, target)
        return result

    elif path == "/api/tours":
        tours = _load_tours(project_root)
        return {"tours": tours}

    elif path.startswith("/api/graph/layers"):
        layers = _compute_layers(mgr, sem_store)
        return {"layers": layers}

    raise ValueError(f"unknown endpoint: {path}")


def handle_health(
    mgr: StorageManager,
    start_time: float,
    db_path: str = "",
    metrics: dict | None = None,
) -> dict:
    """Handle GET /health — return server health status.

    Returns a JSON-serializable dict with server status, version, uptime,
    database size, indexed symbol counts, and runtime diagnostics.
    Designed as a lightweight liveness/readiness probe suitable for
    monitoring and orchestration.

    Args:
        mgr: A :class:`StorageManager` instance for database statistics.
        start_time: ``time.time()`` when the server started (for uptime).
        db_path: Filesystem path to the SQLite database file, used to
            compute ``db_size_bytes``.  When empty the field is omitted.
        metrics: Optional dict of request metrics counters.

    Returns:
        A dict with keys ``status``, ``version``, ``uptime_seconds``,
        ``db_size_bytes``, ``file_count``, ``symbol_count``,
        ``edge_count``, ``memory_usage_mb``, ``last_indexed_at``,
        ``metrics``, ``db_status``, ``platform``, ``python_version``.
    """
    import sys as _sys

    from memorygraph import __version__

    stats = mgr.stats()
    uptime = int(time.time() - start_time)
    result: dict = {
        "status": "ok",
        "version": __version__,
        "uptime_seconds": uptime,
        "file_count": stats["file_count"],
        "symbol_count": stats["symbol_count"],
        "edge_count": stats["edge_count"],
        "platform": _sys.platform,
        "python_version": _sys.version,
    }

    if db_path:
        try:
            result["db_size_bytes"] = os.path.getsize(db_path)
        except OSError:
            result["db_size_bytes"] = -1

    # Memory usage (best-effort via /proc on Linux)
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    result["memory_usage_mb"] = int(line.split()[1]) // 1024
                    break
    except (OSError, ValueError, IndexError):
        result["memory_usage_mb"] = -1

    # Last indexed timestamp (from stats or DB)
    result["last_indexed_at"] = stats.get("last_updated", "")

    # Request metrics (if available)
    if metrics:
        result["metrics"] = dict(metrics)
        # Compute index rate if we have counts and uptime > 0
        index_count = metrics.get("index_count", 0)
        if index_count > 0 and uptime > 0:
            result["index_rate_per_minute"] = round(
                index_count / (uptime / 60), 2
            )

    # Lightweight DB ping: use a simple query instead of the full stats() call
    try:
        mgr.get_conn().execute("SELECT 1")
        result["db_status"] = "connected"
    except Exception:
        result["db_status"] = "error"

    return result


def handle_annotate(data: dict, mgr: StorageManager, sem_store: SemanticStore) -> dict:
    """Handle POST /api/annotate — save semantic annotations.

    Request body format:
    {
        "file": "path/to/file.py",
        "annotations": [
            {"symbol": "func_name", "kind": "function",
             "summary": "...", "design_intent": "...", "pitfalls": "..."}
        ],
        "unknowns": [
            {"symbol": "func_name", "question": "...", "context": "..."}
        ],
        "insights": [
            {"insight": "...", "related_symbols": ["sym1", "sym2"]}
        ],
        "module_summary": "Optional module-level summary"
    }
    """
    file_path = data.get("file")
    if not file_path:
        raise ValueError("missing 'file' field")

    # Build SemanticDocument from request data
    doc = SemanticDocument(
        file=file_path,
        source="web-ui",
        module_summary=data.get("module_summary", ""),
    )

    for ann in data.get("annotations", []):
        doc.annotations.append(Annotation(
            symbol=ann.get("symbol", ""),
            kind=ann.get("kind", "unknown"),
            summary=ann.get("summary", ""),
            design_intent=ann.get("design_intent", ""),
            pitfalls=ann.get("pitfalls", ""),
        ))

    for unk in data.get("unknowns", []):
        doc.unknowns.append(Unknown(
            symbol=unk.get("symbol", ""),
            question=unk.get("question", ""),
            context=unk.get("context", ""),
        ))

    for ins in data.get("insights", []):
        doc.insights.append(Insight(
            insight=ins.get("insight", ""),
            related_symbols=ins.get("related_symbols", []),
        ))

    # Save to store (merge with existing)
    sem_store.save(doc)

    return {
        "saved": True,
        "file": file_path,
        "annotations": len(doc.annotations),
        "unknowns": len(doc.unknowns),
        "insights": len(doc.insights),
    }


def handle_delete_annotation(data: dict, mgr: StorageManager, sem_store: SemanticStore) -> dict:
    """Handle POST /api/annotate/delete — remove a semantic annotation."""
    file_path = data.get("file")
    symbol = data.get("symbol")
    if not file_path or not symbol:
        raise ValueError("missing 'file' or 'symbol' field")
    idx = data.get("index", 0)
    ok = sem_store.delete_annotation(file_path, symbol, idx)
    return {"deleted": ok, "file": file_path, "symbol": symbol}


def _node_to_json(node: dict, sem_store: SemanticStore) -> dict:
    """Serialize a graph node to a JSON-safe dict, enriched with semantic data.

    Extracts the qualified name, kind, source line, file path, and — when
    available — the module role, cyclomatic complexity, and rank from the
    semantic store.

    Args:
        node: A raw symbol dict from the database (e.g. from ``get_node``).
        sem_store: A :class:`SemanticStore` instance for enrichment lookups.

    Returns:
        A JSON-serializable dict with keys ``id``, ``kind``, ``line``,
        ``file``, and optionally ``role``, ``complexity``, and ``rank``.
    """
    qn = node.get("qualified_name", "?")
    kind = node.get("kind", "?")
    result = {"id": qn, "kind": str(kind), "line": node.get("start_line", "?")}
    for key in ("file_path", "file", "path"):
        if key in node:
            result["file"] = node[key]
            break
    for doc in sem_store.load_all():
        if doc.module_roles and qn in doc.module_roles:
            result["role"] = doc.module_roles[qn]
        if doc.metrics and doc.metrics.get("complexity"):
            for c in doc.metrics["complexity"]:
                if c["name"] == node.get("name"):
                    result["complexity"] = c["complexity"]
                    result["rank"] = c["rank"]
                    break
    return result


# ── New endpoint helpers ──────────────────────────────────────────────

# Architecture layer detection: regex patterns on file paths.
_LAYER_PATTERNS: list[tuple[str, str]] = [
    ("api", r"/(api|routes?|endpoints?|controllers?|handlers?|views)/"),
    ("service", r"/(service[s]?|business|domain|logic|usecases?)/"),
    ("data", r"/(data|db|database|model[s]?|repository|repositories|migration[s]?|schema[s]?)/"),
    ("ui", r"/(ui|components?|views?|pages?|templates?|widgets?)/"),
    ("utility", r"/(util[s]?|helper[s]?|common|shared|lib[s]?)/"),
    ("config", r"/(config[s]?|setting[s]?|env)/"),
]


def _detect_layer(file_path: str, role: str = "") -> str:
    """Classify a file into an architecture layer.

    Uses regex patterns on the file path.  When ``role`` is provided
    from the semantic store it takes precedence over the path heuristic.
    """
    import re

    role_lower = role.lower()
    if role_lower:
        for layer, _ in _LAYER_PATTERNS:
            if layer in role_lower:
                return layer

    for layer, pattern in _LAYER_PATTERNS:
        if re.search(pattern, "/" + file_path, re.IGNORECASE):
            return layer
    return "other"


def _fetch_all_nodes(mgr: StorageManager, sem_store: SemanticStore) -> tuple[list[dict], list[dict]]:
    """Batch-fetch all symbols and edges for full graph export.

    Returns ``(nodes, edges)`` where each node includes layer enrichment
    from the semantic store.
    """
    nodes: list[dict] = []
    edges_list: list[dict] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str]] = set()

    # Collect roles from semantic store
    roles: dict[str, str] = {}
    for doc in sem_store.load_all():
        if doc.module_roles:
            roles.update(doc.module_roles)

    # Collect all nodes from all symbol tables via batch SQL
    try:
        conn = mgr.get_conn()
        import sqlite3

        for table_name in mgr.symbol_tables:
            try:
                cur = conn.execute(
                    f"""SELECT s.qualified_name, s.name, s.start_line,
                               s.kind, f.path AS file_path
                        FROM {table_name} s
                        JOIN files f ON f.id = s.file_id"""  # nosec B608
                )
                for row in cur.fetchall():
                    qn = row[0]
                    if qn in seen_nodes:
                        continue
                    seen_nodes.add(qn)
                    file_path = row[4] or ""
                    layer = _detect_layer(file_path, roles.get(qn, ""))
                    nodes.append({
                        "id": qn,
                        "kind": row[3] or "unknown",
                        "line": row[2] or 0,
                        "file": file_path,
                        "layer": layer,
                    })
            except sqlite3.OperationalError:
                continue
    except Exception:
        pass

    # Collect edges
    try:
        for edge in mgr.get_all_edges():
            key = (edge["source"], edge["target"])
            if key not in seen_edges:
                seen_edges.add(key)
                edges_list.append({
                    "source": edge["source"],
                    "target": edge["target"],
                    "kind": edge.get("kind", "calls"),
                })
    except AttributeError:
        pass

    return nodes, edges_list


def _load_tours(project_root: str) -> list[dict]:
    """Load tour definitions from ``.memorygraph/tours/*.json``."""
    import json
    from pathlib import Path

    if not project_root:
        return []
    tours_dir = Path(project_root) / ".memorygraph" / "tours"
    if not tours_dir.exists():
        return []
    tours: list[dict] = []
    for f in sorted(tours_dir.glob("*.json")):
        try:
            tours.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return tours


def _compute_layers(mgr: StorageManager, sem_store: SemanticStore) -> dict[str, dict]:
    """Compute architecture-layer assignments for all indexed files."""
    layers: dict[str, dict] = {
        "api": {"nodes": [], "color": "#f85149"},
        "service": {"nodes": [], "color": "#1f6feb"},
        "data": {"nodes": [], "color": "#238636"},
        "ui": {"nodes": [], "color": "#a371f7"},
        "utility": {"nodes": [], "color": "#d29922"},
        "config": {"nodes": [], "color": "#8b949e"},
        "other": {"nodes": [], "color": "#484f58"},
    }

    # Collect roles from semantic store
    roles: dict[str, str] = {}
    for doc in sem_store.load_all():
        if doc.module_roles:
            roles.update(doc.module_roles)

    try:
        files = mgr.list_files()
    except AttributeError:
        return {"layers": layers}

    for f in files:
        file_path = f.get("path", "")
        symbol_count = f.get("symbol_count", 0)
        if not file_path or symbol_count == 0:
            continue

        try:
            symbols = mgr.get_symbols_for_file(file_path)
        except AttributeError:
            continue

        for sym in symbols:
            qn = sym.get("qualified_name", "")
            if not qn:
                continue
            layer = _detect_layer(file_path, roles.get(qn, ""))
            layers[layer]["nodes"].append(qn)

    return {"layers": layers}
