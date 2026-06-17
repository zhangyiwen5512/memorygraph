"""跨文件引用解析器——填充 Edge.target_span。"""
from memorygraph.parsing.ir import ParseResult, Span


class ReferenceResolver:
    """解析跨文件引用，将 Edge.target 匹配到已索引文件的符号表。"""

    def resolve(self, result: ParseResult, symbol_index: dict[str, Span]) -> ParseResult:
        """为 result 中每条 Edge 查找目标符号定义位置。

        Args:
            result: 解析结果
            symbol_index: {name → Span} 或 {parent.name → Span}
        """
        for edge in result.edges:
            if edge.target_span is not None:
                continue
            target_span = symbol_index.get(edge.target)
            if target_span:
                edge.target_span = target_span
        return result
