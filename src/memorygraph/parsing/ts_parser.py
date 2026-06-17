"""Tree-sitter 解析器包装器——文件字节流 → tree-sitter Tree。"""
from tree_sitter import Language, Parser, Tree

from memorygraph.parsing.registry import LanguageConfig, LanguageRegistry


class ParseError(Exception):
    """致命解析错误——完全无法解析文件。"""
    pass


def read_file_bytes(file_path: str) -> bytes:
    """Read raw bytes from a source file. Raises ParseError on failure."""
    try:
        with open(file_path, "rb") as f:
            return f.read()
    except FileNotFoundError as err:
        raise ParseError(f"File not found: {file_path}") from err
    except OSError as e:
        raise ParseError(f"Cannot read file {file_path}: {e}") from e


class TreeSitterParser:
    """将源码文件解析为 tree-sitter 语法树。使用注册表懒加载语法库。"""

    def __init__(self, registry: LanguageRegistry):
        self._registry = registry
        self._parsers: dict[str, Parser] = {}

    def parse(self, file_path: str, language_config: LanguageConfig) -> tuple[Tree, bytes]:
        """解析文件，返回 (tree_sitter Tree, source_bytes)。"""
        source_bytes = read_file_bytes(file_path)
        return self.parse_bytes(source_bytes, language_config)

    def parse_bytes(
        self, source_bytes: bytes, language_config: LanguageConfig,
    ) -> tuple[Tree, bytes]:
        """从预读的字节解析，返回 (tree_sitter Tree, source_bytes)。

        用于调用方已提前读取文件内容（批量预读、内存文件等），
        避免重复的 open/read 系统调用。
        """
        try:
            parser = self._get_parser(language_config.name)
        except Exception as e:
            raise ParseError(
                f"Failed to load grammar for {language_config.name}: {e}"
            ) from e

        tree = parser.parse(source_bytes)
        return tree, source_bytes

    def _get_parser(self, language: str) -> Parser:
        if language not in self._parsers:
            grammar = self._registry.load_grammar(language)
            lang_obj = Language(grammar)
            parser = Parser(language=lang_obj)
            self._parsers[language] = parser
        return self._parsers[language]
