"""Indexing performance benchmarks.

Usage:
    python tests/bench/bench_index.py /tmp/flask-test
    python tests/bench/bench_index.py /tmp/black-test
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

from memorygraph.cli.shared import _collect_files
from memorygraph.parsing.batch import ParallelParser
from memorygraph.parsing.registry import LanguageRegistry
from memorygraph.storage import StorageManager


def bench_index(project_root: str) -> dict:
    """Run indexing benchmark and return timing data.

    Uses :class:`ParallelParser` (ProcessPoolExecutor) for multi-core
    throughput.  Each run creates a fresh temporary database to isolate
    I/O from parsing performance.
    """
    root = Path(project_root).resolve()
    registry = LanguageRegistry()
    files = _collect_files(str(root), registry)

    if not files:
        return {
            "file_count": 0, "symbol_count": 0, "edge_count": 0,
            "elapsed_seconds": 0.0, "files_per_second": 0.0,
        }

    tmp_dir = tempfile.mkdtemp(prefix="memorygraph_bench_")
    tmp_memory_dir = Path(tmp_dir) / ".memorygraph"
    tmp_memory_dir.mkdir()

    try:
        mgr = StorageManager(str(tmp_dir))
        mgr.initialize()

        total_symbols = 0
        total_edges = 0

        start = time.perf_counter()
        count = 0

        parser = ParallelParser(registry)
        results = parser.parse_files(
            [Path(f) for f in files], resolve_symbols=True,
        )

        # Use bulk_upsert for efficient batch indexing — it collects FTS
        # rows across all files and rebuilds the FTS index exactly once.
        indexed = mgr.bulk_upsert(results)
        for _path_str, result in results.items():
            if not result.fatal_error:
                total_symbols += len(result.symbols)
                total_edges += len(result.edges)
        count = indexed

        elapsed = time.perf_counter() - start

        mgr.close()
        return {
            "file_count": count,
            "symbol_count": total_symbols,
            "edge_count": total_edges,
            "elapsed_seconds": round(elapsed, 3),
            "files_per_second": round(count / elapsed, 1) if elapsed > 0 else 0,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main():
    if len(sys.argv) < 2:
        print("Usage: python tests/bench/bench_index.py <project_root>")
        print("  e.g.  python tests/bench/bench_index.py /tmp/flask-test")
        sys.exit(1)

    project_root = sys.argv[1]
    print(f"Benchmarking index on: {project_root}")
    result = bench_index(project_root)
    print(f"  Files:         {result['file_count']}")
    print(f"  Symbols:       {result['symbol_count']}")
    print(f"  Edges:         {result['edge_count']}")
    print(f"  Elapsed:       {result['elapsed_seconds']}s")
    print(f"  Throughput:    {result['files_per_second']} files/s")


if __name__ == "__main__":
    main()
