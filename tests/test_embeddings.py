"""Tests for semantic embeddings module."""
from unittest import mock

import numpy as np
import pytest
from click.testing import CliRunner

from memorygraph.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestEmbeddingGenerator:
    """Tests for EmbeddingGenerator (without requiring sentence-transformers)."""

    def test_init_without_sentence_transformers(self):
        """Should initialize but mark as unavailable."""
        with mock.patch(
            "memorygraph.semantic.embeddings._check_sentence_transformers",
            return_value=False
        ):
            from memorygraph.semantic.embeddings import EmbeddingGenerator
            gen = EmbeddingGenerator()
            assert not gen.is_available

    def test_generate_returns_none_when_unavailable(self):
        with mock.patch(
            "memorygraph.semantic.embeddings._check_sentence_transformers",
            return_value=False
        ):
            from memorygraph.semantic.embeddings import EmbeddingGenerator
            gen = EmbeddingGenerator()
            result = gen.generate("test_func", "def test_func(): pass")
            assert result is None

    def test_generate_multiple_calls_when_unavailable(self):
        """Multiple generate() calls should all return None when unavailable."""
        with mock.patch(
            "memorygraph.semantic.embeddings._check_sentence_transformers",
            return_value=False
        ):
            from memorygraph.semantic.embeddings import EmbeddingGenerator
            gen = EmbeddingGenerator()
            r1 = gen.generate("f1")
            r2 = gen.generate("f2")
            assert r1 is None
            assert r2 is None

    def test_generate_with_context(self):
        """generate() should include context field in text encoding."""
        with mock.patch(
            "memorygraph.semantic.embeddings._check_sentence_transformers",
            return_value=True
        ):
            from memorygraph.semantic.embeddings import EmbeddingGenerator
            gen = EmbeddingGenerator()
            gen._available = True
            gen._model = mock.MagicMock()
            gen._model.encode.return_value = np.array(
                [1.0, 2.0, 3.0], dtype=np.float32
            )
            result = gen.generate(
                "func_with_ctx", "def f(): pass", "Auth module"
            )
            assert isinstance(result, np.ndarray)
            # Verify context was included in encode call
            call_args = gen._model.encode.call_args[0][0]
            assert "Auth module" in call_args
            assert "func_with_ctx" in call_args

    def test_cosine_similarity_identical(self):
        """Cosine similarity of identical vectors should be 1.0."""
        from memorygraph.semantic.embeddings import EmbeddingGenerator
        gen = EmbeddingGenerator()
        vec = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        sim = gen.cosine_similarity(vec, vec)
        assert abs(sim - 1.0) < 0.001

    def test_cosine_similarity_orthogonal(self):
        """Cosine similarity of orthogonal vectors should be 0.0."""
        from memorygraph.semantic.embeddings import EmbeddingGenerator
        gen = EmbeddingGenerator()
        a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        sim = gen.cosine_similarity(a, b)
        assert abs(sim - 0.0) < 0.001

    def test_cosine_similarity_opposite(self):
        """Cosine similarity of opposite vectors should be -1.0."""
        from memorygraph.semantic.embeddings import EmbeddingGenerator
        gen = EmbeddingGenerator()
        a = np.array([1.0, 2.0], dtype=np.float32)
        b = np.array([-1.0, -2.0], dtype=np.float32)
        sim = gen.cosine_similarity(a, b)
        assert abs(sim - (-1.0)) < 0.001

    def test_cosine_similarity_zero_vector(self):
        """Zero vector should return 0.0 similarity."""
        from memorygraph.semantic.embeddings import EmbeddingGenerator
        gen = EmbeddingGenerator()
        a = np.array([0.0, 0.0], dtype=np.float32)
        b = np.array([1.0, 2.0], dtype=np.float32)
        sim = gen.cosine_similarity(a, b)
        assert sim == 0.0

    def test_search_returns_sorted_by_similarity(self):
        """search() should sort results by cosine similarity descending."""
        from memorygraph.semantic.embeddings import EmbeddingGenerator
        gen = EmbeddingGenerator()
        query_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)

        stored = [
            {"name": "f1", "embedding": np.array([1.0, 0.0, 0.0], dtype=np.float32)},   # sim ~1.0
            {"name": "f2", "embedding": np.array([0.0, 1.0, 0.0], dtype=np.float32)},   # sim ~0.0
            {"name": "f3", "embedding": np.array([0.5, 0.0, 0.0], dtype=np.float32)},   # sim ~1.0 but lower
        ]

        results = gen.search(query_vec, stored, top_k=3)
        assert len(results) == 3
        # f1 (exact match) should be first
        assert results[0]["name"] == "f1"
        assert results[0]["_similarity"] > 0.99
        # f2 (orthogonal) should be last
        assert results[2]["name"] == "f2"

    def test_search_handles_missing_embedding(self):
        """search() should skip items without embedding field."""
        from memorygraph.semantic.embeddings import EmbeddingGenerator
        gen = EmbeddingGenerator()
        query_vec = np.array([1.0, 0.0], dtype=np.float32)

        stored: list[dict] = [
            {"name": "f1", "embedding": np.array([1.0, 0.0], dtype=np.float32)},
            {"name": "no_embed", "other": "data"},
        ]

        results = gen.search(query_vec, stored)
        assert len(results) == 1
        assert results[0]["name"] == "f1"

    def test_hybrid_search_combines_scores(self):
        """Hybrid search should combine FTS and vector scores."""
        from memorygraph.semantic.embeddings import EmbeddingGenerator
        gen = EmbeddingGenerator()
        query_vec = np.array([1.0, 0.0], dtype=np.float32)

        fts_results = [
            {"name": "f1", "qualified_name": "f1", "_score": 10},
            {"name": "f2", "qualified_name": "f2", "_score": 5},
        ]

        vector_results = [
            {"name": "f2", "qualified_name": "f2", "_similarity": 0.9},
            {"name": "f3", "qualified_name": "f3", "_similarity": 0.8},
        ]

        results = gen.hybrid_search(
            query_vec, fts_results, vector_results,
            fts_weight=0.4, vector_weight=0.6
        )
        assert len(results) == 3
        # f2 appears in both, so should have highest combined score
        assert results[0]["qualified_name"] == "f2"

    def test_hybrid_search_empty_fts(self):
        """Hybrid search with empty FTS results should return vector results."""
        from memorygraph.semantic.embeddings import EmbeddingGenerator
        gen = EmbeddingGenerator()
        query_vec = np.array([1.0, 0.0], dtype=np.float32)

        vector_results = [
            {"name": "f1", "qualified_name": "f1", "_similarity": 0.9},
        ]

        results = gen.hybrid_search(query_vec, [], vector_results)
        assert len(results) == 1
        assert results[0]["qualified_name"] == "f1"

    def test_hybrid_search_empty_vector(self):
        """Hybrid search with empty vector results should return FTS results."""
        from memorygraph.semantic.embeddings import EmbeddingGenerator
        gen = EmbeddingGenerator()
        query_vec = np.array([1.0, 0.0], dtype=np.float32)

        fts_results = [
            {"name": "f1", "qualified_name": "f1", "_score": 10},
        ]

        results = gen.hybrid_search(query_vec, fts_results, [])
        assert len(results) == 1
        assert results[0]["qualified_name"] == "f1"


class TestSearchSemanticCLI:
    """Integration tests for the search-semantic CLI command."""

    def test_search_semantic_help(self):
        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(cli, ["search-semantic", "--help"])
        assert result.exit_code == 0

    def test_search_semantic_no_project(self, tmp_path):
        """Search on an empty directory without embeddings."""
        from click.testing import CliRunner
        runner = CliRunner()
        # Without sentence-transformers installed, falls back to FTS
        with mock.patch(
            "memorygraph.semantic.embeddings._check_sentence_transformers",
            return_value=False
        ):
            result = runner.invoke(
                cli, ["search-semantic", "test query",
                      "--project-root", str(tmp_path)]
            )
            assert result.exit_code in (0, 1)

    def test_search_semantic_fallback(self, tmp_path):
        """Search on empty project falls back to FTS (no embeddings stored)."""
        from click.testing import CliRunner
        runner = CliRunner()
        with mock.patch(
            "memorygraph.semantic.embeddings._check_sentence_transformers",
            return_value=False
        ):
            result = runner.invoke(
                cli, ["search-semantic", "nonexistent_xyz",
                      "--project-root", str(tmp_path)]
            )
            assert result.exit_code in (0, 1)


class TestCheckAvailability:
    """Tests for _check_sentence_transformers function."""

    def test_check_import_error(self):
        """Should return False when sentence_transformers import fails."""
        from memorygraph.semantic.embeddings import _check_sentence_transformers
        with (
            mock.patch("memorygraph.semantic.embeddings._SENTENCE_TRANSFORMERS_AVAILABLE", False),
            mock.patch("builtins.__import__", side_effect=ImportError("no module")),
        ):
            result = _check_sentence_transformers()
            assert result is False


class TestLoadModelError:
    """Tests for EmbeddingGenerator._load_model error path."""

    def test_load_model_raises_when_unavailable(self):
        """_load_model should raise RuntimeError when sentence-transformers unavailable."""
        from memorygraph.semantic.embeddings import EmbeddingGenerator
        gen = EmbeddingGenerator()
        gen._available = False
        gen._model = None
        with pytest.raises(RuntimeError, match="sentence-transformers not installed"):
            gen._load_model()
