"""语言检测器——文件扩展名 → LanguageConfig。"""
import os

from memorygraph.parsing.registry import LanguageConfig, LanguageRegistry


class UnknownLanguageError(Exception):
    """文件扩展名未被任何已注册语言识别。"""
    def __init__(self, file_path: str):
        _, ext = os.path.splitext(file_path)
        self.file_path = file_path
        self.extension = ext
        msg = (
            f"Cannot detect language for '{file_path}': "
            f"extension '{ext or '<none>'}' is not registered."
        )
        super().__init__(msg)


class LanguageDetector:
    """根据文件路径检测编程语言。纯扩展名匹配，零配置。"""

    def __init__(self, registry: LanguageRegistry):
        self._registry = registry

    def detect(self, file_path: str) -> LanguageConfig:
        config = self._registry.detect(file_path)
        if config is None:
            raise UnknownLanguageError(file_path)
        return config
