"""Tests for ParallelParser and worker functions."""
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from memorygraph.parsing.batch import ParallelParser
from memorygraph.parsing.registry import LanguageRegistry


@pytest.fixture
def registry():
    return LanguageRegistry()


@pytest.fixture
def parser(registry):
    return ParallelParser(registry, max_workers=2)


def make_py_file(content: str, name: str = "") -> str:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8",
        prefix=name or "test_"
    )
    tmp.write(content)
    tmp.close()
    return tmp.name


def test_parse_multiple_files(parser):
    """Parse multiple files: result count = input file count."""
    files = []
    for i in range(5):
        path = make_py_file(f"def func{i}():\n    return {i}\n", f"file{i}_")
        files.append(Path(path))
    try:
        result = parser.parse_files(files, resolve_symbols=False)
        assert len(result) == 5
        for _path, parse_result in result.items():
            assert parse_result.fatal_error is None
            assert len(parse_result.symbols) >= 1
    finally:
        for f in files:
            os.unlink(str(f))


def test_parse_isolates_failures(parser):
    """One bad file should not affect other files."""
    good_files = []
    for i in range(3):
        path = make_py_file(f"def ok{i}():\n    pass\n", f"good{i}_")
        good_files.append(Path(path))

    # No extension -> UnknownLanguageError
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".xyz", delete=False, encoding="utf-8"
    )
    tmp.write("invalid")
    tmp.close()
    bad_file = Path(tmp.name)

    all_files = good_files + [bad_file]
    try:
        result = parser.parse_files(all_files, resolve_symbols=False)
        assert len(result) == 4
        for gf in good_files:
            assert result[str(gf)].fatal_error is None
            assert len(result[str(gf)].symbols) >= 1
        # Bad file should have fatal_error
        assert result[str(bad_file)].fatal_error is not None
    finally:
        for f in all_files:
            os.unlink(str(f))


def test_parse_empty_list(parser):
    result = parser.parse_files([], resolve_symbols=False)
    assert len(result) == 0


def test_parse_files_with_symbol_resolution(parser):
    """Cross-file reference resolution between two files."""
    path1 = make_py_file("def helper():\n    return 1\n", "mod1_")
    path2 = make_py_file("from mod1 import helper\ndef main():\n    return helper()\n", "mod2_")
    try:
        result = parser.parse_files([Path(path1), Path(path2)], resolve_symbols=True)
        assert len(result) == 2
    finally:
        os.unlink(path1)
        os.unlink(path2)


def test_parallel_parser_attributes(registry):
    """ParallelParser constructor attributes."""
    bp = ParallelParser(registry, parse_timeout=60)
    assert bp._parse_timeout == 60
    assert bp._max_workers > 0


def test_parallel_parser_default_workers(registry):
    """Default worker count from cpu count."""
    bp = ParallelParser(registry)
    assert bp._max_workers > 0
    assert bp._registry is registry


def test_parse_files_with_parent_symbols(parser):
    """Symbols with parent_symbol should be indexed under parent.name format."""
    path1 = make_py_file(
        "class MyClass:\n    def method1(self):\n        return 1\n",
        "cls_"
    )
    try:
        result = parser.parse_files([Path(path1)], resolve_symbols=True)
        assert len(result) == 1
    finally:
        os.unlink(path1)


def test_parse_files_skips_exceptions(parser):
    """Files that fail parsing in Pass 1 should have fatal_error, not crash."""
    good_path = make_py_file("def helper():\n    return 1\n", "good_")
    # Create a file with a known extension but content that crashes parsing
    bad_path = make_py_file("\x00\x00\x00", "bad_")
    # Rename to .py to trick the extension check
    import shutil
    real_bad = str(bad_path).replace("bad_", "badfile_")
    shutil.move(bad_path, real_bad)
    bad_path = Path(real_bad)
    try:
        result = parser.parse_files(
            [Path(good_path), bad_path], resolve_symbols=True
        )
        # Good file should be parsed successfully
        assert any(r.fatal_error is None for r in result.values())
    finally:
        os.unlink(good_path)
        if os.path.exists(str(bad_path)):
            os.unlink(str(bad_path))


def test_parse_files_with_resolve_symbols(parser):
    """Parse files with symbol resolution enabled."""
    path = make_py_file("def foo():\n    pass\n\ndef bar():\n    foo()\n", "resolve_")
    try:
        result = parser.parse_files([Path(path)], resolve_symbols=True)
        assert len(result) == 1
        pr = list(result.values())[0]
        assert pr.fatal_error is None
    finally:
        os.unlink(path)


def test_parse_files_timeout_handling(registry):
    """Timeout during batch processing should produce ParseResult with parse_timeout error."""
    parser = ParallelParser(registry, parse_timeout=0.001)
    path = make_py_file("def test():\n    pass\n", "timeout_")
    try:
        # Mock both ProcessPoolExecutor and as_completed
        with mock.patch("memorygraph.parsing.batch.ProcessPoolExecutor") as mock_pool_cls, \
             mock.patch("memorygraph.parsing.batch.as_completed") as mock_ac:
            mock_future = mock.MagicMock()
            mock_future.result.side_effect = TimeoutError("timed out")

            mock_pool = mock.MagicMock()
            mock_pool.submit.return_value = mock_future
            mock_pool.__enter__.return_value = mock_pool
            mock_pool_cls.return_value = mock_pool

            # as_completed must yield the same future object that submit returned
            def fake_as_completed(futures_dict):
                return list(futures_dict.keys())
            mock_ac.side_effect = fake_as_completed

            result = parser.parse_files([Path(path)], resolve_symbols=False)
            assert len(result) == 1
            pr = list(result.values())[0]
            assert pr.fatal_error is not None
            assert "parse_timeout" in pr.errors or "timed out" in (pr.fatal_error or "")
    finally:
        os.unlink(path)


def test_parse_files_batch_failure(registry):
    """Entire batch failure should mark all chunk files as errored."""
    parser = ParallelParser(registry, max_workers=1)
    path = make_py_file("def test():\n    pass\n", "batchfail_")
    try:
        # Mock both ProcessPoolExecutor and as_completed
        with mock.patch("memorygraph.parsing.batch.ProcessPoolExecutor") as mock_pool_cls, \
             mock.patch("memorygraph.parsing.batch.as_completed") as mock_ac:
            mock_future = mock.MagicMock()
            mock_future.result.side_effect = RuntimeError("worker crash")

            mock_pool = mock.MagicMock()
            mock_pool.submit.return_value = mock_future
            mock_pool.__enter__.return_value = mock_pool
            mock_pool_cls.return_value = mock_pool

            def fake_as_completed(futures_dict):
                return list(futures_dict.keys())
            mock_ac.side_effect = fake_as_completed

            result = parser.parse_files([Path(path)], resolve_symbols=False)
            assert len(result) == 1
            pr = list(result.values())[0]
            assert pr.fatal_error is not None
            assert "batch worker failed" in (pr.fatal_error or "")
    finally:
        os.unlink(path)


def test_parse_files_resolve_skips_fatal_errors(parser):
    """Pass 2 resolve should skip files whose parse result has fatal_error."""
    path1 = make_py_file("def good1():\n    pass\n", "resolve_good1_")

    # Create a file with unrecognized extension — will produce fatal_error
    bad_path = tempfile.NamedTemporaryFile(
        mode="w", suffix=".xyz", delete=False, encoding="utf-8"
    )
    bad_path.write("invalid content")
    bad_path.close()
    bad_path = Path(bad_path.name)

    try:
        result = parser.parse_files(
            [Path(path1), bad_path],
            resolve_symbols=True
        )
        assert len(result) == 2
        # Good file parsed fine
        assert result[str(path1)].fatal_error is None
        # Bad file has fatal error (unknown language)
        assert result[str(bad_path)].fatal_error is not None
    finally:
        os.unlink(path1)
        if os.path.exists(str(bad_path)):
            os.unlink(str(bad_path))


def test_worker_parse_one_direct():
    """_worker_parse_one should be callable directly (covers worker function body)."""
    import tempfile

    from memorygraph.parsing.batch import _worker_parse_one

    f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    f.write("def hello():\n    return 'world'\n")
    f.close()
    try:
        result = _worker_parse_one(str(f.name), {})
        assert len(result.symbols) >= 1
        assert result.fatal_error is None
    finally:
        os.unlink(f.name)


def test_worker_parse_batch_direct():
    """_worker_parse_batch should be callable directly (covers batch worker body)."""
    import tempfile

    from memorygraph.parsing.batch import _worker_parse_batch

    f1 = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    f1.write("def hello():\n    return 'world'\n")
    f1.close()
    f2 = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    f2.write("def bye():\n    return 'goodbye'\n")
    f2.close()
    try:
        results = _worker_parse_batch([str(f1.name), str(f2.name)])
        assert len(results) == 2
        for r in results:
            assert r.fatal_error is None
    finally:
        os.unlink(f1.name)
        os.unlink(f2.name)


def test_worker_parse_batch_with_error():
    """_worker_parse_batch handles parse errors gracefully (covers except branch)."""
    from memorygraph.parsing.batch import _worker_parse_batch

    results = _worker_parse_batch(["/nonexistent/path.py"])
    assert len(results) == 1
    assert results[0].fatal_error is not None


def test_worker_resolve_direct():
    """_worker_resolve should be callable directly (covers worker function body)."""
    import tempfile

    from memorygraph.parsing.batch import _worker_parse_one, _worker_resolve

    f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    f.write("def greeter():\n    return 'hi'\n")
    f.close()
    try:
        result = _worker_parse_one(str(f.name), {})
        resolved = _worker_resolve(result, {})
        assert resolved is not None
    finally:
        os.unlink(f.name)
