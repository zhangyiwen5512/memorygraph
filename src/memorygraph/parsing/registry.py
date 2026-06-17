"""语言注册表——扩展名检测 + 懒加载 tree-sitter 语法库。"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


@dataclass
class LanguageConfig:
    """定义一种语言的解析配置。"""
    name: str
    extensions: list[str]
    grammar_package: str
    grammar_lang_attr: str


_BUILTIN_LANGUAGES: list[LanguageConfig] = [
    LanguageConfig(
        name="typescript",
        extensions=[".ts", ".tsx", ".mts", ".cts"],
        grammar_package="tree-sitter-typescript",
        grammar_lang_attr="language_typescript",
    ),
    LanguageConfig(
        name="javascript",
        extensions=[".js", ".jsx", ".mjs", ".cjs"],
        grammar_package="tree-sitter-typescript",
        grammar_lang_attr="language_typescript",
    ),
    LanguageConfig(
        name="python",
        extensions=[".py", ".pyi", ".pyx"],
        grammar_package="tree-sitter-python",
        grammar_lang_attr="language",
    ),
    LanguageConfig(
        name="go",
        extensions=[".go"],
        grammar_package="tree-sitter-go",
        grammar_lang_attr="language",
    ),
    LanguageConfig(
        name="rust",
        extensions=[".rs"],
        grammar_package="tree-sitter-rust",
        grammar_lang_attr="language",
    ),
    LanguageConfig(
        name="java",
        extensions=[".java"],
        grammar_package="tree-sitter-java",
        grammar_lang_attr="language",
    ),
    LanguageConfig(
        name="csharp",
        extensions=[".cs"],
        grammar_package="tree-sitter-c-sharp",
        grammar_lang_attr="language",
    ),
]


class LanguageRegistry:
    """中心语言注册表。根据文件扩展名检测语言，懒加载语法库。"""

    # 类级别语法缓存：所有 Registry 实例共享同一份 tree-sitter 语法对象
    # 避免每个测试函数（function-scoped fixture）重新加载 .so 导致 RSS 飙升
    _loaded_grammars: dict[str, object] = {}

    def __init__(self):
        self._configs: dict[str, LanguageConfig] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        for config in _BUILTIN_LANGUAGES:
            self.register(config)

    def register(self, config: LanguageConfig) -> None:
        for ext in config.extensions:
            self._configs[ext.lower()] = config

    def detect(self, file_path: str) -> LanguageConfig | None:
        import os
        _, ext = os.path.splitext(file_path)
        return self._configs.get(ext.lower())

    def supported_extensions(self) -> list[str]:
        return sorted(self._configs.keys())

    def is_available(self, language: str) -> bool:
        config = self._configs_by_name().get(language)
        if config is None:
            return False
        try:
            self._load_module(config)
            return True
        except ImportError:
            return False

    def load_grammar(self, language: str) -> object:
        config = self._configs_by_name().get(language)
        if config is None:
            raise ValueError(f"Unknown language: {language}")
        if language in self._loaded_grammars:
            return self._loaded_grammars[language]
        try:
            module = self._load_module(config)
        except ImportError as err:
            if os.environ.get("MEMORYGRAPH_NO_AUTO_INSTALL"):
                raise ImportError(
                    f"Grammar {config.grammar_package} not installed and "
                    f"MEMORYGRAPH_NO_AUTO_INSTALL is set. "
                    f"Install it with: pip install {config.grammar_package}"
                ) from err
            self._install_grammar(config)
            module = self._load_module(config)
        # Try the configured attribute name first, then fallback to 'language'
        lang_fn = getattr(module, config.grammar_lang_attr, None)
        if lang_fn is None:
            lang_fn = getattr(module, "language", None)
        if lang_fn is None:
            raise AttributeError(
                f"Could not find language function in {config.grammar_package}"
            )
        grammar = lang_fn() if callable(lang_fn) else lang_fn
        self._loaded_grammars[language] = grammar
        return grammar

    def _load_module(self, config: LanguageConfig) -> Any:
        return importlib.import_module(
            config.grammar_package.replace("-", "_")
        )

    def _install_grammar(self, config: LanguageConfig) -> None:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            "Grammar %s not found. Attempting pip install (timeout=60s). "
            "Set MEMORYGRAPH_NO_AUTO_INSTALL=1 to disable.",
            config.grammar_package,
        )
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", config.grammar_package],
            timeout=60,
        )

    def _configs_by_name(self) -> dict[str, LanguageConfig]:
        result: dict[str, LanguageConfig] = {}
        for config in self._configs.values():
            if config.name not in result:
                result[config.name] = config
        return result
