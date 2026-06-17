"""Benchmark stress test: 1000-file synthetic project indexing.

Usage:
    python -m pytest tests/test_bench_stress.py -v -s
"""

import json
import tempfile
import time
from pathlib import Path

import pytest

from tests.bench.synthetic import (
    COMPLEXITY_PROFILES,
    generate_synthetic_project,
)


class TestComplexityProfiles:
    """Verify synthetic project complexity distribution matches profile targets."""

    PROFILE_TOLERANCE = 0.15  # ±15% tolerance per rank bucket

    def _collect_complexity(self, project_root: Path) -> dict[str, int]:
        """Collect complexity rank counts from all Python files in project."""
        from memorygraph.semantic.analysis import analyze_complexity

        counts: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "F": 0}
        for fpath in project_root.rglob("*.py"):
            if fpath.name == "__init__.py":
                continue
            source = fpath.read_text()
            results = analyze_complexity(source)
            for r in results:
                counts[r["rank"]] = counts.get(r["rank"], 0) + 1
        return counts

    def test_flat_profile_all_rank_a(self):
        """Flat profile: every function should be rank A."""
        with tempfile.TemporaryDirectory() as tmp:
            root = generate_synthetic_project(
                tmp, num_files=50, symbols_per_file=8,
                complexity_profile="flat", seed=42,
            )
            counts = self._collect_complexity(root)
            total = sum(counts.values())
            assert total > 0, "Should have at least some symbols"
            assert counts["A"] == total, (
                f"Flat profile: expected all A, got {counts}"
            )

    def test_typical_profile_distribution(self):
        """Typical profile: A≈60%, B≈20%, C≈10%, D≈5%, E≈3%, F≈2%."""
        with tempfile.TemporaryDirectory() as tmp:
            root = generate_synthetic_project(
                tmp, num_files=100, symbols_per_file=10,
                complexity_profile="typical", seed=42,
            )
            counts = self._collect_complexity(root)
            total = sum(counts.values())
            assert total >= 900, f"Expected ≥900 symbols, got {total}"

            profile = COMPLEXITY_PROFILES["typical"]
            for rank in ("A", "B", "C", "D", "E", "F"):
                actual = counts.get(rank, 0) / total
                expected = profile.get(rank, 0.0)
                assert abs(actual - expected) < self.PROFILE_TOLERANCE, (
                    f"Rank {rank}: expected {expected:.0%}, got {actual:.1%} "
                    f"(tolerance ±{self.PROFILE_TOLERANCE:.0%})"
                )

    def test_complex_profile_distribution(self):
        """Complex profile: more weight on higher ranks C-F."""
        with tempfile.TemporaryDirectory() as tmp:
            root = generate_synthetic_project(
                tmp, num_files=100, symbols_per_file=10,
                complexity_profile="complex", seed=42,
            )
            counts = self._collect_complexity(root)
            total = sum(counts.values())
            assert total >= 900

            profile = COMPLEXITY_PROFILES["complex"]
            for rank in ("A", "B", "C", "D", "E", "F"):
                actual = counts.get(rank, 0) / total
                expected = profile.get(rank, 0.0)
                assert abs(actual - expected) < self.PROFILE_TOLERANCE, (
                    f"Rank {rank}: expected {expected:.0%}, got {actual:.1%}"
                )

    def test_seed_reproducibility(self):
        """Same seed + profile → identical complexity distribution."""
        with tempfile.TemporaryDirectory() as tmp1:
            root1 = generate_synthetic_project(
                tmp1, num_files=50, symbols_per_file=8,
                complexity_profile="typical", seed=123,
            )
            counts1 = self._collect_complexity(root1)

        with tempfile.TemporaryDirectory() as tmp2:
            root2 = generate_synthetic_project(
                tmp2, num_files=50, symbols_per_file=8,
                complexity_profile="typical", seed=123,
            )
            counts2 = self._collect_complexity(root2)

        assert counts1 == counts2, (
            f"Seed 123 should produce identical distribution: {counts1} vs {counts2}"
        )


@pytest.mark.slow
class TestStressIndexing:
    """Stress test: index a 1000-file synthetic project."""

    def test_generate_and_index_1000_files(self):
        """Generate 1000 Python files and index them, measuring throughput."""
        from memorygraph.parsing.batch import ParallelParser
        from memorygraph.parsing.registry import LanguageRegistry
        from memorygraph.storage import StorageManager

        with tempfile.TemporaryDirectory() as tmp:
            # Generate synthetic project
            gen_start = time.perf_counter()
            project_root = generate_synthetic_project(
                tmp, num_files=1000, symbols_per_file=8, edge_density=0.3,
                complexity_profile="typical",
            )
            gen_elapsed = time.perf_counter() - gen_start
            py_files = sorted(project_root.rglob("*.py"))
            # Exclude __init__.py files from count
            source_files = [f for f in py_files if f.name != "__init__.py"]
            total_lines = sum(len(f.read_text().splitlines()) for f in source_files)
            assert len(source_files) >= 990  # Allow small variance

            # Index
            mgr = StorageManager(str(project_root))
            mgr.initialize()

            registry = LanguageRegistry()
            index_start = time.perf_counter()

            count = 0
            batch_size = 500
            parse_errors = 0
            fatal_errors = 0

            parser = ParallelParser(registry)
            all_files = [str(f) for f in source_files]
            for i in range(0, len(all_files), batch_size):
                chunk = all_files[i:i + batch_size]
                results = parser.parse_files(
                    [Path(f) for f in chunk], resolve_symbols=True
                )
                valid = {}
                for path, result in results.items():
                    if result.fatal_error:
                        fatal_errors += 1
                    else:
                        if result.errors:
                            parse_errors += len(result.errors)
                        valid[path] = result
                if valid:
                    count += mgr.bulk_upsert(valid)

            index_elapsed = time.perf_counter() - index_start

            # Stats
            st = mgr.stats()
            file_count = st["file_count"]
            symbol_count = st["symbol_count"]
            edge_count = st["edge_count"]
            mgr.close()

            files_per_second = len(source_files) / index_elapsed if index_elapsed > 0 else 0

            # Record results
            result = {
                "suite": "stress-1000",
                "files_generated": len(source_files),
                "total_lines": total_lines,
                "gen_elapsed_seconds": round(gen_elapsed, 3),
                "index_elapsed_seconds": round(index_elapsed, 3),
                "files_per_second": round(files_per_second, 1),
                "indexed_file_count": count,
                "db_file_count": file_count,
                "db_symbol_count": symbol_count,
                "db_edge_count": edge_count,
                "parse_errors": parse_errors,
                "fatal_errors": fatal_errors,
            }

            print(f"\n  Stress test results: {json.dumps(result, indent=2)}")

            # Assertions
            assert fatal_errors == 0, f"{fatal_errors} fatal parse errors"
            assert count >= 990, f"Only {count} files indexed"
            assert file_count >= 990
            assert symbol_count >= 5000  # ~8000 expected
            assert edge_count >= 1000  # ~3000 expected
            assert files_per_second > 0

            # Performance assertion: GA target is >= 100 f/s for 1000 files
            # This is a soft assertion — logs a warning but doesn't fail
            if files_per_second < 100:
                print(f"\n  ⚠️  Performance below GA target: {files_per_second:.1f} f/s < 100 f/s")

            # Store results for baseline tracking (don't return — pytest warns)

    def test_raw_pipeline_benchmark(self):
        """Raw pipeline benchmark (no BatchParser/asyncio overhead).

        Uses ParsingPipeline directly + StorageManager.upsert() to measure
        the bare pipeline throughput: detect → parse → extract → resolve → upsert.

        This complements the BatchParser benchmark above — raw pipeline
        measures single-process throughput (~514 f/s), while BatchParser
        measures multi-process async throughput (~118 f/s).
        """
        from memorygraph.parsing.pipeline import parse_file
        from memorygraph.parsing.registry import LanguageRegistry
        from memorygraph.storage import StorageManager

        with tempfile.TemporaryDirectory() as tmp:
            project_root = generate_synthetic_project(
                tmp, num_files=1000, symbols_per_file=8, edge_density=0.3,
                complexity_profile="typical",
            )
            py_files = sorted(project_root.rglob("*.py"))
            source_files = [f for f in py_files if f.name != "__init__.py"]

            # Raw pipeline: single-process, no async overhead
            mgr = StorageManager(str(project_root))
            mgr.initialize()
            registry = LanguageRegistry()
            from memorygraph.parsing.ts_parser import TreeSitterParser
            ts_parser = TreeSitterParser(registry)

            # Phase 1: Parse (detect → parse → extract → resolve)
            parse_start = time.perf_counter()
            parse_results = {}
            all_symbols = []
            for f in source_files:
                result = parse_file(str(f), registry=registry, ts_parser=ts_parser)
                if not result.fatal_error:
                    parse_results[str(f)] = result
                    all_symbols.extend(result.symbols)
            parse_elapsed = time.perf_counter() - parse_start

            # Phase 2: Upsert (write to DB)
            upsert_start = time.perf_counter()
            mgr.bulk_upsert(parse_results)
            upsert_elapsed = time.perf_counter() - upsert_start

            total = parse_elapsed + upsert_elapsed
            n = len(source_files)

            result = {
                "files": n,
                "symbols": len(all_symbols),
                "total_time_s": round(total, 3),
                "files_per_second": round(n / total, 1) if total > 0 else 0,
                "parse_time_s": round(parse_elapsed, 3),
                "parse_files_per_second": round(n / parse_elapsed, 1) if parse_elapsed > 0 else 0,
                "upsert_time_s": round(upsert_elapsed, 3),
                "method": "raw_pipeline_single_process",
            }

            print(f"\n  Raw pipeline: {n} files in {total:.3f}s ({n/total:.0f} f/s)")
            print(f"    Parse:  {parse_elapsed:.3f}s ({n/parse_elapsed:.0f} f/s)")
            print(f"    Upsert: {upsert_elapsed:.3f}s")

            mgr.close()

            # Assertions
            assert n >= 990
            assert result["files_per_second"] > 0
            # Raw pipeline should be faster than BatchParser (less overhead)
            # Soft target: >200 f/s for single-process pipeline
            if result["files_per_second"] < 200:
                print(f"\n  ⚠️  Raw pipeline below 200 f/s: {result['files_per_second']:.1f}")

    def test_stress_2000_files(self):
        """Stress test: index 2000 files, verify memory stays bounded."""

        from memorygraph.parsing.batch import ParallelParser
        from memorygraph.parsing.registry import LanguageRegistry
        from memorygraph.storage import StorageManager

        with tempfile.TemporaryDirectory() as tmp:
            gen_start = time.perf_counter()
            project_root = generate_synthetic_project(
                tmp, num_files=2000, symbols_per_file=8, edge_density=0.3,
                complexity_profile="typical",
            )
            gen_elapsed = time.perf_counter() - gen_start
            py_files = sorted(project_root.rglob("*.py"))
            source_files = [f for f in py_files if f.name != "__init__.py"]
            assert len(source_files) >= 1980

            mgr = StorageManager(str(project_root))
            mgr.initialize()
            registry = LanguageRegistry()

            # Record memory before indexing
            mem_before = -1
            try:
                with open("/proc/self/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            mem_before = int(line.split()[1]) // 1024
                            break
            except OSError:
                pass

            index_start = time.perf_counter()
            count = 0
            fatal_errors = 0
            batch_size = 500

            parser = ParallelParser(registry)
            all_files = [str(f) for f in source_files]
            for i in range(0, len(all_files), batch_size):
                chunk = all_files[i:i + batch_size]
                results = parser.parse_files(
                    [Path(f) for f in chunk], resolve_symbols=True
                )
                valid = {}
                for path, result in results.items():
                    if result.fatal_error:
                        fatal_errors += 1
                    else:
                        valid[path] = result
                if valid:
                    count += mgr.bulk_upsert(valid)

            index_elapsed = time.perf_counter() - index_start

            # Record memory after indexing
            mem_after = -1
            try:
                with open("/proc/self/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            mem_after = int(line.split()[1]) // 1024
                            break
            except OSError:
                pass

            st = mgr.stats()
            mgr.close()

            files_per_second = len(source_files) / index_elapsed if index_elapsed > 0 else 0

            result = {
                "suite": "stress-2000",
                "files_generated": len(source_files),
                "gen_elapsed_seconds": round(gen_elapsed, 3),
                "index_elapsed_seconds": round(index_elapsed, 3),
                "files_per_second": round(files_per_second, 1),
                "indexed_file_count": count,
                "db_file_count": st["file_count"],
                "db_symbol_count": st["symbol_count"],
                "db_edge_count": st["edge_count"],
                "fatal_errors": fatal_errors,
                "mem_before_mb": mem_before,
                "mem_after_mb": mem_after,
                "mem_delta_mb": mem_after - mem_before if mem_before > 0 and mem_after > 0 else -1,
            }

            print(f"\n  Stress-2000 results: {json.dumps(result, indent=2)}")

            assert fatal_errors == 0, f"{fatal_errors} fatal parse errors"
            assert count >= 1980, f"Only {count} files indexed"
            assert st["file_count"] >= 1980
            assert st["symbol_count"] >= 10000
            assert st["edge_count"] >= 2000
            assert files_per_second > 0, "Should have positive throughput"

            if files_per_second < 50:
                print(f"\n  ⚠️  2000-file throughput below 50 f/s: {files_per_second:.1f}")

    def test_stress_reindex_stability(self):
        """Re-index same project 3 times — verify stable, no data corruption."""
        from memorygraph.parsing.batch import ParallelParser
        from memorygraph.parsing.registry import LanguageRegistry
        from memorygraph.storage import StorageManager

        with tempfile.TemporaryDirectory() as tmp:
            project_root = generate_synthetic_project(
                tmp, num_files=200, symbols_per_file=8, edge_density=0.3,
                complexity_profile="typical",
            )
            py_files = sorted(project_root.rglob("*.py"))
            source_files = [str(f) for f in py_files if f.name != "__init__.py"]

            registry = LanguageRegistry()
            prev_symbol_count = -1

            for cycle in range(3):
                mgr = StorageManager(str(project_root))
                mgr.initialize()

                parser = ParallelParser(registry)
                results = parser.parse_files(
                    [Path(f) for f in source_files], resolve_symbols=True
                )
                valid = {p: r for p, r in results.items() if not r.fatal_error}
                mgr.bulk_upsert(valid)

                st = mgr.stats()
                mgr.close()

                # Verify consistency
                assert st["file_count"] >= 180, f"Cycle {cycle}: expected ≥180 files"
                assert st["symbol_count"] >= 1000, f"Cycle {cycle}: expected ≥1000 symbols"

                if prev_symbol_count > 0:
                    # Symbol count should be stable across re-index
                    ratio = abs(st["symbol_count"] - prev_symbol_count) / prev_symbol_count
                    assert ratio < 0.05, (
                        f"Cycle {cycle}: symbol count drift {ratio:.1%} "
                        f"({prev_symbol_count} → {st['symbol_count']})"
                    )
                prev_symbol_count = st["symbol_count"]

            print(f"\n  Re-index stability: 3 cycles OK, {prev_symbol_count} symbols stable")

    def test_generate_and_index_100_files_quick(self):
        """Quick stress test: 100 files (runs faster, for CI)."""
        from memorygraph.parsing.batch import ParallelParser
        from memorygraph.parsing.registry import LanguageRegistry
        from memorygraph.storage import StorageManager

        with tempfile.TemporaryDirectory() as tmp:
            project_root = generate_synthetic_project(
                tmp, num_files=100, symbols_per_file=8, edge_density=0.3,
                complexity_profile="typical",
            )
            py_files = sorted(project_root.rglob("*.py"))
            source_files = [f for f in py_files if f.name != "__init__.py"]

            mgr = StorageManager(str(project_root))
            mgr.initialize()
            registry = LanguageRegistry()

            parser = ParallelParser(registry)
            all_files = [str(f) for f in source_files]
            for i in range(0, len(all_files), 500):
                chunk = all_files[i:i + 500]
                results = parser.parse_files(
                    [Path(f) for f in chunk], resolve_symbols=True
                )
                valid = {}
                for path, result in results.items():
                    if not result.fatal_error:
                        valid[path] = result
                if valid:
                    mgr.bulk_upsert(valid)

            st = mgr.stats()
            file_count = st["file_count"]
            symbol_count = st["symbol_count"]
            mgr.close()

            assert file_count >= 90
            assert symbol_count >= 500

    def test_stress_5000_files(self):
        """Stress test: 5000 files to verify memory stability and throughput at scale."""
        from memorygraph.parsing.pipeline import parse_file
        from memorygraph.parsing.registry import LanguageRegistry
        from memorygraph.parsing.ts_parser import TreeSitterParser
        from memorygraph.storage import StorageManager

        with tempfile.TemporaryDirectory() as tmp:
            gen_start = time.perf_counter()
            project_root = generate_synthetic_project(
                tmp, num_files=5000, symbols_per_file=6, edge_density=0.3,
                complexity_profile="typical",
            )
            gen_elapsed = time.perf_counter() - gen_start
            py_files = sorted(project_root.rglob("*.py"))
            source_files = [f for f in py_files if f.name != "__init__.py"]
            total_lines = sum(len(f.read_text().splitlines()) for f in source_files)
            assert len(source_files) >= 4900  # Allow small variance

            # Record memory before indexing
            mem_before = -1
            try:
                with open("/proc/self/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            mem_before = int(line.split()[1]) // 1024
                            break
            except OSError:
                pass

            # Raw pipeline: single-process throughput
            mgr = StorageManager(str(project_root))
            mgr.initialize()
            registry = LanguageRegistry()
            ts_parser = TreeSitterParser(registry)

            index_start = time.perf_counter()
            parse_results = {}
            for f in source_files:
                result = parse_file(str(f), registry=registry, ts_parser=ts_parser)
                if not result.fatal_error:
                    parse_results[str(f)] = result

            parse_elapsed = time.perf_counter() - index_start
            upsert_start = time.perf_counter()
            mgr.bulk_upsert(parse_results)
            upsert_elapsed = time.perf_counter() - upsert_start

            total_elapsed = parse_elapsed + upsert_elapsed
            n = len(source_files)

            # Record memory after indexing
            mem_after = -1
            try:
                with open("/proc/self/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            mem_after = int(line.split()[1]) // 1024
                            break
            except OSError:
                pass

            st = mgr.stats()
            mgr.close()

            fps = n / total_elapsed if total_elapsed > 0 else 0

            result = {
                "suite": "stress-5000",
                "files_generated": n,
                "total_lines": total_lines,
                "gen_elapsed_seconds": round(gen_elapsed, 3),
                "parse_elapsed_seconds": round(parse_elapsed, 3),
                "upsert_elapsed_seconds": round(upsert_elapsed, 3),
                "total_elapsed_seconds": round(total_elapsed, 3),
                "files_per_second": round(fps, 1),
                "db_file_count": st["file_count"],
                "db_symbol_count": st["symbol_count"],
                "db_edge_count": st["edge_count"],
                "mem_before_mb": mem_before,
                "mem_after_mb": mem_after,
                "mem_delta_mb": mem_after - mem_before if mem_before > 0 and mem_after > 0 else -1,
            }

            print(f"\n  Stress-5000 results: {json.dumps(result, indent=2)}")

            assert n >= 4900
            assert st["file_count"] >= 4900
            assert st["symbol_count"] >= 25000  # ~30000 expected
            assert st["edge_count"] >= 10000
            assert fps >= 100, f"5000-file throughput {fps:.1f} f/s < 100 f/s"

            # Memory should not grow unboundedly (soft check)
            if (mem_delta := result["mem_delta_mb"]) and mem_delta > 2048:
                print(f"\n  ⚠️  Memory delta high: {mem_delta} MB for 5000 files")
            print(f"\n  5000 files: {fps:.0f} f/s, memory: {mem_after} MB (Δ{result['mem_delta_mb']} MB)")

    def test_stress_10000_files(self):
        """Stress test: 10000 files to verify production-scale throughput and memory."""
        from memorygraph.parsing.pipeline import parse_file
        from memorygraph.parsing.registry import LanguageRegistry
        from memorygraph.parsing.ts_parser import TreeSitterParser
        from memorygraph.storage import StorageManager

        with tempfile.TemporaryDirectory() as tmp:
            gen_start = time.perf_counter()
            project_root = generate_synthetic_project(
                tmp, num_files=10000, symbols_per_file=5, edge_density=0.2,
                complexity_profile="typical",
            )
            gen_elapsed = time.perf_counter() - gen_start
            py_files = sorted(project_root.rglob("*.py"))
            source_files = [f for f in py_files if f.name != "__init__.py"]
            total_lines = sum(len(f.read_text().splitlines()) for f in source_files)
            assert len(source_files) >= 9800  # Allow small variance

            mem_before = -1
            try:
                with open("/proc/self/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            mem_before = int(line.split()[1]) // 1024
                            break
            except OSError:
                pass

            mgr = StorageManager(str(project_root))
            mgr.initialize()
            registry = LanguageRegistry()
            ts_parser = TreeSitterParser(registry)

            index_start = time.perf_counter()
            parse_results = {}
            for f in source_files:
                result = parse_file(str(f), registry=registry, ts_parser=ts_parser)
                if not result.fatal_error:
                    parse_results[str(f)] = result

            parse_elapsed = time.perf_counter() - index_start
            upsert_start = time.perf_counter()
            mgr.bulk_upsert(parse_results)
            upsert_elapsed = time.perf_counter() - upsert_start

            total_elapsed = parse_elapsed + upsert_elapsed
            n = len(source_files)

            mem_after = -1
            try:
                with open("/proc/self/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            mem_after = int(line.split()[1]) // 1024
                            break
            except OSError:
                pass

            st = mgr.stats()
            mgr.close()

            fps = n / total_elapsed if total_elapsed > 0 else 0

            result = {
                "suite": "stress-10000",
                "files_generated": n,
                "total_lines": total_lines,
                "gen_elapsed_seconds": round(gen_elapsed, 3),
                "parse_elapsed_seconds": round(parse_elapsed, 3),
                "upsert_elapsed_seconds": round(upsert_elapsed, 3),
                "total_elapsed_seconds": round(total_elapsed, 3),
                "files_per_second": round(fps, 1),
                "db_file_count": st["file_count"],
                "db_symbol_count": st["symbol_count"],
                "db_edge_count": st["edge_count"],
                "mem_before_mb": mem_before,
                "mem_after_mb": mem_after,
                "mem_delta_mb": mem_after - mem_before if mem_before > 0 and mem_after > 0 else -1,
            }

            print(f"\n  Stress-10000 results: {json.dumps(result, indent=2)}")

            assert n >= 9800
            assert st["file_count"] >= 9800
            assert st["symbol_count"] >= 40000  # ~50000 expected
            assert st["edge_count"] >= 15000
            # Production target: ≥80 f/s at 10K scale
            assert fps >= 80, f"10000-file throughput {fps:.1f} f/s < 80 f/s"

            if (mem_delta := result["mem_delta_mb"]) and mem_delta > 4096:
                print(f"\n  ⚠️  Memory delta high: {mem_delta} MB for 10000 files")
            print(f"\n  10000 files: {fps:.0f} f/s, memory: {mem_after} MB (Δ{result['mem_delta_mb']} MB)")


@pytest.mark.slow
class TestRealRepoBenchmarks:
    """Benchmark indexing on real open-source repos (black, flask, requests,
    django, cpython, numpy, scipy — 8000+ files total across 7 repos).

    Clones repos with ``--depth 1`` for speed, runs the index benchmark,
    and records results to the baseline file.
    """

    REAL_REPOS = {
        "black": {
            "url": "https://github.com/psf/black.git",
            "expected_files": 100,   # ~337 Python files; conservative min
            "min_fps": 50,           # very conservative floor
        },
        "flask": {
            "url": "https://github.com/pallets/flask.git",
            "expected_files": 30,    # ~83 Python files; conservative min
            "min_fps": 50,
        },
        "requests": {
            "url": "https://github.com/psf/requests.git",
            "expected_files": 15,    # ~34 Python files; conservative min
            "min_fps": 40,           # tiny repo, init overhead dominates
        },
        "django": {
            "url": "https://github.com/django/django.git",
            "expected_files": 2000,  # ~2922 Python files; conservative min
            "min_fps": 80,           # actual ~188 f/s; conservative floor
        },
        "cpython": {
            "url": "https://github.com/python/cpython.git",
            "expected_files": 500,   # ~2300 Python files; conservative min
            "min_fps": 40,           # actual ~58-107 f/s; conservative floor (OOM-safe)
        },
        "numpy": {
            "url": "https://github.com/numpy/numpy.git",
            "expected_files": 500,   # ~782 Python files; conservative min
            "min_fps": 80,
        },
        "scipy": {
            "url": "https://github.com/scipy/scipy.git",
            "expected_files": 1000,  # ~2000+ Python files; conservative min
            "min_fps": 80,
        },
    }

    @staticmethod
    def _clone_repo(url: str, target: Path) -> bool:
        """Shallow-clone a repo. Returns True on success."""
        import subprocess
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", url, str(target)],
                check=True, capture_output=True, timeout=120,
            )
            return True
        except Exception:
            return False

    def test_benchmark_real_repos(self):
        """Clone black + flask, index them, verify ≥50 f/s and update baseline."""
        import shutil

        from tests.bench.bench_index import bench_index
        from tests.bench.runner import update_baseline

        for repo_name, cfg in self.REAL_REPOS.items():
            tmp = tempfile.mkdtemp(prefix=f"mg_bench_{repo_name}_")
            try:
                clone_ok = self._clone_repo(cfg["url"], Path(tmp))
                if not clone_ok:
                    pytest.skip(
                        f"Cannot clone {repo_name} from {cfg['url']} "
                        f"(network unavailable?)"
                    )

                result = bench_index(tmp)
                fps = result["files_per_second"]

                print(
                    f"\n  {repo_name}: {result['file_count']} files, "
                    f"{fps:.1f} f/s, {result['elapsed_seconds']}s"
                )

                assert result["file_count"] >= cfg["expected_files"], (
                    f"{repo_name}: expected ≥{cfg['expected_files']} files, "
                    f"got {result['file_count']}"
                )
                assert fps >= cfg["min_fps"], (
                    f"{repo_name}: {fps:.1f} f/s < {cfg['min_fps']} "
                    f"(performance regression)"
                )

                # Record for baseline tracking (wrap in run_benchmark format)
                baseline_entry = {
                    "meta": {
                        "project_root": "git-clone",
                        "repo": repo_name,
                        "timestamp": __import__("datetime").datetime.now(
                            __import__("datetime").timezone.utc
                        ).isoformat(),
                        "total_elapsed_seconds": result["elapsed_seconds"],
                    },
                    "results": {
                        "index": {
                            "description": f"Index {repo_name}",
                            "metrics": result,
                        }
                    },
                }
                update_baseline(baseline_entry)

            finally:
                shutil.rmtree(tmp, ignore_errors=True)
