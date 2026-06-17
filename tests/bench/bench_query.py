"""Query performance benchmarks.

Usage:
    python tests/bench/bench_query.py /tmp/flask-test
"""
import sys
import time

from memorygraph.storage import StorageManager


def bench_queries(project_root: str, iterations: int = 100) -> dict:
    """Run query benchmarks."""
    mgr = StorageManager(project_root)
    mgr.initialize()

    # Warm up
    mgr.search("app", limit=10)

    # Bench search
    search_times = []
    for _ in range(iterations):
        start = time.perf_counter()
        mgr.search("app", limit=10)
        search_times.append((time.perf_counter() - start) * 1000)

    # Bench callers
    caller_times = []
    for _ in range(iterations):
        start = time.perf_counter()
        mgr.get_callers("app", depth=1)
        caller_times.append((time.perf_counter() - start) * 1000)

    # Bench callees
    callee_times = []
    for _ in range(iterations):
        start = time.perf_counter()
        mgr.get_callees("app", depth=1)
        callee_times.append((time.perf_counter() - start) * 1000)

    mgr.close()

    sorted_search = sorted(search_times)
    sorted_callers = sorted(caller_times)
    sorted_callees = sorted(callee_times)

    return {
        "search_p50_ms": round(sorted_search[len(sorted_search) // 2], 2),
        "search_p99_ms": round(sorted_search[int(len(sorted_search) * 0.99)], 2),
        "callers_p50_ms": round(sorted_callers[len(sorted_callers) // 2], 2),
        "callers_p99_ms": round(sorted_callers[int(len(sorted_callers) * 0.99)], 2),
        "callees_p50_ms": round(sorted_callees[len(sorted_callees) // 2], 2),
        "callees_p99_ms": round(sorted_callees[int(len(sorted_callees) * 0.99)], 2),
        "iterations": iterations,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python tests/bench/bench_query.py <project_root>")
        sys.exit(1)

    project_root = sys.argv[1]
    print(f"Benchmarking queries on: {project_root}")
    result = bench_queries(project_root)
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
