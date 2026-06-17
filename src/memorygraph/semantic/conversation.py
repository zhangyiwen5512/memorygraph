"""Extract semantic annotations from Claude Code conversation exports.

Three extraction tiers (auto-selected by available dependencies):

1. **Semantic filter + regex** (default, local, zero API key)
   Uses sentence-transformers embeddings to identify code-relevant sentences,
   then applies regex patterns on filtered text. No external API needed.

2. **LLM-powered** (opt-in, requires ANTHROPIC_API_KEY)
   Sends conversation to Claude API with a structured JSON extraction prompt.
   Deepest understanding but requires network + API key.

3. **Regex-only** (fallback, zero dependencies)
   Pure pattern matching. Works everywhere but lower precision.

Fallback chain: semantic filter → regex-only → empty result.
LLM path overrides everything when API key is set.
"""
import json
import logging
import os
import re
from pathlib import Path

from memorygraph.semantic.models import Annotation, SemanticDocument

logger = logging.getLogger(__name__)

# ── semantic filtering prompts (used with sentence-transformers) ──────────

_CODE_SEMANTIC_PATTERNS = [
    "function description code purpose what it does",
    "class description code architecture design pattern",
    "software design decision trade-off architecture choice",
    "bug issue pitfall edge case gotcha warning",
    "code refactoring improvement optimization suggestion",
    "API endpoint route handler request response",
    "database schema table column query optimization",
    "module file responsibility separation of concerns",
]


def extract_from_conversation(conversation_path: str) -> list[SemanticDocument]:
    """Extract semantic annotations from a conversation file.

    Auto-selects best extraction tier based on available dependencies:
    sentence-transformers → regex → empty.

    Set ANTHROPIC_API_KEY to use LLM extraction (overrides local methods).

    Args:
        conversation_path: Path to the conversation JSON file

    Returns:
        List of SemanticDocument objects with extracted annotations.
    """
    path = Path(conversation_path)
    if not path.exists():
        raise FileNotFoundError(f"Conversation file not found: {conversation_path}")

    text = _load_conversation_text(path)

    if not text:
        return []

    # LLM path (opt-in, overrides everything when any API key is set)
    _any_llm_key = any(
        os.environ.get(k) for k in (
            "LLM_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
        )
    )
    if _any_llm_key:
        try:
            docs = extract_with_llm(text)
            if docs:
                logger.info("LLM extraction yielded %d document(s)", len(docs))
                return docs
        except Exception:
            logger.warning("LLM extraction failed, falling back", exc_info=True)

    # Semantic filter path (local, no API key)
    docs = _extract_with_semantic_filter(text)
    if docs:
        logger.info("Semantic filter extraction yielded %d document(s)", len(docs))
        return docs

    # Regex-only fallback
    return _extract_with_regex(text)


# ── Tier 1: semantic filter + regex ──────────────────────────────────────

def _extract_with_semantic_filter(text: str) -> list[SemanticDocument]:
    """Filter conversation sentences by code relevance, then apply regex.

    Uses sentence-transformers to compute cosine similarity between each
    sentence and code-semantic anchor patterns. Only sentences above the
    similarity threshold are passed to regex extraction.

    Returns empty list if sentence-transformers is not available.
    """
    import importlib.util
    if importlib.util.find_spec("sentence_transformers") is None:
        return []

    sentences = _split_sentences(text)
    if len(sentences) < 2:
        # Too short to benefit from filtering; let regex handle it
        return []

    try:
        model = _get_embedding_model()
        if model is None:
            return []

        # Compute embeddings
        sentence_embeddings = model.encode(sentences, show_progress_bar=False)
        anchor_embeddings = model.encode(_CODE_SEMANTIC_PATTERNS, show_progress_bar=False)

        # Cosine similarity: each sentence vs max anchor similarity
        from numpy import dot
        from numpy.linalg import norm as np_norm

        anchor_norms = [np_norm(a) for a in anchor_embeddings]
        relevant_lines: list[str] = []

        for i, sent_emb in enumerate(sentence_embeddings):
            sent_norm = np_norm(sent_emb)
            if sent_norm == 0:
                continue
            # Max cosine similarity across all anchor patterns
            max_sim = max(
                dot(sent_emb, anchor_emb) / (sent_norm * anchor_norms[j])
                for j, anchor_emb in enumerate(anchor_embeddings)
                if anchor_norms[j] > 0
            )
            if max_sim > 0.4:  # Threshold: moderately relevant or better
                relevant_lines.append(sentences[i])

        if not relevant_lines:
            return []

        filtered_text = "\n".join(relevant_lines)
        return _extract_with_regex(filtered_text)

    except Exception:
        logger.warning("Semantic filter failed, will use regex fallback", exc_info=True)
        return []


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences (basic, no NLTK dependency)."""
    # Split on sentence boundaries
    raw = re.split(r'(?<=[.!?。！？\n])\s+', text)
    return [s.strip() for s in raw if len(s.strip()) > 20]


_embedding_model: object = None  # type: ignore[annotation-unchecked]


def _get_embedding_model():
    """Lazy-load the sentence-transformers model (cached)."""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    try:
        from sentence_transformers import SentenceTransformer
        # Use a small, fast model (80 MB, <50ms per encode)
        _embedding_model = SentenceTransformer(
            "all-MiniLM-L6-v2",
            cache_folder=os.path.join(
                os.path.expanduser("~"), ".cache", "memorygraph", "models"
            ),
        )
        return _embedding_model
    except Exception:
        logger.warning("Could not load embedding model", exc_info=True)
        return None


# ── Tier 2: LLM extraction (opt-in, external API) ────────────────────────

# Provider defaults: (api_host, path, model)
_LLM_PROVIDERS = {
    "anthropic": {
        "host": "api.anthropic.com",
        "path": "/v1/messages",
        "model": "claude-sonnet-4-6",
        "auth_header": "x-api-key",
        "protocol": "anthropic",
    },
    "deepseek": {
        "host": "api.deepseek.com",
        "path": "/v1/chat/completions",
        "model": "deepseek-chat",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "protocol": "openai",
    },
    "openai": {
        "host": "api.openai.com",
        "path": "/v1/chat/completions",
        "model": "gpt-4o",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "protocol": "openai",
    },
}


def extract_with_llm(conversation_text: str) -> list[SemanticDocument]:
    """Extract semantic annotations using LLM API (multi-provider).

    Provider selection (checked in order):
    1. ``LLM_PROVIDER`` env var: ``anthropic`` | ``deepseek`` | ``openai`` | ``openai-compatible``
    2. ``LLM_API_KEY`` env var: generic API key
    3. ``LLM_MODEL`` env var: model name override
    4. ``LLM_BASE_URL`` env var: custom base URL (for openai-compatible)

    Falls back to provider-specific env vars:
    ``ANTHROPIC_API_KEY``, ``DEEPSEEK_API_KEY``, ``OPENAI_API_KEY``

    Uses stdlib http.client only — no additional dependencies.
    """
    import http.client as http_client

    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()

    # Resolve API key
    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        # Fall back to provider-specific env vars
        key_env_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        api_key = os.environ.get(key_env_map.get(provider, ""), "")
    if not api_key:
        raise ValueError(
            f"Set LLM_API_KEY or {key_env_map.get(provider, provider.upper() + '_API_KEY')} "
            f"environment variable"
        )

    # Resolve provider config
    if provider == "openai-compatible":
        base_url = os.environ.get("LLM_BASE_URL", "")
        if not base_url:
            raise ValueError("LLM_BASE_URL required for openai-compatible provider")
        # Parse host + path from base_url
        if "://" in base_url:
            base_url = base_url.split("://", 1)[1]
        host, _, path = base_url.partition("/")
        path = "/v1/chat/completions" if not path else "/" + path
        provider_cfg = {
            "host": host,
            "path": path,
            "model": os.environ.get("LLM_MODEL", "gpt-4o"),
            "auth_header": "Authorization",
            "auth_prefix": "Bearer ",
            "protocol": "openai",
        }
    elif provider in _LLM_PROVIDERS:
        provider_cfg = dict(_LLM_PROVIDERS[provider])
        if os.environ.get("LLM_MODEL"):
            provider_cfg["model"] = os.environ["LLM_MODEL"]
        if os.environ.get("LLM_BASE_URL"):
            base_url = os.environ["LLM_BASE_URL"]
            if "://" in base_url:
                base_url = base_url.split("://", 1)[1]
            host, _, custom_path = base_url.partition("/")
            provider_cfg["host"] = host
            if custom_path:
                provider_cfg["path"] = "/" + custom_path
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{provider}'. "
            f"Supported: anthropic, deepseek, openai, openai-compatible"
        )

    prompt = _build_extraction_prompt(conversation_text[:8000])

    if provider_cfg["protocol"] == "anthropic":
        return _call_anthropic(provider_cfg, api_key, prompt, http_client)
    else:
        return _call_openai_compatible(provider_cfg, api_key, prompt, http_client)


def _call_anthropic(cfg: dict, api_key: str, prompt: str, http_client) -> list[SemanticDocument]:
    """Call Anthropic Messages API."""
    body = json.dumps({
        "model": cfg["model"],
        "max_tokens": 2000,
        "temperature": 0.0,
        "system": (
            "You are a code knowledge graph extractor. Output ONLY valid JSON — "
            "no markdown, no explanation. Your entire response must parse as JSON."
        ),
        "messages": [{"role": "user", "content": prompt}],
    })

    conn = http_client.HTTPSConnection(cfg["host"], timeout=30)
    try:
        conn.request("POST", cfg["path"], body=body, headers={
            cfg["auth_header"]: api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        })
        resp = conn.getresponse()
        if resp.status != 200:
            raise RuntimeError(f"API returned {resp.status}: {resp.read().decode()[:200]}")
        data = json.loads(resp.read().decode())
    finally:
        conn.close()

    content = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            content += block.get("text", "")

    return _parse_llm_response(content)


def _call_openai_compatible(cfg: dict, api_key: str, prompt: str, http_client) -> list[SemanticDocument]:
    """Call OpenAI-compatible Chat Completions API (DeepSeek, OpenAI, etc.)."""
    auth_value = cfg.get("auth_prefix", "") + api_key

    system_prompt = (
        "You are a code knowledge graph extractor. Output ONLY valid JSON — "
        "no markdown, no explanation. Your entire response must parse as JSON."
    )

    body = json.dumps({
        "model": cfg["model"],
        "max_tokens": 2000,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    })

    conn = http_client.HTTPSConnection(cfg["host"], timeout=30)
    try:
        conn.request("POST", cfg["path"], body=body, headers={
            cfg["auth_header"]: auth_value,
            "content-type": "application/json",
        })
        resp = conn.getresponse()
        if resp.status != 200:
            raise RuntimeError(f"API returned {resp.status}: {resp.read().decode()[:200]}")
        data = json.loads(resp.read().decode())
    finally:
        conn.close()

    # OpenAI format: choices[0].message.content
    content = ""
    choices = data.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", "")

    return _parse_llm_response(content)


def _build_extraction_prompt(text: str) -> str:
    """Build the structured extraction prompt for the LLM."""
    return f"""Analyze this conversation about code. Extract structured semantic annotations.
Output a JSON object with these fields:

- "annotations": array of {{"symbol": "...", "kind": "function|method|class|interface|type|variable|module", "summary": "...", "design_intent": "...", "pitfalls": "..."}}
- "design_decisions": array of strings (architectural choices discussed)
- "module_summaries": array of {{"file": "...", "summary": "..."}}

Rules:
- Only extract about symbols actually mentioned or discussed
- "summary" describes what the symbol does
- "design_intent" captures WHY it was built that way
- "pitfalls" captures bugs, edge cases, gotchas mentioned
- Use empty string "" for unknown fields, never omit them
- If nothing relevant found, return empty arrays

Conversation text:
{text}"""


def _parse_llm_response(content: str) -> list[SemanticDocument]:
    """Parse the LLM's JSON response into SemanticDocument objects."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:]) if len(lines) > 1 else content
    if content.endswith("```"):
        content = content[:-3].strip()

    data = json.loads(content)

    docs: list[SemanticDocument] = []

    for ann_data in data.get("annotations", []):
        doc = SemanticDocument(
            file=ann_data.get("file", "conversation-extract"),
            source="llm-extract",
        )
        doc.annotations.append(Annotation(
            symbol=ann_data.get("symbol", ""),
            kind=ann_data.get("kind", "function"),
            summary=ann_data.get("summary", ""),
            design_intent=ann_data.get("design_intent", ""),
            pitfalls=ann_data.get("pitfalls", ""),
        ))
        docs.append(doc)

    for decision in data.get("design_decisions", []):
        doc = SemanticDocument(
            file="conversation-extract",
            source="llm-extract",
            module_summary=decision[:500] if isinstance(decision, str) else "",
        )
        docs.append(doc)

    for mod_data in data.get("module_summaries", []):
        doc = SemanticDocument(
            file=mod_data.get("file", "conversation-extract"),
            source="llm-extract",
            module_summary=mod_data.get("summary", "")[:500],
        )
        docs.append(doc)

    return docs


# ── Tier 3: regex-only fallback ──────────────────────────────────────────

def _load_conversation_text(path: Path) -> str:
    """Load and extract text from a conversation file."""
    with open(path) as f:
        data = json.load(f)
    return _extract_text(data)


def _extract_with_regex(text: str) -> list[SemanticDocument]:
    """Extract annotations using heuristic regex patterns (fallback)."""
    docs: list[SemanticDocument] = []

    patterns = {
        "summary": [
            r'(?:函数|方法|function|method)\s+`?(\w+)`?\s*(?:是|用于|does|handles|returns|计算|处理|负责)\s*(.+?)(?:\.|\n|$)',
            r'(?:类|class)\s+`?(\w+)`?\s*(?:是|用于|represents|管理|负责|handles)\s*(.+?)(?:\.|\n|$)',
            r'`(\w+)`\s+(?:is|是一个|用于|handles|负责)\s+(.+?)(?:\.|\n|$)',
        ],
        "design_intent": [
            r'(?:设计|design|架构|architecture|pattern|模式).*?[:：]\s*(.+?)(?:\.|\n\n)',
            r'(?:决定|decision|trade.?off).*?[:：]\s*(.+?)(?:\.|\n\n)',
            r'(?:should|应该|must|必须|推荐|建议)\s+(?:use|使用|采用)\s+(.+?)(?:\.|\n|$)',
        ],
        "pitfalls": [
            r'(?:注意|warning|小心|caution|bug|问题|issue|陷阱|pitfall).*?[:：]\s*(.+?)(?:\.|\n\n)',
            r'(?:don\'t|do not|不要|避免|avoid)\s+(.+?)(?:\.|\n|$)',
            r'(?:TODO|FIXME|HACK|BUG|XXX)[:：]?\s*(.+?)(?:\n|$)',
        ],
    }

    for ann_type, type_patterns in patterns.items():
        for pattern in type_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                symbol_name = match.group(1) if match.lastindex and match.lastindex >= 1 else ""
                description = match.group(match.lastindex) if match.lastindex else match.group(0)
                description = description.strip()[:500]

                doc = SemanticDocument(
                    file="conversation-extract",
                    source="conversation-extract",
                )
                if ann_type == "summary":
                    doc.annotations.append(Annotation(
                        symbol=symbol_name,
                        kind="function",
                        summary=description,
                        design_intent="",
                        pitfalls="",
                    ))
                elif ann_type == "design_intent":
                    doc.module_summary = description
                elif ann_type == "pitfalls":
                    doc.annotations.append(Annotation(
                        symbol=symbol_name,
                        kind="unknown",
                        summary="",
                        design_intent="",
                        pitfalls=description,
                    ))
                docs.append(doc)

    return docs


def _extract_text(data) -> str:
    """Extract conversation text from various JSON structures.

    Handles Claude Code export format and generic chat formats.
    """
    if isinstance(data, str):
        return data

    if isinstance(data, dict):
        for key in ("messages", "conversation", "chat", "content", "text"):
            if key in data:
                return _extract_text(data[key])

        text_parts = []
        for _key, value in data.items():
            if isinstance(value, str) and len(value) > 50:
                text_parts.append(value)
            elif isinstance(value, (dict, list)):
                text_parts.append(_extract_text(value))
        return "\n".join(text_parts)

    if isinstance(data, list):
        texts = []
        for item in data:
            if isinstance(item, dict):
                if "content" in item:
                    if isinstance(item["content"], str):
                        texts.append(item["content"])
                    elif isinstance(item["content"], list):
                        for block in item["content"]:
                            if isinstance(block, dict) and "text" in block:
                                texts.append(block["text"])
                elif "text" in item:
                    texts.append(item["text"])
                elif "message" in item:
                    texts.append(str(item["message"]))
            elif isinstance(item, str):
                texts.append(item)
        return "\n".join(texts)

    return str(data)
