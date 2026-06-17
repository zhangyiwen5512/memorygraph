"""批量并行解析器——asyncio + ProcessPoolExecutor（多进程绕过 GIL）。"""
from __future__ import annotations

import contextlib
import logging
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from memorygraph.parsing.ir import FileInfo, ParseResult, Span
from memorygraph.parsing.registry import LanguageRegistry

logger = logging.getLogger(__name__)

# 默认单文件解析超时（秒）— 可通过 memorygraph.toml [memorygraph.parse_timeout] 覆盖
DEFAULT_PARSE_TIMEOUT = 30  # configurable via memorygraph.toml


def _add_to_symbol_index(
    path_str: str, result: ParseResult, symbol_index: dict[str, Span],
) -> None:
    """Add every symbol in *result* to the cross-file symbol index.

    Both ``BatchParser`` and ``ParallelParser`` use the same indexing logic.
    Extracted here to keep them DRY.
    """
    try:
        rel = str(Path(path_str).resolve().relative_to(Path.cwd()))
    except (ValueError, OSError):
        rel = path_str
    for sym in result.symbols:
        unscoped = sym.name
        scoped = f"{rel}::{sym.name}"
        if sym.parent_symbol:
            unscoped = f"{sym.parent_symbol}.{sym.name}"
            scoped = f"{rel}::{sym.parent_symbol}.{sym.name}"
        # setdefault: single dict lookup instead of two (in+assign)
        symbol_index.setdefault(scoped, sym.span)
        symbol_index.setdefault(unscoped, sym.span)


def _worker_parse_one(path: str, symbol_index: dict | None = None) -> ParseResult:
    """Worker 函数（模块级，用于 pickle 跨进程传递）。
    每个 worker 进程独立初始化自己的 LanguageRegistry 和 TreeSitterParser。
    """
    from memorygraph.parsing.pipeline import parse_file
    from memorygraph.parsing.registry import LanguageRegistry
    from memorygraph.parsing.ts_parser import TreeSitterParser

    registry = LanguageRegistry()
    ts_parser = TreeSitterParser(registry)
    return parse_file(path, registry, symbol_index, ts_parser)


def _worker_parse_batch(paths: list[str]) -> list[ParseResult]:
    """Worker：批量解析文件列表（单次 grammar 加载 + 预读 I/O）。

    每个 worker 进程只初始化一次 LanguageRegistry 和 TreeSitterParser，
    然后预读所有文件字节，最后解析。预读批量 I/O 减少 open/read 系统调用
    开销（~15% 提升），TreeSitterParser 复用避免每个文件重复创建
    Language(grammar) + Parser 对象。
    """
    from memorygraph.parsing.pipeline import parse_file
    from memorygraph.parsing.registry import LanguageRegistry
    from memorygraph.parsing.ts_parser import TreeSitterParser, read_file_bytes

    registry = LanguageRegistry()
    ts_parser = TreeSitterParser(registry)

    # Phase 1: Pre-read all source files in batch (amortize I/O overhead)
    sources: dict[str, bytes | None] = {}
    _read_errors: dict[str, str] = {}
    for path in paths:
        try:
            sources[path] = read_file_bytes(path)
        except Exception as e:
            sources[path] = None
            _read_errors[path] = str(e)

    # Phase 2: Parse from pre-read bytes
    results: list[ParseResult] = []
    for path in paths:
        source_bytes = sources.get(path)
        if source_bytes is None:
            error_msg = _read_errors.get(path, f"Cannot read file: {path}")
            results.append(ParseResult(
                file=FileInfo(path=path, language="unknown", content_hash=""),
                fatal_error=error_msg,
            ))
        else:
            try:
                results.append(
                    parse_file(path, registry, None, ts_parser, source_bytes=source_bytes)
                )
            except Exception as e:  # pragma: no cover — unexpected parse error fallback
                results.append(ParseResult(
                    file=FileInfo(path=path, language="unknown", content_hash=""),
                    fatal_error=str(e),
                ))
    return results


def _worker_resolve(result: ParseResult, symbol_index: dict) -> ParseResult:
    """Worker 函数：跨文件引用解析。"""
    from memorygraph.parsing.resolver import ReferenceResolver
    resolver = ReferenceResolver()
    return resolver.resolve(result, symbol_index)

class ParallelParser:
    """多进程并行解析器。

    ProcessPoolExecutor 绕过 Python GIL，实现真正的多核并行。
    每个子进程调用 :func:`_worker_parse_one` 时创建独立的 parser 实例。
    """

    def __init__(
        self,
        registry: "LanguageRegistry",
        max_workers: int | None = None,
        parse_timeout: int = DEFAULT_PARSE_TIMEOUT,
    ):
        self._registry = registry
        self._max_workers = max_workers or min(os.cpu_count() or 4, 16)
        self._parse_timeout = parse_timeout

    def parse_files(
        self,
        file_paths: list[Path],
        resolve_symbols: bool = True,
    ) -> dict[str, "ParseResult"]:
        """并行解析多个文件（多进程绕过 GIL）。

        两遍流程：
        1. 第一遍：所有文件并行解析（无跨文件引用解析）
        2. 若 resolve_symbols=True：收集全局符号表 → 并行解析引用
        """
        results: dict[str, "ParseResult"] = {}
        if not file_paths:
            return results

        # Pre-warm grammar cache on the main thread so worker processes
        # benefit from cached grammar files on disk.
        _warmed_ext: set[str] = set()
        _warmed_name: set[str] = set()
        for fp in file_paths:
            ext = os.path.splitext(str(fp))[1].lower()
            if ext in _warmed_ext:
                continue
            _warmed_ext.add(ext)
            config = self._registry.detect(f"dummy{ext}")
            if config and config.name not in _warmed_name:
                try:
                    self._registry.load_grammar(config.name)
                    _warmed_name.add(config.name)
                except Exception:
                    logger.warning(
                        "Failed to warm grammar for %s (parse will proceed per-file)",
                        config.name, exc_info=True,
                    )

        # Single ProcessPoolExecutor for both passes (avoids double startup cost)
        n_workers = min(self._max_workers, len(file_paths))

        # Python 3.13+: use spawn to avoid fork+threads deadlock (gh-84559)
        mp_context = None
        if sys.version_info >= (3, 13):
            mp_context = multiprocessing.get_context("spawn")

        with ProcessPoolExecutor(max_workers=n_workers, mp_context=mp_context) as pool:
            # Pass 1: parse in batched chunks (one grammar load per worker)
            chunk_size = max(1, len(file_paths) // n_workers)
            chunks: list[list[str]] = []
            for i in range(0, len(file_paths), chunk_size):
                chunks.append([str(p) for p in file_paths[i:i + chunk_size]])

            batch_futures = {
                pool.submit(_worker_parse_batch, chunk): i
                for i, chunk in enumerate(chunks)
            }
            for future in as_completed(batch_futures):
                chunk_idx = batch_futures[future]
                try:
                    parsed = future.result(timeout=self._parse_timeout)
                except TimeoutError:
                    # Batch timed out — mark all files in chunk as errored
                    for p in chunks[chunk_idx]:
                        results[p] = ParseResult(
                            file=FileInfo(
                                path=p, language="unknown", content_hash="",
                            ),
                            errors=["parse_timeout"],
                            fatal_error=(
                                f"Batch parsing timed out "
                                f"after {self._parse_timeout}s"
                            ),
                        )
                    continue
                except Exception:
                    # Entire batch failed — mark all files in chunk as errored
                    for p in chunks[chunk_idx]:
                        results[p] = ParseResult(
                            file=FileInfo(
                                path=p, language="unknown", content_hash="",
                            ),
                            fatal_error="batch worker failed",
                        )
                    continue
                for path_str, result in zip(chunks[chunk_idx], parsed, strict=True):
                    results[path_str] = result

        # Pass 2: resolve cross-file references (inline, main thread).
        # Running inline avoids pickling large ParseResult + symbol_index
        # dicts across process boundaries. Resolve is lightweight (O(symbols)
        # dict lookups) and doesn't benefit from multi-process parallelism.
        if resolve_symbols:
            symbol_index: dict[str, Span] = {}
            for path_str, result in results.items():
                if result.fatal_error:
                    continue
                _add_to_symbol_index(path_str, result, symbol_index)

            if symbol_index:
                from memorygraph.parsing.resolver import ReferenceResolver
                resolver = ReferenceResolver()
                for path_str in results:
                    if not results[path_str].fatal_error:
                        with contextlib.suppress(Exception):
                            results[path_str] = resolver.resolve(
                                results[path_str], symbol_index
                            )

        return results
