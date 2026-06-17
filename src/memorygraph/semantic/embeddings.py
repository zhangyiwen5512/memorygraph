"""Semantic embeddings for code symbols using sentence-transformers.

Generates vector embeddings from symbol name + signature + context,
stores them in the database, and supports cosine similarity search.

Model: all-MiniLM-L6-v2 (384-dim, ~80MB)
Lazy loading: model is loaded on first call and cached in memory.
"""

from __future__ import annotations

import numpy as np

_SENTENCE_TRANSFORMERS_AVAILABLE = False


def _check_sentence_transformers() -> bool:
    global _SENTENCE_TRANSFORMERS_AVAILABLE
    if _SENTENCE_TRANSFORMERS_AVAILABLE:
        return True
    try:
        import sentence_transformers  # noqa: F401
        _SENTENCE_TRANSFORMERS_AVAILABLE = True
        return True
    except ImportError:
        return False


class EmbeddingGenerator:
    """Generates and manages vector embeddings for code symbols.

    Uses sentence-transformers all-MiniLM-L6-v2 (384 dimensions).
    Model is loaded lazily on first call and cached.

    Usage:
        gen = EmbeddingGenerator()
        vec = gen.generate("login", "def login(user): ...", "auth module")
        results = gen.search(query_vec, stored_vectors, top_k=10)
    """

    MODEL_NAME = "all-MiniLM-L6-v2"

    def __init__(self):
        self._model = None
        self._available = _check_sentence_transformers()

    @property
    def is_available(self) -> bool:
        """Check if sentence-transformers is installed."""
        return self._available

    def _load_model(self):
        """Lazy-load the sentence-transformers model."""
        if self._model is not None:
            return
        if not self._available:
            raise RuntimeError(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(
            self.MODEL_NAME,
            local_files_only=True  # Use cached model, avoid network calls
        )

    def generate(self, name: str, signature: str = "",
                 context: str = "") -> np.ndarray | None:
        """Generate embedding vector for a symbol.

        Args:
            name: Symbol name
            signature: Function/method signature
            context: Surrounding context (docstring, comments, etc.)

        Returns:
            384-dim numpy array, or None if model not available
        """
        if not self._available:
            return None

        self._load_model()
        assert self._model is not None

        # Build descriptive text from available fields
        parts = [name]
        if signature:
            parts.append(signature)
        if context:
            parts.append(context)
        text = " ".join(parts)

        embedding = self._model.encode(text, convert_to_numpy=True)
        return embedding.astype(np.float32)

    def cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    def search(self, query_vec: np.ndarray, stored: list[dict],
               top_k: int = 10,
               field: str = "embedding") -> list[dict]:
        """Search stored embeddings by cosine similarity.

        Args:
            query_vec: Query embedding vector (384-dim)
            stored: List of dicts with 'embedding' field (numpy array)
            top_k: Number of results to return
            field: Key name for the embedding in stored dicts

        Returns:
            Sorted list of dicts with '_similarity' score added
        """
        results = []
        for item in stored:
            vec = item.get(field)
            if vec is None:
                continue
            sim = self.cosine_similarity(query_vec, vec)
            item_copy = {k: v for k, v in item.items() if k != field}
            item_copy["_similarity"] = sim
            results.append(item_copy)

        results.sort(key=lambda x: x["_similarity"], reverse=True)
        return results[:top_k]

    def hybrid_search(self, query_vec: np.ndarray,
                      fts_results: list[dict],
                      vector_results: list[dict],
                      fts_weight: float = 0.4,
                      vector_weight: float = 0.6) -> list[dict]:
        """Combine FTS and vector search results with weighted scoring.

        Args:
            query_vec: Query embedding vector
            fts_results: Results from FTS search (with '_score' field)
            vector_results: Results from vector search (with '_similarity' field)
            fts_weight: Weight for FTS scores (default 0.4)
            vector_weight: Weight for vector scores (default 0.6)

        Returns:
            Combined and re-ranked results
        """
        combined: dict[str, dict] = {}

        # Normalize FTS scores
        max_fts = max((r.get("_score", 0) for r in fts_results), default=1)
        for r in fts_results:
            key = r.get("qualified_name", r.get("name", ""))
            norm_score = r.get("_score", 0) / max_fts if max_fts > 0 else 0
            combined[key] = {**r, "_combined": norm_score * fts_weight}

        # Normalize vector scores
        max_vec = max((r.get("_similarity", 0) for r in vector_results), default=1)
        for r in vector_results:
            key = r.get("qualified_name", r.get("name", ""))
            norm_sim = r.get("_similarity", 0) / max_vec if max_vec > 0 else 0
            if key in combined:
                combined[key]["_combined"] += norm_sim * vector_weight
                combined[key]["_similarity"] = r.get("_similarity", 0)
            else:
                combined[key] = {**r, "_combined": norm_sim * vector_weight}

        sorted_results = sorted(
            combined.values(),
            key=lambda x: x.get("_combined", 0),
            reverse=True
        )
        return sorted_results
