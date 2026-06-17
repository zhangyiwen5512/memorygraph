"""Semantic layer — human-curated annotations on top of the static knowledge graph.

Two-layer architecture:
  - tree-sitter AST → static graph (deterministic, token-level)
  - semantic layer → human understanding (advisory, append-only JSON)
"""

from memorygraph.semantic.models import (
    Annotation,
    Insight,
    SemanticDocument,
    Unknown,
    file_path_hash,
)
from memorygraph.semantic.store import SemanticStore

__all__ = [
    "Annotation",
    "Unknown",
    "Insight",
    "SemanticDocument",
    "file_path_hash",
    "SemanticStore",
]
