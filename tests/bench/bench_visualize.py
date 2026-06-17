"""Export/visualization performance benchmarks.

Usage:
    python tests/bench/bench_visualize.py /tmp/flask-test
"""
import json
import sys
import tempfile
import time
from pathlib import Path

from memorygraph.storage import StorageManager


def bench_export(project_root: str) -> dict:
    """Benchmark full graph data export (collection + JSON serialization)."""
    mgr = StorageManager(project_root)
    mgr.initialize()

    # ── Node collection ──
    start = time.perf_counter()
    nodes = []
    edges_list = []
    seen = set()

    for file_row in mgr.list_files():
        symbols = mgr.get_symbols_for_file(file_row["path"])
        for sym in symbols:
            qn = sym.get("qualified_name", "?")
            if qn in seen:
                continue
            seen.add(qn)
            nodes.append({
                "id": qn,
                "kind": sym.get("kind", "?"),
                "file": file_row["path"],
                "line": sym.get("start_line"),
            })

    # Collect edges
    conn = mgr._get_conn()
    edge_rows = conn.execute(
        "SELECT source, target, kind FROM edges LIMIT 50000"
    ).fetchall()
    for e in edge_rows:
        edges_list.append({
            "source": e["source"],
            "target": e["target"],
            "kind": e["kind"],
        })

    collection_elapsed = time.perf_counter() - start

    # ── JSON serialization ──
    json_start = time.perf_counter()
    output = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump({"nodes": nodes, "edges": edges_list}, output, default=str)
    output.close()
    json_elapsed = time.perf_counter() - json_start

    Path(output.name).unlink()
    mgr.close()

    return {
        "node_count": len(nodes),
        "edge_count": len(edges_list),
        "collection_seconds": round(collection_elapsed, 3),
        "json_serialize_seconds": round(json_elapsed, 3),
        "total_seconds": round(collection_elapsed + json_elapsed, 3),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python tests/bench/bench_visualize.py <project_root>")
        print("  e.g.  python tests/bench/bench_visualize.py /tmp/flask-test")
        sys.exit(1)

    project_root = sys.argv[1]
    print(f"Benchmarking export on: {project_root}")
    result = bench_export(project_root)
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
