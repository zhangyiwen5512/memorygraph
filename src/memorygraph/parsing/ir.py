"""统一中间表示（IR）数据类型。

解析层的唯一输出。下游不接触 tree-sitter 原始类型。
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SymbolKind(Enum):
    """图谱节点类型。"""
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    INTERFACE = "interface"
    TYPE_ALIAS = "type"
    VARIABLE = "variable"


class EdgeKind(Enum):
    """图谱边类型。"""
    CALLS = "calls"
    IMPORTS = "imports"
    EXTENDS = "extends"
    IMPLEMENTS = "implements"
    TYPE_REFERENCES = "type_refs"


@dataclass
class Span:
    """行列级源码位置。行号和列号从 0 开始，遵循 tree-sitter 习惯。"""
    file: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int


@dataclass
class Symbol:
    """图谱节点——一个代码符号。"""
    name: str
    kind: SymbolKind
    span: Span
    parent_symbol: str | None = None
    signature: str | None = None
    is_partial: bool = False


@dataclass
class Edge:
    """图谱边——两个符号之间的关系。"""
    source: str
    target: str
    kind: EdgeKind
    source_span: Span
    target_span: Span | None = None


@dataclass
class FileInfo:
    """被解析文件的元信息。"""
    path: str
    language: str
    content_hash: str


@dataclass
class ParseResult:
    """单个文件的完整解析产物。"""
    file: FileInfo
    symbols: list[Symbol] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fatal_error: str | None = None


def to_json_dict(obj: Any) -> Any:
    """将 IR 数据类转换为 JSON 可序列化的 dict，处理 Enum 字段。

    >>> d = to_json_dict(SymbolKind.FUNCTION)
    >>> d == "function"
    True
    """
    if isinstance(obj, Enum):
        return obj.value
    if dataclasses.is_dataclass(obj):
        result = {}
        for f in dataclasses.fields(obj):
            value = getattr(obj, f.name)
            result[f.name] = to_json_dict(value)
        return result
    if isinstance(obj, list):
        return [to_json_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {k: to_json_dict(v) for k, v in obj.items()}
    return obj
