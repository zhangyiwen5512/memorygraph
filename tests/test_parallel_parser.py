"""Tests for ParallelParser."""
import tempfile
from pathlib import Path

from memorygraph.parsing.batch import ParallelParser, _worker_parse_one
from memorygraph.parsing.registry import LanguageRegistry


class TestParallelParser:
    def test_parse_empty_list(self):
        registry = LanguageRegistry()
        parser = ParallelParser(registry, max_workers=2)
        results = parser.parse_files([])
        assert results == {}

    def test_parse_single_python_file(self):
        registry = LanguageRegistry()
        parser = ParallelParser(registry, max_workers=1)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("def hello():\n    return 'world'\n")
            tmp_path = Path(f.name)
        try:
            results = parser.parse_files([tmp_path])
            assert len(results) == 1
            result = results[str(tmp_path)]
            assert not result.fatal_error
            assert any(s.name == "hello" for s in result.symbols)
        finally:
            tmp_path.unlink()

    def test_parse_multiple_files_parallel(self):
        registry = LanguageRegistry()
        parser = ParallelParser(registry, max_workers=4)
        tmp_files = []
        for i in range(5):
            f = tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            )
            f.write(f"def func_{i}():\n    return {i}\n")
            f.close()
            tmp_files.append(Path(f.name))
        try:
            results = parser.parse_files(tmp_files)
            assert len(results) == 5
            for p in tmp_files:
                assert str(p) in results
                assert not results[str(p)].fatal_error
        finally:
            for p in tmp_files:
                p.unlink()

    def test_parse_nonexistent_file(self):
        registry = LanguageRegistry()
        parser = ParallelParser(registry, max_workers=1)
        fake_path = Path("/nonexistent/path.py")
        results = parser.parse_files([fake_path])
        assert len(results) == 1
        assert results[str(fake_path)].fatal_error

    def test_resolve_symbols_false(self):
        registry = LanguageRegistry()
        parser = ParallelParser(registry, max_workers=1)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write("def foo():\n    pass\n")
            tmp_path = Path(f.name)
        try:
            results = parser.parse_files([tmp_path], resolve_symbols=False)
            assert len(results) == 1
            assert not results[str(tmp_path)].fatal_error
        finally:
            tmp_path.unlink()

    def test_parallel_correctness_matches_serial(self):
        """并行解析结果应与逐个串行解析一致。"""
        registry = LanguageRegistry()
        tmp_files = []
        for i in range(3):
            f = tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            )
            f.write(f"def helper{i}():\n    return {i}\n\n")
            f.write(f"def caller{i}():\n    helper{i}()\n")
            f.close()
            tmp_files.append(Path(f.name))
        try:
            parser = ParallelParser(registry, max_workers=3)
            results_parallel = parser.parse_files(tmp_files)
            results_serial = {}
            for p in tmp_files:
                results_serial[str(p)] = _worker_parse_one(str(p), None)
            for p in tmp_files:
                pr = results_parallel[str(p)]
                sr = results_serial[str(p)]
                assert len(pr.symbols) == len(sr.symbols), \
                    f"Mismatch for {p}"
                assert len(pr.edges) == len(sr.edges), \
                    f"Edges mismatch for {p}"
        finally:
            for p in tmp_files:
                p.unlink()


class TestParallelParserPerformance:
    """Performance benchmarks for ProcessPoolExecutor."""

    def test_benchmark_1000_files_ge_300_fps(self):
        """Synthetic 1000 files should parse at ≥300 f/s with ProcessPoolExecutor."""
        import shutil
        import time

        tmpdir = tempfile.mkdtemp()
        try:
            files = []
            for i in range(1000):
                fpath = Path(tmpdir) / f"mod_{i:04d}.py"
                fpath.write_text(
                    f"def func_{i}(x: int) -> int:\n"
                    f"    '''Module {i} utility function.'''\n"
                    f"    return x * {i} + {i % 100}\n\n"
                    f"class Class{i}:\n"
                    f"    def __init__(self):\n"
                    f"        self.val = {i}\n"
                    f"    def method(self, y):\n"
                    f"        return self.val + y\n"
                )
                files.append(fpath)

            registry = LanguageRegistry()
            parser = ParallelParser(registry)

            start = time.perf_counter()
            results = parser.parse_files(files, resolve_symbols=True)
            elapsed = time.perf_counter() - start

            success = sum(
                1 for r in results.values() if not r.fatal_error
            )
            rate = success / elapsed if elapsed > 0 else 0

            assert success == 1000, (
                f"Expected 1000 successful parses, got {success}"
            )
            assert rate >= 300, (
                f"Expected ≥300 f/s, got {rate:.1f} f/s "
                f"({success} files in {elapsed:.2f}s)"
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_resolve_failure_is_non_fatal(self, monkeypatch):
        """Pass 2 resolve exception should not crash parse_files (batch.py:298-299)."""
        import shutil as _shutil
        import tempfile as _tempfile
        from pathlib import Path as _Path

        tmpdir = _tempfile.mkdtemp()
        try:
            fpath = _Path(tmpdir) / "mod.py"
            fpath.write_text("def foo(): pass\n")

            registry = LanguageRegistry()
            parser = ParallelParser(registry)

            # First parse without resolve to get valid results with symbols
            results = parser.parse_files([fpath], resolve_symbols=False)
            assert not results[str(fpath)].fatal_error

            # Monkeypatch ReferenceResolver.resolve to always raise
            from memorygraph.parsing import resolver as _resolver
            _orig = _resolver.ReferenceResolver.resolve

            def _failing_resolve(self, result, symbol_index):
                raise RuntimeError("simulated resolve failure")

            monkeypatch.setattr(
                _resolver.ReferenceResolver, "resolve", _failing_resolve
            )

            # Should not raise — resolve failure is non-fatal
            results = parser.parse_files([fpath], resolve_symbols=True)
            assert not results[str(fpath)].fatal_error
        finally:
            _shutil.rmtree(tmpdir, ignore_errors=True)

    def test_grammar_prewarm_failure_non_fatal(self, monkeypatch):
        """Grammar pre-warming failure should not crash (batch.py:232-233)."""
        import shutil as _shutil
        import tempfile as _tempfile
        from pathlib import Path as _Path

        tmpdir = _tempfile.mkdtemp()
        try:
            fpath = _Path(tmpdir) / "mod.py"
            fpath.write_text("def foo(): pass\n")

            registry = LanguageRegistry()
            parser = ParallelParser(registry)

            # Monkeypatch load_grammar to always raise
            _orig = registry.load_grammar
            def _failing_load(name):
                raise RuntimeError("simulated grammar load failure")
            monkeypatch.setattr(registry, "load_grammar", _failing_load)

            # Should not crash — pre-warm failure is non-fatal
            results = parser.parse_files([fpath], resolve_symbols=False)
            assert not results[str(fpath)].fatal_error
        finally:
            _shutil.rmtree(tmpdir, ignore_errors=True)

    def test_batch_worker_failure_marks_chunk_as_errored(self, monkeypatch):
        """When future.result() raises, whole chunk gets fatal_error (batch.py:252-261)."""
        import shutil as _shutil
        import tempfile as _tempfile
        from concurrent.futures import Future
        from pathlib import Path as _Path
        from unittest import mock

        tmpdir = _tempfile.mkdtemp()
        try:
            fpath = _Path(tmpdir) / "mod.py"
            fpath.write_text("def foo(): pass\n")

            registry = LanguageRegistry()
            parser = ParallelParser(registry, max_workers=1)

            # A real Future that raises on .result() — as_completed needs
            # a proper Future with _condition etc.
            failing = Future()
            failing.set_exception(RuntimeError("simulated worker crash"))

            # Mock ProcessPoolExecutor so submit returns the failing future
            with mock.patch(
                "memorygraph.parsing.batch.ProcessPoolExecutor"
            ) as mock_pool_cls:
                mock_pool = mock.MagicMock()
                mock_pool_cls.return_value = mock_pool
                mock_pool.__enter__.return_value = mock_pool
                mock_pool.__exit__.return_value = None
                mock_pool.submit.return_value = failing

                results = parser.parse_files([fpath], resolve_symbols=False)

            assert str(fpath) in results
            assert results[str(fpath)].fatal_error == "batch worker failed"
        finally:
            _shutil.rmtree(tmpdir, ignore_errors=True)
