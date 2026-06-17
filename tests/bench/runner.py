"""Unified benchmark runner with parameterization and JSON reporting.

Usage:
    python -m tests.bench.runner --help
    python -m tests.bench.runner --suite all /tmp/flask-test
    python -m tests.bench.runner --suite index --iterations 3 /tmp/flask-test
    python -m tests.bench.runner --suite query --iterations 200 /tmp/flask-test
    python -m tests.bench.runner --suite export /tmp/flask-test
    python -m tests.bench.runner --suite all --output bench-results.json /tmp/flask-test
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bench_index import bench_index
from .bench_query import bench_queries
from .bench_visualize import bench_export

BENCHMARK_SUITES = {
    "index": ("Indexing throughput", bench_index),
    "query": ("Query latency (P50/P99)", bench_queries),
    "export": ("Export serialization", bench_export),
}


def run_benchmark(
    project_root: str,
    suite: str = "all",
    iterations: int = 100,
    batch_size: int = 50,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Run one or all benchmark suites and return structured results."""
    if not Path(project_root).exists():
        raise FileNotFoundError(f"Project root not found: {project_root}")

    suites_to_run: dict[str, tuple[str, callable]]
    if suite == "all":
        suites_to_run = BENCHMARK_SUITES
    elif suite in BENCHMARK_SUITES:
        suites_to_run = {suite: BENCHMARK_SUITES[suite]}
    else:
        raise ValueError(
            f"Unknown suite '{suite}'. Choices: all, {', '.join(BENCHMARK_SUITES)}"
        )

    results: dict[str, Any] = {
        "meta": {
            "project_root": str(Path(project_root).resolve()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "suite": suite,
        },
        "results": {},
    }

    overall_start = time.perf_counter()

    for name, (description, bench_fn) in suites_to_run.items():
        print(f"\n{'='*60}")
        print(f"  {description}")
        print(f"{'='*60}")

        kwargs = {}
        if name == "index":
            kwargs["project_root"] = project_root
        elif name == "query":
            kwargs = {"project_root": project_root, "iterations": iterations}
        elif name == "export":
            kwargs["project_root"] = project_root

        suite_start = time.perf_counter()
        suite_result = bench_fn(**kwargs)
        suite_elapsed = time.perf_counter() - suite_start

        results["results"][name] = {
            "description": description,
            "elapsed_seconds": round(suite_elapsed, 3),
            "metrics": suite_result,
        }

        # Print results
        for k, v in suite_result.items():
            if k != "iterations":
                print(f"  {k}: {v}")

    results["meta"]["total_elapsed_seconds"] = round(
        time.perf_counter() - overall_start, 3
    )

    if output_file:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(results, indent=2, default=str))
        print(f"\nResults saved to: {output_path}")

    return results


def update_baseline(results: dict[str, Any], baseline_file: str = "docs/benchmark-baseline.json") -> None:
    """Append or update benchmark results in the baseline tracking file."""
    baseline_path = Path(baseline_file)
    baseline_path.parent.mkdir(parents=True, exist_ok=True)

    baseline_data: list[dict[str, Any]] = []
    if baseline_path.exists():
        try:
            raw = json.loads(baseline_path.read_text())
            # Accept both list-of-entries and legacy dict-with-history format
            if isinstance(raw, list):
                baseline_data = raw
            elif isinstance(raw, dict):
                # Migrate legacy single-dict format to list
                baseline_data = [raw]
            else:
                baseline_data = []
        except (json.JSONDecodeError, ValueError):
            baseline_data = []

    baseline_data.append(results)
    baseline_path.write_text(json.dumps(baseline_data, indent=2, default=str))
    print(f"Baseline updated: {baseline_path} ({len(baseline_data)} entries)")


def main():
    parser = argparse.ArgumentParser(
        description="memorygraph benchmark suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tests.bench.runner --suite all /tmp/flask-test
  python -m tests.bench.runner --suite query --iterations 200 /tmp/flask-test
  python -m tests.bench.runner --suite all --output results.json --baseline /tmp/flask-test
        """,
    )
    parser.add_argument("project_root", help="Path to project to benchmark")
    parser.add_argument(
        "--suite", "-s",
        choices=["all", "index", "query", "export"],
        default="all",
        help="Benchmark suite to run (default: all)",
    )
    parser.add_argument(
        "--iterations", "-n",
        type=int,
        default=100,
        help="Number of iterations for query benchmarks (default: 100)",
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=50,
        help="Batch size for indexing benchmark (default: 50)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Save JSON results to file",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        default=False,
        help="Update baseline tracking file after run",
    )

    args = parser.parse_args()

    try:
        results = run_benchmark(
            project_root=args.project_root,
            suite=args.suite,
            iterations=args.iterations,
            batch_size=args.batch_size,
            output_file=args.output,
        )

        if args.baseline:
            update_baseline(results)

        # Print summary
        metrics = results.get("results", {})
        print(f"\n{'='*60}")
        print("  Summary")
        print(f"{'='*60}")
        print(f"  Total elapsed: {results['meta']['total_elapsed_seconds']}s")
        for name, data in metrics.items():
            m = data.get("metrics", {})
            if "files_per_second" in m:
                print(f"  {name}: {m['files_per_second']} files/s")
            if "search_p50_ms" in m:
                print(f"  {name}: search P50={m['search_p50_ms']}ms P99={m['search_p99_ms']}ms")

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
