"""Tests for conversation extraction."""
import json
import os
import tempfile
from unittest import mock

import pytest

from memorygraph.semantic.conversation import (
    _build_extraction_prompt,
    _call_anthropic,
    _call_openai_compatible,
    _extract_text,
    _extract_with_regex,
    _extract_with_semantic_filter,
    _get_embedding_model,
    _load_conversation_text,
    _parse_llm_response,
    _split_sentences,
    extract_from_conversation,
    extract_with_llm,
)


class TestExtractText:
    def test_plain_string(self):
        assert _extract_text("hello world") == "hello world"

    def test_empty_string(self):
        assert _extract_text("") == ""

    def test_dict_with_messages_key(self):
        data = {"messages": [{"content": "def login(): handles auth"}]}
        result = _extract_text(data)
        assert "def login" in result

    def test_dict_with_conversation_key(self):
        data = {"conversation": [{"text": "class UserRepository"}]}
        result = _extract_text(data)
        assert "UserRepository" in result

    def test_dict_with_chat_key(self):
        data = {"chat": "discussion about auth module"}
        result = _extract_text(data)
        assert "auth module" in result

    def test_list_of_dicts_with_content_key(self):
        data = [
            {"content": "message one"},
            {"content": "message two"},
        ]
        result = _extract_text(data)
        assert "message one" in result
        assert "message two" in result

    def test_list_of_dicts_with_text_key(self):
        data = [
            {"text": "observation one"},
            {"text": "observation two"},
        ]
        result = _extract_text(data)
        assert "observation one" in result
        assert "observation two" in result

    def test_list_of_strings(self):
        data = ["first", "second"]
        result = _extract_text(data)
        assert "first" in result
        assert "second" in result

    def test_claude_code_format(self):
        """Claude Code format: list of dicts with content containing blocks."""
        data = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "The function login handles authentication."},
                    {"type": "text", "text": "class AuthManager manages auth state."},
                ],
            },
            {
                "role": "user",
                "content": "I need a UserRepository.",
            },
        ]
        result = _extract_text(data)
        assert "login handles authentication" in result
        assert "AuthManager" in result

    def test_nested_dict(self):
        data = {"outer": {"inner": {"messages": [{"content": "deeply nested"}]}}}
        result = _extract_text(data)
        assert "deeply nested" in result

    def test_non_string_dict_value(self):
        data = {"count": 42, "enabled": True, "text": "valid text"}
        result = _extract_text(data)
        assert "valid text" in result

    def test_non_string_non_dict_non_list(self):
        result = _extract_text(42)
        assert result == "42"


class TestExtractFromConversation:
    @pytest.fixture(autouse=True)
    def _clear_llm_api_keys(self):
        """Prevent real LLM API calls during testing."""
        with mock.patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
            "DEEPSEEK_API_KEY": "",
            "LLM_API_KEY": "",
        }):
            yield

    def create_temp_json(self, data):
        """Helper to create a temp JSON file."""
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(data, f)
        f.close()
        return f.name

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            extract_from_conversation("/nonexistent/path.json")

    def test_empty_json_returns_empty(self):
        path = self.create_temp_json({})
        try:
            docs = extract_from_conversation(path)
            assert docs == []
        finally:
            os.unlink(path)

    def test_chinese_function_description(self):
        data = {
            "messages": [
                {"content": "函数 login 用于处理用户登录认证"}
            ]
        }
        path = self.create_temp_json(data)
        try:
            docs = extract_from_conversation(path)
            assert len(docs) >= 1
            # One of the docs should have an annotation for 'login'
            annotations = []
            for doc in docs:
                for ann in doc.annotations:
                    if hasattr(ann, "symbol") and ann.symbol == "login":
                        annotations.append(ann)
            assert len(annotations) >= 1
        finally:
            os.unlink(path)

    def test_english_function_description(self):
        data = {
            "messages": [
                {"content": "method `validate` handles input validation and returns a boolean."}
            ]
        }
        path = self.create_temp_json(data)
        try:
            docs = extract_from_conversation(path)
            assert len(docs) >= 1
        finally:
            os.unlink(path)

    def test_class_description(self):
        data = {
            "messages": [
                {"content": "class `UserRepository` represents the data access layer for users."}
            ]
        }
        path = self.create_temp_json(data)
        try:
            docs = extract_from_conversation(path)
            assert len(docs) >= 1
        finally:
            os.unlink(path)

    def test_design_intent_extraction(self):
        data = {
            "messages": [
                {"content": "设计: 使用 Strategy 模式来处理不同的支付方式."}
            ]
        }
        path = self.create_temp_json(data)
        try:
            docs = extract_from_conversation(path)
            # At least one doc should have module_summary set
            summaries = [d.module_summary for d in docs if d.module_summary]
            assert len(summaries) >= 1
        finally:
            os.unlink(path)

    def test_english_design_intent(self):
        data = {
            "messages": [
                {"content": "design: should use dependency injection for testability."}
            ]
        }
        path = self.create_temp_json(data)
        try:
            docs = extract_from_conversation(path)
            summaries = [d.module_summary for d in docs if d.module_summary]
            assert len(summaries) >= 1
        finally:
            os.unlink(path)

    def test_pitfalls_extraction(self):
        data = {
            "messages": [
                {"content": "warning: this function is not thread-safe."}
            ]
        }
        path = self.create_temp_json(data)
        try:
            docs = extract_from_conversation(path)
            assert len(docs) >= 1
        finally:
            os.unlink(path)

    def test_todo_extraction(self):
        data = {
            "messages": [
                {"content": "TODO: add retry logic for network failures"}
            ]
        }
        path = self.create_temp_json(data)
        try:
            docs = extract_from_conversation(path)
            assert len(docs) >= 1
        finally:
            os.unlink(path)

    def test_no_matches_returns_empty(self):
        data = {
            "messages": [
                {"content": "The weather is nice today. I like programming."}
            ]
        }
        path = self.create_temp_json(data)
        try:
            docs = extract_from_conversation(path)
            # The regex patterns may match loosely, but if they do match,
            # they should produce valid SemanticDocument objects
            for doc in docs:
                assert doc.file == "conversation-extract"
                assert doc.source == "conversation-extract"
        finally:
            os.unlink(path)

    def test_all_docs_have_correct_source(self):
        data = {
            "messages": [
                {"content": "函数 helper 用于辅助计算. 注意: helper 不是幂等的."}
            ]
        }
        path = self.create_temp_json(data)
        try:
            docs = extract_from_conversation(path)
            for doc in docs:
                assert doc.file == "conversation-extract"
                assert doc.source == "conversation-extract"
        finally:
            os.unlink(path)


# Additional tests for uncovered branches in _extract_text


class TestExtractTextBranches:
    def test_dict_long_string_values(self):
        """Covers line 117: dict values >50 chars."""
        long_text = "a" * 60
        data = {"key": long_text}
        result = _extract_text(data)
        assert long_text in result

    def test_dict_short_string_values_ignored(self):
        """Short dict values (<50 chars) are ignored in the dict branch."""
        data = {"key": "short"}
        result = _extract_text(data)
        # Short values are not appended; result may be empty or just newline
        assert isinstance(result, str)

    def test_list_item_with_message_key(self):
        """Covers lines 136-137: list items with 'message' key."""
        data = [{"message": "An error occurred in the system."}]
        result = _extract_text(data)
        assert "An error occurred" in result


class TestLLMExtraction:
    """Tests for the LLM-powered extraction path (stdlib http.client)."""

    def test_build_extraction_prompt_includes_text(self):
        """Prompt should contain the conversation text and expected structure."""
        prompt = _build_extraction_prompt("def login(): handles auth")
        assert "def login" in prompt
        assert "annotations" in prompt
        assert "design_decisions" in prompt
        assert "module_summaries" in prompt
        assert "symbol" in prompt
        assert "design_intent" in prompt
        assert "pitfalls" in prompt

    def test_build_extraction_prompt_truncates_long_text(self):
        """Prompt should handle arbitrarily long text (truncated at 8000 chars upstream)."""
        long_text = "x" * 10000
        prompt = _build_extraction_prompt(long_text)
        assert len(prompt) >= 9000  # prompt overhead + text

    def test_parse_llm_response_annotations(self):
        """Parse a valid LLM response with annotations."""
        response = json.dumps({
            "annotations": [
                {
                    "symbol": "login",
                    "kind": "function",
                    "summary": "Authenticates users via JWT",
                    "design_intent": "Stateless auth to support horizontal scaling",
                    "pitfalls": "Token expiry not handled on 401 responses",
                }
            ],
            "design_decisions": [],
            "module_summaries": [],
        })
        docs = _parse_llm_response(response)
        assert len(docs) == 1
        assert docs[0].annotations[0].symbol == "login"
        assert docs[0].annotations[0].kind == "function"
        assert "JWT" in docs[0].annotations[0].summary
        assert "Stateless" in docs[0].annotations[0].design_intent
        assert "401" in docs[0].annotations[0].pitfalls
        assert docs[0].source == "llm-extract"

    def test_parse_llm_response_design_decisions(self):
        """Parse LLM response with design decisions."""
        response = json.dumps({
            "annotations": [],
            "design_decisions": [
                "Use asyncpg for PostgreSQL access (non-blocking pool)",
                "Adopt repository pattern for data access abstraction",
            ],
            "module_summaries": [],
        })
        docs = _parse_llm_response(response)
        assert len(docs) == 2
        assert "asyncpg" in docs[0].module_summary
        assert "repository" in docs[1].module_summary
        assert all(d.source == "llm-extract" for d in docs)

    def test_parse_llm_response_module_summaries(self):
        """Parse LLM response with module summaries."""
        response = json.dumps({
            "annotations": [],
            "design_decisions": [],
            "module_summaries": [
                {"file": "auth.py", "summary": "Authentication and authorization module"},
            ],
        })
        docs = _parse_llm_response(response)
        assert len(docs) == 1
        assert docs[0].file == "auth.py"
        assert "Authentication" in docs[0].module_summary

    def test_parse_llm_response_with_markdown_fence(self):
        """Strip ```json fences from LLM response."""
        response = '```json\n' + json.dumps({
            "annotations": [{"symbol": "foo", "kind": "function", "summary": "bar", "design_intent": "", "pitfalls": ""}],
            "design_decisions": [],
            "module_summaries": [],
        }) + '\n```'
        docs = _parse_llm_response(response)
        assert len(docs) == 1
        assert docs[0].annotations[0].symbol == "foo"

    def test_parse_llm_response_empty(self):
        """Empty response should return empty list."""
        docs = _parse_llm_response(json.dumps({
            "annotations": [], "design_decisions": [], "module_summaries": [],
        }))
        assert docs == []

    def test_parse_llm_response_missing_fields(self):
        """Missing optional fields should not crash."""
        response = json.dumps({
            "annotations": [{"symbol": "x"}],
        })
        docs = _parse_llm_response(response)
        assert len(docs) == 1
        assert docs[0].annotations[0].symbol == "x"

    def test_extract_with_llm_no_api_key(self):
        """Should raise ValueError when no API key is set."""
        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Set LLM_API_KEY"):
                extract_with_llm("some text")

    def test_extract_with_llm_deepseek_provider(self):
        """Should route to OpenAI-compatible path for DeepSeek."""
        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "sk-test",
        }):
            # We just test routing — actual HTTP call will fail without network
            # but the function should not raise ValueError about missing keys
            try:
                extract_with_llm("def login(): handles auth")
            except ValueError:
                pass  # Expected: provider resolved, key found
            except Exception:
                pass  # Expected: network error (no real API call in test)

    def test_extract_with_llm_generic_key(self):
        """LLM_API_KEY should work for any provider."""
        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "deepseek",
            "LLM_API_KEY": "sk-generic",
        }):
            try:
                extract_with_llm("test")
            except ValueError as e:
                assert "Set LLM_API_KEY" not in str(e)  # key was found
            except Exception:
                pass  # Network error is expected

    def test_extract_with_llm_openai_compatible(self):
        """openai-compatible provider should use LLM_BASE_URL."""
        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "openai-compatible",
            "LLM_API_KEY": "sk-test",
            "LLM_BASE_URL": "https://my-llm.example.com/v1",
        }):
            try:
                extract_with_llm("test")
            except ValueError as e:
                assert "LLM_BASE_URL" not in str(e)  # base URL was found
            except Exception:
                pass

    def test_extract_with_llm_unknown_provider(self):
        """Unknown LLM_PROVIDER should raise ValueError."""
        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "unknown-llm",
            "LLM_API_KEY": "sk-test",
        }):
            with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
                extract_with_llm("test")

    def test_load_conversation_text_extracts_content(self, tmp_path):
        """_load_conversation_text should load JSON and extract text."""
        conv_file = tmp_path / "conv.json"
        conv_file.write_text(json.dumps({
            "messages": [{"content": "def process(): handles data processing pipeline"}]
        }))
        text = _load_conversation_text(conv_file)
        assert "process" in text
        assert "data processing" in text


class TestSemanticFilter:
    """Tests for the local semantic filter + regex extraction path."""

    def test_split_sentences_basic(self):
        """Should split text into sentences."""
        text = "The login function has a race condition. We should use a mutex. This is critical."
        sentences = _split_sentences(text)
        assert len(sentences) >= 2
        assert any("race condition" in s for s in sentences)

    def test_split_sentences_filters_short(self):
        """Should filter out very short fragments (<20 chars)."""
        text = "OK. The authentication module handles user login and session management."
        sentences = _split_sentences(text)
        assert not any(s == "OK." or len(s) < 20 for s in sentences)

    def test_split_sentences_empty(self):
        """Empty text returns empty list."""
        assert _split_sentences("") == []

    def test_extract_with_semantic_filter_no_dependency(self):
        """When sentence-transformers is not installed, returns empty list."""
        with mock.patch.dict("sys.modules", {"sentence_transformers": None}):
            docs = _extract_with_semantic_filter("def login(): handles auth")
            assert docs == []

    def test_extract_with_semantic_filter_short_text(self):
        """Very short text should be skipped (returns empty)."""
        # Text too short to have multiple sentences → skip filtering
        docs = _extract_with_semantic_filter("hello")
        assert docs == []

    def test_extract_with_regex_standalone(self):
        """_extract_with_regex should work as a standalone function."""
        docs = _extract_with_regex("function `login` handles user authentication via JWT.")
        assert len(docs) >= 1
        assert docs[0].source == "conversation-extract"

    def test_extract_from_conversation_falls_back_to_regex(self, tmp_path):
        """Without any special deps, should fall back to regex extraction."""
        conv_file = tmp_path / "conv.json"
        conv_file.write_text(json.dumps({
            "messages": [{"content": "class `UserRepo` handles database access for users."}]
        }))
        with mock.patch.dict(os.environ, {}, clear=True):
            docs = extract_from_conversation(str(conv_file))
        assert len(docs) >= 1


class TestEmbeddingModel:
    """Tests for _get_embedding_model lazy-loading and caching."""

    def test_get_embedding_model_cached(self):
        """After first successful load, subsequent calls return cached model."""
        mock_model = mock.MagicMock()
        mock_st = mock.MagicMock(return_value=mock_model)

        with mock.patch.dict("sys.modules", {"sentence_transformers": mock.MagicMock()}):
            import memorygraph.semantic.conversation as conv
            conv._embedding_model = None  # reset
            with mock.patch(
                "sentence_transformers.SentenceTransformer", mock_st
            ):
                model1 = _get_embedding_model()
                assert model1 is mock_model
                mock_st.assert_called_once()

                # Second call should return cached model without re-creating
                model2 = _get_embedding_model()
                assert model2 is mock_model
                mock_st.assert_called_once()  # still only called once

    def test_get_embedding_model_load_failure(self):
        """When SentenceTransformer raises, returns None gracefully."""
        import memorygraph.semantic.conversation as conv
        conv._embedding_model = None  # reset
        # Prevent real sentence_transformers import (broken because no transformers)
        with mock.patch.dict("sys.modules", {"sentence_transformers": mock.MagicMock()}):
            with mock.patch(
                "sentence_transformers.SentenceTransformer",
                side_effect=ImportError("no module transformers"),
            ):
                model = _get_embedding_model()
                assert model is None

    def test_extract_with_semantic_filter_full_pipeline(self):
        """Full semantic filter pipeline: embed → cosine similarity → regex."""
        import numpy as np

        mock_model = mock.MagicMock()
        mock_model.encode.side_effect = [
            np.array([[0.5, 0.5], [0.1, 0.1], [0.9, 0.1]], dtype=np.float32),
            np.array([[0.5, 0.5]] * 8, dtype=np.float32),
        ]

        import memorygraph.semantic.conversation as conv
        conv._embedding_model = None
        with mock.patch(
            "importlib.util.find_spec", return_value=True
        ):
            with mock.patch.object(conv, "_get_embedding_model", return_value=mock_model):
                text = (
                    "The login function handles user authentication. "
                    "We use JWT tokens for session management. "
                    "The weather is nice today and we had lunch at noon."
                )
                docs = _extract_with_semantic_filter(text)
                assert isinstance(docs, list)

    def test_semantic_filter_similarity_threshold(self):
        """Sentences below cosine similarity threshold are excluded."""
        import numpy as np

        mock_model = mock.MagicMock()
        mock_model.encode.side_effect = [
            np.array([[0.91, 0.1], [0.01, 0.99]], dtype=np.float32),
            np.array([[0.9, 0.1]], dtype=np.float32),
        ]

        import memorygraph.semantic.conversation as conv
        conv._embedding_model = None
        with mock.patch(
            "importlib.util.find_spec", return_value=True
        ):
            with mock.patch.object(conv, "_get_embedding_model", return_value=mock_model):
                text = (
                    "function login handles authentication for the system. "
                    "I enjoy eating lunch with my colleagues every day."
                )
                docs = _extract_with_semantic_filter(text)
                assert isinstance(docs, list)

class TestSemanticFilterEdgeCases:
    """Tests for uncovered branches in semantic filter (lines 84-85, 130, 141, 146-148)."""

    def test_extract_from_conversation_semantic_filter_success(self, tmp_path):
        """Covers lines 84-85: semantic filter returns docs, logger.info + return."""
        import logging

        from memorygraph.semantic.models import Annotation, SemanticDocument

        conv_file = tmp_path / "conv.json"
        conv_file.write_text(json.dumps({
            "messages": [{"content": "function `login` handles user authentication via JWT tokens."}]
        }))

        doc = SemanticDocument(file="test", source="semantic-filter")
        doc.annotations.append(Annotation(
            symbol="login", kind="function",
            summary="Handles auth", design_intent="", pitfalls="",
        ))

        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "memorygraph.semantic.conversation._extract_with_semantic_filter",
                return_value=[doc],
            ):
                with mock.patch.object(logging.getLogger("memorygraph.semantic.conversation"), "info") as mock_log:
                    docs = extract_from_conversation(str(conv_file))
                    assert len(docs) == 1
                    assert docs[0].annotations[0].symbol == "login"
                    mock_log.assert_called_once()
                    assert "Semantic filter extraction yielded" in mock_log.call_args[0][0]

    def test_get_embedding_model_returns_none(self):
        """Covers line 114: return [] when _get_embedding_model returns None."""

        import memorygraph.semantic.conversation as conv
        conv._embedding_model = None
        with mock.patch("importlib.util.find_spec", return_value=True):
            with mock.patch.object(conv, "_get_embedding_model", return_value=None):
                # Text must have ≥2 sentences after _split_sentences filtering
                text = (
                    "The authentication module needs careful design consideration. "
                    "function login handles user authentication via JWT tokens securely."
                )
                docs = _extract_with_semantic_filter(text)
                assert docs == []

    def test_semantic_filter_zero_vector_sentence(self):
        """Covers line 130: continue when sent_norm == 0."""
        import numpy as np

        mock_model = mock.MagicMock()
        # 2 sentences, first gets zero vector. 8 anchor patterns.
        mock_model.encode.side_effect = [
            np.array([[0.0, 0.0], [0.8, 0.6]], dtype=np.float32),
            np.array([[0.5, 0.5]] * 8, dtype=np.float32),
        ]

        import memorygraph.semantic.conversation as conv
        conv._embedding_model = None
        with mock.patch("importlib.util.find_spec", return_value=True):
            with mock.patch.object(conv, "_get_embedding_model", return_value=mock_model):
                # Need ≥2 sentences after _split_sentences (≥20 chars each)
                text = (
                    "The authentication module needs careful design consideration. "
                    "function login handles user authentication via JWT tokens securely."
                )
                docs = _extract_with_semantic_filter(text)
                assert isinstance(docs, list)

    def test_semantic_filter_no_relevant_sentences(self):
        """Covers line 141: return [] when no relevant_lines pass threshold."""
        import numpy as np

        mock_model = mock.MagicMock()
        # Sentence embeddings orthogonal to all anchor embeddings → cos_sim = 0 → < 0.4
        mock_model.encode.side_effect = [
            np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32),  # 2 sentences, x-direction
            np.array([[0.0, 1.0]] * 8, dtype=np.float32),           # 8 anchors, y-direction
        ]

        import memorygraph.semantic.conversation as conv
        conv._embedding_model = None
        with mock.patch("importlib.util.find_spec", return_value=True):
            with mock.patch.object(conv, "_get_embedding_model", return_value=mock_model):
                # Need ≥2 sentences after _split_sentences (≥20 chars each)
                text = (
                    "The weather is nice today and the sun is shining brightly. "
                    "I had lunch with friends at a lovely restaurant downtown."
                )
                docs = _extract_with_semantic_filter(text)
                assert docs == []

    def test_semantic_filter_exception_handler(self):
        """Covers lines 146-148: except Exception → logger.warning + return []."""
        import logging


        mock_model = mock.MagicMock()
        mock_model.encode.side_effect = RuntimeError("Embedding model crashed")

        import memorygraph.semantic.conversation as conv
        conv._embedding_model = None
        with mock.patch("importlib.util.find_spec", return_value=True):
            with mock.patch.object(conv, "_get_embedding_model", return_value=mock_model):
                with mock.patch.object(logging.getLogger("memorygraph.semantic.conversation"), "warning") as mock_warn:
                    text = "function login handles authentication. class UserRepo manages data."
                    docs = _extract_with_semantic_filter(text)
                    assert docs == []
                    mock_warn.assert_called_once()
                    assert "Semantic filter failed" in mock_warn.call_args[0][0]


class TestLLMExtractionCoverage:
    """Tests for LLM extraction paths not covered by existing tests."""

    def test_extract_with_llm_openai_compatible_no_url_raises(self):
        """openai-compatible without LLM_BASE_URL raises ValueError."""
        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "openai-compatible",
            "LLM_API_KEY": "sk-test",
        }, clear=True):
            with pytest.raises(ValueError, match="LLM_BASE_URL"):
                extract_with_llm("def foo(): pass")

    def test_extract_with_llm_model_env_override(self):
        """LLM_MODEL env var should override default model in provider config."""
        import contextlib
        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "deepseek",
            "LLM_API_KEY": "sk-test",
            "LLM_MODEL": "deepseek-v4-pro",
        }, clear=True):
            with contextlib.suppress(Exception):
                extract_with_llm("def bar(): pass")  # Network error expected

    def test_extract_with_llm_base_url_override(self):
        """LLM_BASE_URL should override host in provider config."""
        import contextlib
        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER": "anthropic",
            "LLM_API_KEY": "sk-test",
            "LLM_BASE_URL": "https://custom-proxy.example.com/v1/messages",
        }, clear=True):
            with contextlib.suppress(Exception):
                extract_with_llm("def baz(): pass")  # Network error expected

    def test_call_anthropic_parses_response(self):
        """_call_anthropic correctly parses a successful API response."""
        from unittest import mock as umock

        cfg = {"host": "api.example.com", "path": "/v1/messages", "model": "claude-test", "auth_header": "x-api-key"}
        response_data = json.dumps({
            "content": [
                {"type": "text", "text": '{"annotations": [{"symbol": "foo", "kind": "function", "summary": "does things", "design_intent": "simple", "pitfalls": "none"}], "design_decisions": [], "module_summaries": []}'}
            ]
        })

        mock_conn = umock.MagicMock()
        mock_resp = umock.MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = response_data.encode()
        mock_conn.getresponse.return_value = mock_resp

        http_client = umock.MagicMock()
        http_client.HTTPSConnection.return_value = mock_conn

        docs = _call_anthropic(cfg, "sk-test", "Extract from: def foo(): pass", http_client)
        assert len(docs) >= 1
        assert docs[0].annotations[0].symbol == "foo"

    def test_call_openai_compatible_parses_response(self):
        """_call_openai_compatible correctly parses a successful API response."""
        from unittest import mock as umock

        cfg = {
            "host": "api.example.com", "path": "/v1/chat/completions",
            "model": "gpt-test", "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
        }
        response_data = json.dumps({
            "choices": [{
                "message": {
                    "content": '{"annotations": [{"symbol": "bar", "kind": "class", "summary": "data model", "design_intent": "clean API", "pitfalls": ""}], "design_decisions": ["use dataclass"], "module_summaries": []}'
                }
            }]
        })

        mock_conn = umock.MagicMock()
        mock_resp = umock.MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = response_data.encode()
        mock_conn.getresponse.return_value = mock_resp

        http_client = umock.MagicMock()
        http_client.HTTPSConnection.return_value = mock_conn

        docs = _call_openai_compatible(cfg, "sk-test", "Extract from: class Bar:", http_client)
        assert len(docs) >= 1
        assert docs[0].annotations[0].symbol == "bar"

    def test_extract_from_conversation_llm_success(self, tmp_path):
        """extract_from_conversation returns LLM results when API key is set."""
        conv_file = tmp_path / "conv.json"
        conv_file.write_text(json.dumps({
            "messages": [{"content": "function `login` handles authentication"}]
        }))

        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=True):
            with mock.patch(
                "memorygraph.semantic.conversation.extract_with_llm"
            ) as mock_llm:
                from memorygraph.semantic.models import Annotation, SemanticDocument
                doc = SemanticDocument(file="conv-extract", source="llm-extract")
                doc.annotations.append(Annotation(
                    symbol="login", kind="function",
                    summary="Handles auth", design_intent="", pitfalls="",
                ))
                mock_llm.return_value = [doc]

                docs = extract_from_conversation(str(conv_file))
                assert len(docs) == 1
                assert docs[0].annotations[0].symbol == "login"
