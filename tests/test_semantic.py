"""Tests for the semantic layer."""
import json
from pathlib import Path

import pytest

from memorygraph.semantic.models import (
    Annotation,
    Insight,
    SemanticDocument,
    Unknown,
    file_path_hash,
)
from memorygraph.semantic.store import SemanticStore


class TestSemanticDocument:
    """Test SemanticDocument model."""

    def test_create_document(self):
        doc = SemanticDocument(
            file="src/app.py",
            source="manual",
            module_summary="Application entry point",
        )
        d = doc.to_dict()
        assert d["file"] == "src/app.py"
        assert d["module_summary"] == "Application entry point"
        assert d["source"] == "manual"
        assert d["ingested_at"] != ""

    def test_create_with_annotations(self):
        doc = SemanticDocument(
            file="src/utils.py",
            annotations=[
                Annotation(
                    symbol="helper",
                    kind="function",
                    summary="Helper utility",
                    design_intent="Pure function for reuse",
                )
            ],
        )
        d = doc.to_dict()
        assert len(d["annotations"]) == 1
        assert d["annotations"][0]["symbol"] == "helper"

    def test_create_with_unknowns(self):
        doc = SemanticDocument(
            file="src/mystery.py",
            unknowns=[
                Unknown(
                    symbol="obscure_func",
                    question="What does this do?",
                    context="Seen in auth flow",
                )
            ],
        )
        d = doc.to_dict()
        assert len(d["unknowns"]) == 1
        assert d["unknowns"][0]["question"] == "What does this do?"

    def test_create_with_insights(self):
        doc = SemanticDocument(
            file="src/design.py",
            insights=[
                Insight(
                    insight="Plugin architecture",
                    related_symbols=["Plugin", "Manager"],
                )
            ],
        )
        d = doc.to_dict()
        assert len(d["insights"]) == 1
        assert d["insights"][0]["insight"] == "Plugin architecture"

    def test_roundtrip_from_dict(self):
        doc = SemanticDocument(
            file="src/app.py",
            module_summary="Test module",
            annotations=[
                Annotation(symbol="foo", kind="function", summary="Does foo"),
            ],
        )
        d = doc.to_dict()
        doc2 = SemanticDocument.from_dict(d)
        assert doc2.file == doc.file
        assert doc2.module_summary == doc.module_summary
        assert len(doc2.annotations) == 1
        assert doc2.annotations[0].symbol == "foo"

    def test_merge_updates_module_summary(self):
        doc1 = SemanticDocument(
            file="src/app.py", module_summary="Old summary"
        )
        doc2 = SemanticDocument(
            file="src/app.py", module_summary="New summary"
        )
        doc1.merge_from(doc2)
        assert doc1.module_summary == "New summary"

    def test_merge_preserves_empty_summary(self):
        doc1 = SemanticDocument(
            file="src/app.py", module_summary="Has summary"
        )
        doc2 = SemanticDocument(
            file="src/app.py", module_summary=""
        )
        doc1.merge_from(doc2)
        assert doc1.module_summary == "Has summary"

    def test_merge_deduplicates_annotations(self):
        doc1 = SemanticDocument(
            file="src/app.py",
            annotations=[Annotation(symbol="foo", kind="function", summary="First")],
        )
        doc2 = SemanticDocument(
            file="src/app.py",
            annotations=[Annotation(symbol="foo", kind="function", summary="Second")],
        )
        doc1.merge_from(doc2)
        assert len(doc1.annotations) == 1
        assert doc1.annotations[0].summary == "Second"  # updated

    def test_merge_adds_new_annotations(self):
        doc1 = SemanticDocument(
            file="src/app.py",
            annotations=[Annotation(symbol="foo", kind="function", summary="Foo")],
        )
        doc2 = SemanticDocument(
            file="src/app.py",
            annotations=[Annotation(symbol="bar", kind="function", summary="Bar")],
        )
        doc1.merge_from(doc2)
        assert len(doc1.annotations) == 2

    def test_merge_append_insights(self):
        doc1 = SemanticDocument(
            file="src/app.py",
            insights=[Insight(insight="Insight 1")],
        )
        doc2 = SemanticDocument(
            file="src/app.py",
            insights=[Insight(insight="Insight 2")],
        )
        doc1.merge_from(doc2)
        assert len(doc1.insights) == 2

    def test_file_path_hash(self):
        h = file_path_hash("src/app.py")
        assert len(h) == 16
        # Same path gives same hash
        assert file_path_hash("src/app.py") == h
        # Different path gives different hash
        assert file_path_hash("src/other.py") != h


class TestSemanticStore:
    """Test SemanticStore CRUD operations."""

    @pytest.fixture
    def store(self, tmpdir):
        store = SemanticStore(str(tmpdir))
        store.ensure_dir()
        return store

    def test_ensure_dir(self, tmpdir):
        store = SemanticStore(str(tmpdir))
        store.ensure_dir()
        sem_dir = Path(tmpdir) / ".memorygraph" / "semantic"
        assert sem_dir.exists()

    def test_save_and_load(self, store):
        doc = SemanticDocument(
            file="src/app.py",
            module_summary="Main application entry",
            annotations=[
                Annotation(symbol="main", kind="function", summary="Entry point"),
            ],
        )
        store.save(doc)
        loaded = store.load("src/app.py")
        assert loaded is not None
        assert loaded.module_summary == "Main application entry"
        assert len(loaded.annotations) == 1

    def test_save_lock_timeout(self, store):
        """save() should log warning and return when lock can't be acquired."""
        from unittest import mock

        from memorygraph.semantic.models import SemanticDocument

        doc = SemanticDocument(
            file="src/locked.py",
            module_summary="Locked file",
        )
        with mock.patch("memorygraph.semantic.store.FileLock") as mock_lock_cls:
            mock_lock = mock.MagicMock()
            mock_lock.acquire.side_effect = TimeoutError("lock timeout")
            mock_lock_cls.return_value = mock_lock

            with mock.patch("logging.Logger.warning") as mock_warning:
                store.save(doc)
                mock_warning.assert_called_once()
                assert "Could not acquire lock" in mock_warning.call_args[0][0]

    def test_load_nonexistent(self, store):
        doc = store.load("nonexistent.py")
        assert doc is None

    def test_save_merges(self, store):
        doc1 = SemanticDocument(
            file="src/app.py",
            module_summary="First",
            annotations=[Annotation(symbol="a", kind="function", summary="A")],
        )
        store.save(doc1)

        doc2 = SemanticDocument(
            file="src/app.py",
            module_summary="Second",
            annotations=[Annotation(symbol="b", kind="function", summary="B")],
        )
        store.save(doc2)

        loaded = store.load("src/app.py")
        assert loaded.module_summary == "Second"
        assert len(loaded.annotations) == 2

    def test_add_annotation_via_save_roundtrip(self, store):
        """Adding an annotation via save() should persist across load()."""
        doc = SemanticDocument(
            file="src/app.py",
            annotations=[Annotation(symbol="foo", kind="function", summary="Foo")],
        )
        store.save(doc)

        loaded = store.load("src/app.py")
        assert loaded is not None
        assert len(loaded.annotations) == 1
        assert loaded.annotations[0].symbol == "foo"
        assert loaded.annotations[0].summary == "Foo"

    def test_add_annotation_multiple_same_symbol(self, store):
        """Adding two annotations with the same symbol: last write wins (merge_from behavior)."""
        store.save(SemanticDocument(
            file="src/app.py",
            annotations=[Annotation(symbol="foo", kind="function", summary="Version 1")],
        ))
        store.save(SemanticDocument(
            file="src/app.py",
            annotations=[Annotation(symbol="foo", kind="function", summary="Version 2")],
        ))
        loaded = store.load("src/app.py")
        assert loaded is not None
        assert len(loaded.annotations) == 1
        assert loaded.annotations[0].summary == "Version 2"

    def test_add_annotation_then_delete_roundtrip(self, store):
        """Add annotation, delete it, verify it's gone — no merge_from revert."""
        store.save(SemanticDocument(
            file="src/app.py",
            annotations=[
                Annotation(symbol="foo", kind="function", summary="Foo"),
                Annotation(symbol="bar", kind="function", summary="Bar"),
            ],
        ))
        assert store.delete_annotation("src/app.py", "foo", index=0) is True

        loaded = store.load("src/app.py")
        assert loaded is not None
        foo_anns = [a for a in loaded.annotations if a.symbol == "foo"]
        assert len(foo_anns) == 0, "delete_annotation should persist, not be reverted by merge_from"
        assert len(loaded.annotations) == 1
        assert loaded.annotations[0].symbol == "bar"

    def test_load_all(self, store):
        store.save(SemanticDocument(file="a.py", module_summary="A"))
        store.save(SemanticDocument(file="b.py", module_summary="B"))
        all_docs = store.load_all()
        assert len(all_docs) == 2

    def test_count_annotated_symbols(self, store):
        store.save(SemanticDocument(
            file="a.py",
            annotations=[
                Annotation(symbol="f1", kind="function", summary="F1"),
                Annotation(symbol="f2", kind="function", summary="F2"),
            ],
        ))
        store.save(SemanticDocument(
            file="b.py",
            annotations=[
                Annotation(symbol="f3", kind="function", summary="F3"),
                Annotation(symbol="f1", kind="function", summary="F1 again"),
            ],
        ))
        # f1 in 2 files = 2 annotations, f2 = 1, f3 = 1, total = 4
        count = store.count_annotated_symbols()
        assert count == 4

    def test_get_coverage(self, store):
        store.save(SemanticDocument(
            file="a.py",
            annotations=[
                Annotation(symbol="f1", kind="function", summary="F1"),
            ],
        ))
        # 1 annotated symbol out of 10 total, 1 documented file out of 5 total
        coverage = store.get_coverage(total_symbols=10, file_count=5)
        assert "20.0% files" in coverage    # 1/5 files
        assert "10.0% symbols" in coverage  # 1/10 symbols

    def test_get_coverage_module_summary_only(self, store):
        """module_summary alone should count toward file-level coverage."""
        store.save(SemanticDocument(
            file="b.py", module_summary="Important module"
        ))
        coverage = store.get_coverage(total_symbols=100, file_count=20)
        assert "5.0% files" in coverage     # 1/20 files documented
        assert "0.0% symbols" in coverage   # 0/100 symbols annotated

    def test_get_coverage_zero_symbols(self, store):
        coverage = store.get_coverage(total_symbols=0, file_count=0)
        assert "0% files" in coverage
        assert "0% symbols" in coverage

    def test_remove(self, store):
        store.save(SemanticDocument(file="a.py", module_summary="A"))
        assert store.load("a.py") is not None
        store.remove("a.py")
        assert store.load("a.py") is None

    def test_remove_nonexistent_file(self, store):
        """Removing a file that doesn't exist should not raise."""
        store.remove("nonexistent.py")  # Should not raise

    def test_remove_persists(self, store):
        """After remove(), load() should return None."""
        store.save(SemanticDocument(file="temp.py", module_summary="Temp"))
        assert store.load("temp.py") is not None
        store.remove("temp.py")
        assert store.load("temp.py") is None

    def test_remove_repeated(self, store):
        """Calling remove() twice on the same file should not raise."""
        store.save(SemanticDocument(file="once.py"))
        store.remove("once.py")
        store.remove("once.py")  # Should not raise

    def test_list_documented_files(self, store):
        store.save(SemanticDocument(file="a.py", module_summary="A"))
        store.save(SemanticDocument(file="b.py"))  # no summary, no annotations
        files = store.list_documented_files()
        assert "a.py" in files

    def test_list_documented_files_with_annotations(self, store):
        store.save(SemanticDocument(
            file="c.py",
            annotations=[Annotation(symbol="f", kind="function", summary="F")],
        ))
        files = store.list_documented_files()
        assert "c.py" in files

    def test_load_corrupt_json_returns_none(self, store):
        """load() should return None for corrupt JSON files."""
        from memorygraph.semantic.models import file_path_hash
        hashed = file_path_hash("bad")
        bad_path = store._semantic_dir / f"{hashed}.json"
        bad_path.write_text("{not valid json")
        doc = store.load("bad")
        assert doc is None

    def test_load_invalid_annotation_returns_none(self, store):
        """load() should return None when annotation dict lacks required fields."""
        from memorygraph.semantic.models import file_path_hash
        hashed = file_path_hash("badann")
        bad_path = store._semantic_dir / f"{hashed}.json"
        bad_path.write_text(json.dumps({
            "file": "test.py",
            "annotations": [{"wrong_only": "missing symbol and kind"}]
        }))
        doc = store.load("badann")
        assert doc is None

    def test_load_all_skips_corrupt_files(self, store):
        """load_all() should skip corrupt JSON files without crashing."""
        store.save(SemanticDocument(file="good.py", module_summary="OK"))
        bad_path = store._semantic_dir / "bad.json"
        bad_path.write_text("corrupt{{{")
        docs = store.load_all()
        assert len(docs) == 1
        assert docs[0].file == "good.py"

    def test_load_all_empty_store(self, store):
        """load_all() on an empty store should return []."""
        docs = store.load_all()
        assert docs == []

    def test_load_all_with_many_documents(self, store):
        """load_all() should correctly load many documents."""
        for i in range(50):
            store.save(SemanticDocument(
                file=f"src/module_{i}.py",
                module_summary=f"Module {i}",
            ))
        docs = store.load_all()
        assert len(docs) >= 50
        files = {d.file for d in docs}
        for i in range(50):
            assert f"src/module_{i}.py" in files

    def test_delete_annotation_success(self, store):
        """delete_annotation returns True and actually removes the annotation."""
        store.save(SemanticDocument(
            file="src/app.py",
            annotations=[
                Annotation(symbol="foo", kind="function", summary="Foo"),
                Annotation(symbol="bar", kind="function", summary="Bar"),
                Annotation(symbol="foo", kind="function", summary="Foo2"),
            ],
        ))
        # Delete first "foo" annotation (index 0 in matches list)
        result = store.delete_annotation("src/app.py", "foo", index=0)
        assert result is True

        # Verify the annotation was actually removed (not just pop returned True)
        doc = store.load("src/app.py")
        assert doc is not None
        assert len(doc.annotations) == 2
        foo_annotations = [a for a in doc.annotations if a.symbol == "foo"]
        assert len(foo_annotations) == 1
        assert foo_annotations[0].summary == "Foo2"

    def test_delete_last_annotation(self, store):
        """Deleting the last annotation leaves an empty annotations list."""
        store.save(SemanticDocument(
            file="src/app.py",
            annotations=[
                Annotation(symbol="only", kind="function", summary="Only one"),
            ],
        ))
        result = store.delete_annotation("src/app.py", "only", index=0)
        assert result is True

        doc = store.load("src/app.py")
        assert doc is not None
        assert doc.annotations == []

    def test_delete_annotation_second_instance(self, store):
        """Delete the second annotation with the same symbol (index=1)."""
        store.save(SemanticDocument(
            file="src/app.py",
            annotations=[
                Annotation(symbol="foo", kind="function", summary="First"),
                Annotation(symbol="foo", kind="function", summary="Second"),
                Annotation(symbol="foo", kind="function", summary="Third"),
            ],
        ))
        result = store.delete_annotation("src/app.py", "foo", index=1)
        assert result is True

        doc = store.load("src/app.py")
        assert doc is not None
        assert len(doc.annotations) == 2
        summaries = {a.summary for a in doc.annotations}
        assert summaries == {"First", "Third"}

    def test_delete_annotation_save_load_roundtrip(self, store):
        """After delete + save + load, the annotation is gone (persisted)."""
        store.save(SemanticDocument(
            file="src/app.py",
            annotations=[
                Annotation(symbol="keep", kind="function", summary="Keep me"),
                Annotation(symbol="remove", kind="function", summary="Remove me"),
            ],
        ))
        store.delete_annotation("src/app.py", "remove", index=0)

        # Create a fresh store pointing to the same directory — simulates
        # another process or a later session.
        fresh_store = SemanticStore(store._project_root)
        doc = fresh_store.load("src/app.py")
        assert doc is not None
        assert len(doc.annotations) == 1
        assert doc.annotations[0].symbol == "keep"

    def test_delete_annotation_preserves_other_fields(self, store):
        """Deleting an annotation should not affect module_summary or unknowns."""
        store.save(SemanticDocument(
            file="src/app.py",
            module_summary="Important module",
            annotations=[
                Annotation(symbol="a", kind="function", summary="A"),
                Annotation(symbol="b", kind="function", summary="B"),
            ],
            unknowns=[
                Unknown(symbol="c", question="What does c do?"),
            ],
        ))
        store.delete_annotation("src/app.py", "b", index=0)

        doc = store.load("src/app.py")
        assert doc is not None
        assert doc.module_summary == "Important module"
        assert len(doc.annotations) == 1
        assert doc.annotations[0].symbol == "a"
        assert len(doc.unknowns) == 1
        assert doc.unknowns[0].symbol == "c"

    def test_delete_annotation_file_not_found(self, store):
        """delete_annotation returns False when the JSON file doesn't exist."""
        result = store.delete_annotation("never_saved.py", "foo", index=0)
        assert result is False

    def test_delete_annotation_nonexistent_file(self, store):
        """delete_annotation returns False when file not found (line 124-125)."""
        result = store.delete_annotation("nonexistent.py", "foo")
        assert result is False

    def test_delete_annotation_out_of_range_index(self, store):
        """delete_annotation returns False when index out of range (line 131)."""
        store.save(SemanticDocument(
            file="src/app.py",
            annotations=[
                Annotation(symbol="foo", kind="function", summary="Foo"),
            ],
        ))
        # Only 1 match for "foo" at index 0, but index=1 is out of range
        result = store.delete_annotation("src/app.py", "foo", index=1)
        assert result is False

    def test_delete_annotation_no_match(self, store):
        """delete_annotation returns False when symbol doesn't match (line 131)."""
        store.save(SemanticDocument(
            file="src/app.py",
            annotations=[
                Annotation(symbol="foo", kind="function", summary="Foo"),
            ],
        ))
        result = store.delete_annotation("src/app.py", "nonexistent")
        assert result is False


class TestSemanticDocumentMerge:
    """Tests for SemanticDocument.merge() method."""

    def test_merge_unknowns_dedup(self):
        """Merge should deduplicate unknowns by (symbol, question)."""
        from memorygraph.semantic.models import SemanticDocument, Unknown

        doc1 = SemanticDocument(file="a.py", source="test")
        doc1.unknowns.append(Unknown(symbol="foo", question="What?",
                                     context="ctx1"))
        doc1.unknowns.append(Unknown(symbol="bar", question="Why?",
                                     context="ctx2"))

        doc2 = SemanticDocument(file="b.py", source="test")
        doc2.unknowns.append(Unknown(symbol="foo", question="What?",
                                     context="ctx3"))  # Duplicate key
        doc2.unknowns.append(Unknown(symbol="baz", question="How?",
                                     context="ctx4"))  # New

        doc1.merge_from(doc2)
        assert len(doc1.unknowns) == 3  # foo/What deduped, bar/Why + baz/How
        symbols = [u.symbol for u in doc1.unknowns]
        assert "bar" in symbols
        assert "baz" in symbols

    def test_merge_metrics_and_roles(self):
        """Merge should update metrics and module_roles from other doc."""
        from memorygraph.semantic.models import SemanticDocument

        doc1 = SemanticDocument(file="a.py", source="test",
                                metrics={"lines": 100})
        doc1.module_roles = {"main": "controller"}

        doc2 = SemanticDocument(file="b.py", source="test",
                                metrics={"lines": 200, "classes": 5})
        doc2.module_roles = {"helper": "utility"}

        doc1.merge_from(doc2)
        assert doc1.metrics == {"lines": 200, "classes": 5}
        assert doc1.module_roles == {"main": "controller", "helper": "utility"}


class TestEmbeddingGeneratorPaths:
    """Cover EmbeddingGenerator missed lines in embeddings.py."""

    def test_check_sentence_transformers_import_error(self, monkeypatch):
        """_check_sentence_transformers returns False on ImportError (line 27)."""
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "sentence_transformers" in name:
                raise ImportError("mock import error")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        # Reset the module-level cache
        import memorygraph.semantic.embeddings as emb
        emb._SENTENCE_TRANSFORMERS_AVAILABLE = False
        result = emb._check_sentence_transformers()
        assert result is False

    def test_is_available_property(self):
        """is_available returns _available flag (line 52)."""
        from memorygraph.semantic.embeddings import EmbeddingGenerator
        gen = EmbeddingGenerator()
        assert gen.is_available in (True, False)

    def test_load_model_already_loaded(self):
        """_load_model returns early when model already loaded (lines 56-57)."""
        from memorygraph.semantic.embeddings import EmbeddingGenerator
        gen = EmbeddingGenerator()
        gen._available = False  # Prevent real loading
        gen._model = object()   # Pretend model is loaded
        # Should return without error (already loaded)
        gen._load_model()
        assert gen._model is not None

    def test_load_model_not_available_raises(self):
        """_load_model raises RuntimeError when not available (lines 58-59)."""
        import pytest

        from memorygraph.semantic.embeddings import EmbeddingGenerator
        gen = EmbeddingGenerator()
        gen._available = False
        gen._model = None
        with pytest.raises(RuntimeError, match="not installed"):
            gen._load_model()

    def test_generate_not_available_returns_none(self):
        """generate returns None when model not available (lines 81-82)."""
        from memorygraph.semantic.embeddings import EmbeddingGenerator
        gen = EmbeddingGenerator()
        gen._available = False
        result = gen.generate("foo")
        assert result is None

    def test_check_sentence_transformers_cached(self, monkeypatch):
        """_check_sentence_transformers returns True when already cached (line 20-21)."""
        import memorygraph.semantic.embeddings as emb
        emb._SENTENCE_TRANSFORMERS_AVAILABLE = True
        result = emb._check_sentence_transformers()
        assert result is True
        emb._SENTENCE_TRANSFORMERS_AVAILABLE = False  # Restore

    def test_generate_with_mocked_model(self):
        """generate() with mocked SentenceTransformer covers lines 84-96."""
        from unittest import mock

        import numpy as np

        from memorygraph.semantic.embeddings import EmbeddingGenerator

        # Create a mock model that returns fake embeddings
        mock_model = mock.MagicMock()
        fake_vec = np.random.randn(384).astype(np.float32)
        mock_model.encode.return_value = fake_vec

        gen = EmbeddingGenerator()
        gen._available = True
        gen._model = mock_model  # Simulate loaded model

        result = gen.generate("test_func", "def test_func():", "test module")
        assert result is not None
        assert isinstance(result, np.ndarray)
        assert result.shape == (384,)
        mock_model.encode.assert_called_once()
        # Verify text was built from parts (lines 88-93)
        call_text = mock_model.encode.call_args[0][0]
        assert "test_func" in call_text
        assert "def test_func():" in call_text
        assert "test module" in call_text

    def test_load_model_with_mocked_sentence_transformers(self):
        """_load_model loads SentenceTransformer when available (lines 63-64)."""
        from unittest import mock

        from memorygraph.semantic.embeddings import EmbeddingGenerator

        mock_st = mock.MagicMock()
        # SentenceTransformer is imported inside _load_model with 'from sentence_transformers import SentenceTransformer'
        with mock.patch.dict("sys.modules", {"sentence_transformers": mock.MagicMock()}):
            import sentence_transformers as st_mod
            st_mod.SentenceTransformer = mock_st

            gen = EmbeddingGenerator()
            gen._available = True
            gen._model = None
            gen._load_model()
            assert gen._model is not None
            mock_st.assert_called_once_with("all-MiniLM-L6-v2", local_files_only=True)

    def test_generate_only_name_no_signature_context(self):
        """generate with only name (no signature/context) covers line 88-93 with empty fields."""
        from unittest import mock

        import numpy as np

        from memorygraph.semantic.embeddings import EmbeddingGenerator

        mock_model = mock.MagicMock()
        mock_model.encode.return_value = np.zeros(384, dtype=np.float32)

        gen = EmbeddingGenerator()
        gen._available = True
        gen._model = mock_model

        result = gen.generate("simple_name")
        assert result is not None
        assert result.shape == (384,)
        call_text = mock_model.encode.call_args[0][0]
        assert call_text == "simple_name"  # Only name, no signature/context
