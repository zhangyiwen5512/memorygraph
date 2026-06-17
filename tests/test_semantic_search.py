"""Tests for semantic search with real embeddings (requires sentence-transformers)."""
import os

import pytest


# HuggingFace Hub doesn't support SOCKS proxy — remove proxy for these tests
@pytest.fixture(autouse=True)
def clean_proxy():
    """Remove SOCKS proxy for HuggingFace compatibility."""
    saved = {}
    for var in ["ALL_PROXY", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                "http_proxy", "https_proxy", "no_proxy"]:
        saved[var] = os.environ.pop(var, None)
    yield
    for var, val in saved.items():
        if val is not None:
            os.environ[var] = val

# Check if sentence-transformers and model are available (importable + loadable)
try:
    from memorygraph.semantic.embeddings import EmbeddingGenerator
    gen = EmbeddingGenerator()
    if gen.is_available:
        gen._load_model()  # Verify model files are actually cached
    HAS_EMBEDDINGS = gen.is_available and gen._model is not None
except Exception:
    HAS_EMBEDDINGS = False


@pytest.mark.skipif(not HAS_EMBEDDINGS, reason="sentence-transformers not available")
class TestRealEmbeddings:
    """Tests using the real all-MiniLM-L6-v2 model."""

    def test_generate_returns_vector(self):
        gen = EmbeddingGenerator()
        vec = gen.generate("login", "def login(user, password):", "auth")
        assert vec is not None
        assert len(vec) == 384  # all-MiniLM-L6-v2 dimension

    def test_cosine_similarity_same_is_high(self):
        gen = EmbeddingGenerator()
        v1 = gen.generate("", "authenticate user login")
        v2 = gen.generate("", "verify user credentials")
        sim = gen.cosine_similarity(v1, v2)
        # Similar meanings should have high similarity
        assert sim > 0.3

    def test_cosine_similarity_different_is_low(self):
        gen = EmbeddingGenerator()
        v1 = gen.generate("", "authenticate user login")
        v2 = gen.generate("", "render HTML template page")
        sim = gen.cosine_similarity(v1, v2)
        # Different meanings should have lower similarity
        assert sim < 0.8  # Not strictly negative but lower than auth-related

    def test_search_ranks_auth_higher_than_render(self):
        gen = EmbeddingGenerator()
        syms = [
            {"name": "login", "signature": "def login(u, p):"},
            {"name": "render", "signature": "def render(tpl):"},
            {"name": "auth", "signature": "def auth(token):"},
            {"name": "parse_file", "signature": "def parse_file(path):"},
        ]
        embeddings = [gen.generate(s["name"], s.get("signature", ""))
                       for s in syms]
        stored = [{"name": s["name"], "embedding": e}
                   for s, e in zip(syms, embeddings, strict=False) if e is not None]

        query_vec = gen.generate("", "user authentication login")
        results = gen.search(query_vec, stored, top_k=4)

        # login/auth should have higher similarity than render
        top_names = [r["name"] for r in results]
        sims = {r["name"]: r["_similarity"] for r in results}

        assert sims.get("login", -1) > sims.get("render", -999), \
            f"login should rank above render, got: {top_names} with {sims}"
        assert sims.get("auth", -1) > sims.get("render", -999), \
            f"auth should rank above render, got: {top_names} with {sims}"

    def test_hybrid_search_combines(self):
        gen = EmbeddingGenerator()
        query_vec = gen.generate("", "helper function")
        fts = [{"name": "helper", "qualified_name": "helper", "_score": 10}]
        vec_results = [{"name": "main", "qualified_name": "main", "_similarity": 0.5}]
        combined = gen.hybrid_search(query_vec, fts, vec_results)
        assert len(combined) == 2
        # Both results should have _combined score
        assert "_combined" in combined[0]
        assert "_combined" in combined[1]

    def test_generate_multiple(self):
        gen = EmbeddingGenerator()
        syms = [
            {"name": "f1", "signature": "def f1():"},
            {"name": "f2", "signature": "def f2(x):"},
            {"name": "f3", "signature": "def f3():"},
        ]
        embeddings = [gen.generate(s["name"], s.get("signature", ""))
                       for s in syms]
        assert len(embeddings) == 3
        for e in embeddings:
            assert e is not None
            assert len(e) == 384
