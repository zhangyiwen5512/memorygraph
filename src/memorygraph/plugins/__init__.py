"""Plugin system for memorygraph.

Two plugin types:
  - LanguagePlugin:  provides extractor for a language
  - AnalyzerPlugin:  provides additional analysis (smells, complexity, etc.)

Third-party plugins register via pyproject.toml entry_points:
  [project.entry-points."memorygraph.plugins"]
  kotlin = "memorygraph_kotlin:KotlinPlugin"
"""
import importlib.metadata
import logging
from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ── Abstract Base Classes ──────────────────────────────────────────


class LanguagePlugin(ABC):
    """Abstract base for language extractor plugins.

    Implementations provide:
      - language name
      - file extensions
      - extract() method that produces IR from a tree-sitter parse tree
    """

    @property
    @abstractmethod
    def language(self) -> str:
        """Language identifier (e.g. 'python', 'kotlin')."""
        ...  # pragma: no cover

    @property
    @abstractmethod
    def extensions(self) -> list[str]:
        """File extensions for this language (e.g. ['.py', '.pyi'])."""
        ...  # pragma: no cover

    @abstractmethod
    def extract(self, file_path: str, tree, source_bytes: bytes,
                language: str):
        """Extract IR (symbols, edges) from a parsed tree.

        Returns:
            ParseResult
        """
        ...  # pragma: no cover


class AnalyzerPlugin(ABC):
    """Abstract base for semantic analyzer plugins.

    Implementations provide additional analysis beyond tree-sitter:
      - Code smell detection
      - Design pattern detection
      - Custom metrics
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique analyzer name."""
        ...  # pragma: no cover

    @abstractmethod
    def analyze(self, symbols: list, callers: dict, callees: dict,
                source: str) -> dict:
        """Analyze symbols and return findings.

        Returns:
            dict with analysis results (smells, metrics, patterns, etc.)
        """
        ...  # pragma: no cover


# ── Plugin Registry ────────────────────────────────────────────────


def discover_plugins() -> dict[str, list]:
    """Discover installed plugins via entry_points.

    Returns:
        {'language': [...], 'analyzer': [...]}
    """
    plugins: dict[str, list] = {"language": [], "analyzer": []}
    try:
        eps = importlib.metadata.entry_points(
            group="memorygraph.plugins"
        )
    except TypeError:
        # Python < 3.12 compatibility
        eps = importlib.metadata.entry_points().get("memorygraph.plugins", [])  # type: ignore[arg-type]

    for ep in eps:
        try:
            cls = ep.load()
            obj = cls()
            if isinstance(obj, LanguagePlugin):
                plugins["language"].append(obj)
            elif isinstance(obj, AnalyzerPlugin):
                plugins["analyzer"].append(obj)
        except Exception:
            logger.warning(
                "Failed to load plugin %s", ep.name, exc_info=True
            )
    return plugins


# ── Built-in Language Registry ─────────────────────────────────────

def builtin_languages() -> list[dict]:
    """Return list of built-in languages (migrated from extractor registry).

    These are the languages supported out of the box without plugins.
    """
    return [
        {"name": "python", "extensions": [".py", ".pyi"]},
        {"name": "typescript", "extensions": [".ts", ".tsx"]},
        {"name": "javascript", "extensions": [".js", ".jsx", ".mjs"]},
        {"name": "go", "extensions": [".go"]},
        {"name": "rust", "extensions": [".rs"]},
        {"name": "java", "extensions": [".java"]},
        {"name": "csharp", "extensions": [".cs"]},
    ]
