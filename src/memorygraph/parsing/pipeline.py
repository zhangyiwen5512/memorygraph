"""解析管道——4 阶段串行：Detect → Parse → Extract → Resolve。"""
import hashlib
import threading

from memorygraph.parsing.detector import LanguageDetector
from memorygraph.parsing.extractor import (
    CSharpExtractor,
    GoExtractor,
    IRExtractor,
    JavaExtractor,
    JavaScriptExtractor,
    PythonExtractor,
    RustExtractor,
    TypeScriptExtractor,
)
from memorygraph.parsing.ir import FileInfo, ParseResult, Span
from memorygraph.parsing.registry import LanguageRegistry
from memorygraph.parsing.resolver import ReferenceResolver
from memorygraph.parsing.ts_parser import TreeSitterParser

_EXTRACTOR_MAP: dict[str, type[IRExtractor]] = {
    "python": PythonExtractor,
    "typescript": TypeScriptExtractor,
    "javascript": JavaScriptExtractor,
    "go": GoExtractor,
    "rust": RustExtractor,
    "java": JavaExtractor,
    "csharp": CSharpExtractor,
}

# Instance cache: extractor instances are stateless per call (all state
# comes from parameters), so reusing them avoids per-file allocations.
_EXTRACTOR_INSTANCES: dict[str, IRExtractor] = {}
_EXTRACTOR_LOCK = threading.Lock()


def parse_file(
    file_path: str,
    registry: LanguageRegistry | None = None,
    symbol_index: dict[str, Span] | None = None,
    ts_parser: TreeSitterParser | None = None,
    source_bytes: bytes | None = None,
) -> ParseResult:
    """解析单个文件的完整管道。

    Args:
        file_path: 文件绝对路径
        registry: 语言注册表（若为 None 则创建默认实例）
        symbol_index: 已索引符号表 {name → Span}，用于跨文件引用解析
        ts_parser: 可复用的 TreeSitterParser（用于批量解析，避免重复创建）
        source_bytes: 预读的源码字节。若提供，跳过文件 I/O（调用方负责读取）

    Returns:
        ParseResult
    """
    if registry is None:
        registry = LanguageRegistry()

    # 阶段 1: 检测语言
    detector = LanguageDetector(registry)
    config = detector.detect(file_path)

    # 阶段 2: tree-sitter 解析
    if ts_parser is None:
        ts_parser = TreeSitterParser(registry)
    if source_bytes is not None:
        tree, source_bytes = ts_parser.parse_bytes(source_bytes, config)
    else:
        tree, source_bytes = ts_parser.parse(file_path, config)

    # 阶段 3: 提取 IR（复用 extractor 实例，减少每文件分配）
    extractor_cls = _EXTRACTOR_MAP.get(config.name)
    if extractor_cls is None:
        return ParseResult(
            file=FileInfo(
                path=file_path, language=config.name,
                content_hash=hashlib.sha256(source_bytes).hexdigest()
            ),
            fatal_error=f"No extractor for language: {config.name}"
        )
    if config.name not in _EXTRACTOR_INSTANCES:
        with _EXTRACTOR_LOCK:
            if config.name not in _EXTRACTOR_INSTANCES:
                _EXTRACTOR_INSTANCES[config.name] = extractor_cls()
    extractor = _EXTRACTOR_INSTANCES[config.name]
    result = extractor.extract(file_path, tree, source_bytes, config.name)

    # 阶段 4: 跨文件引用解析
    if symbol_index:
        resolver = ReferenceResolver()
        result = resolver.resolve(result, symbol_index)

    return result
