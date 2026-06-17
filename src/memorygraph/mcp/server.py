"""MCP server — exposes memorygraph tools via Model Context Protocol."""
import json
import logging
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from memorygraph.semantic.store import SemanticStore
from memorygraph.storage import create_storage_manager
from memorygraph.storage.backend import create_semantic_store

logger = logging.getLogger(__name__)


def _lookup_semantic_for_file(
    sem_store: SemanticStore, file_path: str
) -> dict | None:
    """Look up semantic data for a file and return a serializable dict."""
    doc = sem_store.load(file_path)
    if doc is None:
        return None
    return {
        "file": doc.file,
        "module_summary": doc.module_summary,
        "annotations": [
            {
                "symbol": a.symbol,
                "kind": a.kind,
                "summary": a.summary,
                "design_intent": a.design_intent,
                "pitfalls": a.pitfalls,
            }
            for a in doc.annotations
        ],
        "unknowns": [
            {"symbol": u.symbol, "question": u.question, "context": u.context}
            for u in doc.unknowns
        ],
        "insights": [
            {"insight": i.insight, "related_symbols": i.related_symbols}
            for i in doc.insights
        ],
    }


def auto_sync_on_startup(project_root: str) -> dict:
    """Check index freshness and auto-repair stale entries.

    Called at MCP/server startup. Compares file hashes against stored
    hashes and re-indexes only changed files. Controlled by the
    ``MEMORYGRAPH_AUTO_SYNC`` env var (default: true).

    Returns a dict with sync statistics, or ``{"skipped": True}``
    when auto-sync is disabled.
    """
    if os.environ.get("MEMORYGRAPH_AUTO_SYNC", "true").lower() in ("0", "false", "no"):
        logger.info("Auto-sync disabled via MEMORYGRAPH_AUTO_SYNC")
        return {"skipped": True, "reason": "disabled by env"}

    try:
        from pathlib import Path

        from memorygraph.cli.shared import _collect_files, _compute_hash
        from memorygraph.parsing.batch import ParallelParser
        from memorygraph.parsing.registry import LanguageRegistry

        mgr = create_storage_manager(project_root)
        mgr.initialize()
        registry = LanguageRegistry()

        files = _collect_files(project_root, registry)
        if not files:
            mgr.close()
            return {"skipped": True, "reason": "no source files found"}

        new_files, changed_files, unchanged = [], [], 0
        for fpath in files:
            current_hash = _compute_hash(fpath)
            stored_hash = mgr.get_file_hash(fpath)
            if stored_hash is None:
                new_files.append(fpath)
            elif current_hash != stored_hash:
                changed_files.append(fpath)
            else:
                unchanged += 1

        to_parse = new_files + changed_files
        if not to_parse:
            mgr.close()
            return {
                "status": "fresh",
                "total_files": len(files),
                "new": 0, "changed": 0, "unchanged": unchanged,
            }

        parser = ParallelParser(registry)
        results = parser.parse_files(
            [Path(f) for f in to_parse], resolve_symbols=True
        )
        synced = mgr.bulk_upsert(results)

        # L5-6: incremental semantic re-analysis for changed/new files
        analyzed = 0
        try:
            from memorygraph.cli.shared import _analyze_files
            analyzed = _analyze_files(project_root, to_parse)
        except Exception:
            logger.debug("Incremental semantic analysis skipped", exc_info=True)

        mgr.close()

        logger.info(
            "Auto-sync: %d new + %d changed → %d re-indexed, %d re-analyzed (%d unchanged)",
            len(new_files), len(changed_files), synced, analyzed, unchanged,
        )
        return {
            "status": "synced",
            "total_files": len(files),
            "new": len(new_files),
            "changed": len(changed_files),
            "unchanged": unchanged,
            "synced_count": synced,
            "analyzed_count": analyzed,
        }
    except Exception:
        logger.exception("Auto-sync failed, continuing with existing index")
        return {"status": "error", "message": "auto-sync failed, using existing index"}


def create_memorygraph_server(project_root: str = ".") -> Server:
    """Create and configure the MCP server with all memorygraph tools."""
    from pathlib import Path

    server = Server("memorygraph")

    # L5-2: Auto-check index freshness on startup
    _sync_result: dict = auto_sync_on_startup(project_root)

    # L5-4: query log for self-growing graph
    _query_log_path = Path(project_root) / ".memorygraph" / "queries.jsonl"
    _query_log_path.parent.mkdir(parents=True, exist_ok=True)

    def _log_query(query: str, symbols: list[str], tool: str) -> None:
        """Append a query record to the query log for hotness tracking."""
        import time
        try:
            with open(_query_log_path, "a") as f:
                f.write(json.dumps({
                    "ts": time.time(),
                    "tool": tool,
                    "query": query[:200],
                    "symbols": symbols[:20],
                }) + "\n")
        except Exception:
            pass  # logging failure should never block a query

    def _get_hot_symbols(limit: int = 20) -> list[dict]:
        """Aggregate query logs to find most frequently accessed symbols."""
        from collections import Counter
        if not _query_log_path.exists():
            return []
        sym_counter: Counter = Counter()
        try:
            for line in _query_log_path.read_text().splitlines()[:1000]:
                try:
                    record = json.loads(line)
                    for sym in record.get("symbols", []):
                        sym_counter[sym] += 1
                except (json.JSONDecodeError, KeyError):
                    continue
        except Exception:
            return []
        return [
            {"symbol": sym, "access_count": count}
            for sym, count in sym_counter.most_common(limit)
        ]

    mgr = create_storage_manager(project_root)
    mgr.initialize()
    sem_store = create_semantic_store(project_root)

    # ── static graph helpers ──────────────────────────────────────────

    def _search_tool(query: str, limit: int = 10) -> list[dict]:
        results = mgr.search(query, limit=limit)
        symbols = [r.get("qualified_name", "") for r in results]
        _log_query(query, symbols, "search")
        return results

    def _get_callers(symbol: str, depth: int = 1,
                     file_path: str | None = None) -> list[dict]:
        return mgr.get_callers(
            symbol, depth=min(depth, 5), file_path=file_path
        )

    def _get_callees(symbol: str, depth: int = 1,
                     file_path: str | None = None) -> list[dict]:
        return mgr.get_callees(
            symbol, depth=min(depth, 5), file_path=file_path
        )

    def _get_impact(symbol: str, depth: int = 3) -> list[dict]:
        return mgr.get_impact(symbol, max_depth=min(depth, 5))

    def _get_node(symbol: str,
                  file_path: str | None = None) -> dict | None:
        return mgr.get_node(symbol, file_path=file_path)

    def _semantic_search(query: str, limit: int = 10, hybrid: bool = True) -> list[dict]:
        """Semantic search using vector embeddings when available, falls back to FTS."""
        from memorygraph.semantic.embeddings import EmbeddingGenerator
        gen = EmbeddingGenerator()
        if gen.is_available:
            try:
                query_vec = gen.generate("query", query)
                if query_vec is not None:
                    fts_results = mgr.semantic_search(query, limit=limit * 2) if hybrid else []
                    # Load stored embeddings
                    conn = mgr.get_conn()
                    rows = conn.execute(
                        "SELECT symbol_name, qualified_name, signature, file_path, "
                        "kind, e.embedding FROM fts_index f "
                        "JOIN embeddings e ON e.qualified_name = f.qualified_name "
                        "AND e.file_path = f.file_path"
                    ).fetchall()
                    import numpy as np
                    stored = []
                    for row in rows:
                        blob = row[5]
                        if blob and len(blob) == 384 * 4:
                            vec = np.frombuffer(blob, dtype=np.float32)
                            stored.append({
                                "name": row[0], "qualified_name": row[1],
                                "signature": row[2], "file_path": row[3],
                                "kind": row[4], "embedding": vec,
                            })
                    if stored:
                        vec_results = gen.search(query_vec, stored, top_k=limit)
                        if hybrid and fts_results:
                            return gen.hybrid_search(query_vec, fts_results, vec_results)
                        return vec_results
            except Exception:
                logger.exception("Vector search failed, falling back to FTS")
        return mgr.semantic_search(query, limit=limit)

    def _context(task: str, limit: int = 10) -> dict:
        results = mgr.semantic_search(task, limit=limit)
        entry_points = []
        related = []
        # Collect unique files to attach semantic data
        files_with_semantic: dict[str, dict] = {}

        for r in results:
            entry_points.append({
                "symbol": r["qualified_name"],
                "kind": r["kind"],
                "file": r["file_path"],
                "signature": r.get("signature", ""),
                "relevance": r.get("rank", 0),
            })
            callers = mgr.get_callers(r["qualified_name"], depth=1)
            callees = mgr.get_callees(r["qualified_name"], depth=1)
            related.append({
                "symbol": r["qualified_name"],
                "kind": r["kind"],
                "file": r["file_path"],
                "callers": [c["source"] for c in callers],
                "callees": [c["target"] for c in callees],
            })
            # Attach semantic data for this file if available
            if r["file_path"] not in files_with_semantic:
                sem = _lookup_semantic_for_file(sem_store, r["file_path"])
                if sem:
                    files_with_semantic[r["file_path"]] = sem

        symbols_queried = [r["qualified_name"] for r in results]
        _log_query(task, symbols_queried, "context")

        # L5-4: enrich with hot symbols from past interactions
        hot = _get_hot_symbols(10)
        result = {
            "task": task,
            "entry_points": entry_points,
            "related": related,
        }
        if files_with_semantic:
            result["semantic_context"] = list(files_with_semantic.values())
        if hot:
            result["hot_symbols"] = hot
        return result

    def _diff(diff_text: str) -> dict:
        """Analyze a git diff and return affected symbols."""
        import os
        root = os.path.abspath(project_root)

        changed_files = set()
        for line in diff_text.split("\n"):
            # Parse git diff headers: "--- a/path" / "+++ b/path"
            if line.startswith("+++ b/"):
                path = line[6:]  # strip "+++ b/" (6 chars)
                if path != "/dev/null":
                    changed_files.add(path)
            elif line.startswith("--- a/"):
                path = line[6:]  # strip "--- a/" (6 chars)
                if path != "/dev/null":
                    changed_files.add(path)

        all_affected: dict[str, list] = {}
        for fpath in changed_files:
            # Resolve relative path to absolute (DB stores absolute paths)
            if not os.path.isabs(fpath):
                abs_path = os.path.normpath(os.path.join(root, fpath))
            else:
                abs_path = fpath
            symbols = mgr.get_symbols_for_file(abs_path)
            if not symbols:
                # Try relative path as fallback
                symbols = mgr.get_symbols_for_file(fpath)
            for sym in symbols:
                qn = sym["qualified_name"]
                impacted = mgr.get_impact(qn, max_depth=3)
                if qn not in all_affected:
                    all_affected[qn] = []
                for imp in impacted:
                    all_affected[qn].append(imp["target"])

        return {
            "changed_files": sorted(changed_files),
            "affected_symbols": list(all_affected.keys()),
            "call_chains": all_affected,
        }

    # ── semantic helpers ──────────────────────────────────────────────

    def _semantic_context(file_path: str = "", symbol: str = "") -> dict:
        """Return semantic context for a file or symbol."""
        results: dict[str, Any] = {}
        files_to_check = []

        if file_path:
            files_to_check.append(file_path)
        elif symbol:
            node = mgr.get_node(symbol)
            if node and node.get("file_path"):
                files_to_check.append(node["file_path"])

        if not files_to_check:
            # Return all semantic docs
            all_docs = sem_store.load_all()
            results["documents"] = [
                {
                    "file": d.file,
                    "module_summary": d.module_summary,
                    "annotation_count": len(d.annotations),
                    "unknown_count": len(d.unknowns),
                    "insight_count": len(d.insights),
                }
                for d in all_docs
            ]
            return results

        for fp in files_to_check:
            sem = _lookup_semantic_for_file(sem_store, fp)
            if sem:
                results[fp] = sem

        return results

    def _annotations(file_path: str = "", symbol: str = "") -> dict:
        """Return annotations, optionally filtered by file or symbol."""
        all_docs = sem_store.load_all()
        result: dict[str, list] = {"annotations": []}

        for doc in all_docs:
            if file_path and doc.file != file_path:
                continue
            for ann in doc.annotations:
                if symbol and ann.symbol != symbol:
                    continue
                result["annotations"].append({
                    "file": doc.file,
                    "symbol": ann.symbol,
                    "kind": ann.kind,
                    "summary": ann.summary,
                    "design_intent": ann.design_intent,
                    "pitfalls": ann.pitfalls,
                })

        return result

    def _unknowns(limit: int = 20) -> dict:
        """Return open unknowns, sorted by reference frequency."""
        all_docs = sem_store.load_all()
        items: list[dict[str, Any]] = []

        # Count symbol references to sort by importance
        ref_counts: dict[str, int] = {}
        for doc in all_docs:
            for unk in doc.unknowns:
                key = f"{doc.file}:{unk.symbol}"
                if key not in ref_counts:
                    # Count how many times this symbol is referenced
                    callers = mgr.get_callers(unk.symbol, depth=1)
                    callees = mgr.get_callees(unk.symbol, depth=1)
                    ref_counts[key] = len(callers) + len(callees)

        for doc in all_docs:
            for unk in doc.unknowns:
                key = f"{doc.file}:{unk.symbol}"
                items.append({
                    "file": doc.file,
                    "symbol": unk.symbol,
                    "question": unk.question,
                    "context": unk.context,
                    "reference_count": ref_counts.get(key, 0),
                })

        items.sort(key=lambda x: x["reference_count"], reverse=True)
        return {"unknowns": items[:limit]}

    def _insights(limit: int = 20) -> dict:
        """Return design insights across all documented modules."""
        all_docs = sem_store.load_all()
        items: list[dict[str, Any]] = []
        for doc in all_docs:
            for ins in doc.insights:
                items.append({
                    "file": doc.file,
                    "insight": ins.insight,
                    "related_symbols": ins.related_symbols,
                })
        return {"insights": items[:limit]}

    # ── semantic write-back handlers (L5: "learn while using") ─────────

    def _annotate_symbol(file_path: str, symbol: str, kind: str = "function",
                         summary: str = "", design_intent: str = "",
                         pitfalls: str = "") -> dict:
        """Write an annotation for a symbol and persist to semantic store.

        This is the core of the "learn while using" loop — Claude Code calls
        this after understanding a symbol's purpose, design, or pitfalls.
        """
        from memorygraph.semantic.models import Annotation, SemanticDocument

        doc = sem_store.load(file_path)
        if doc is None:
            doc = SemanticDocument(file=file_path, source="mcp")

        ann = Annotation(
            symbol=symbol,
            kind=kind,
            summary=summary,
            design_intent=design_intent,
            pitfalls=pitfalls,
        )
        # Remove existing annotation for this symbol (upsert)
        doc.annotations = [a for a in doc.annotations if a.symbol != symbol]
        doc.annotations.append(ann)

        sem_store.save(doc)
        logger.info("Annotation written for %s in %s via MCP", symbol, file_path)
        return {"status": "ok", "symbol": symbol, "file": file_path}

    def _add_insight(insight_text: str, related_symbols: list[str] | None = None,
                     file_path: str = "") -> dict:
        """Write a design insight or architectural observation.

        Insights capture cross-cutting observations that aren't tied to a
        single symbol — patterns, trade-offs, conventions.
        """
        from memorygraph.semantic.models import Insight, SemanticDocument

        if not file_path:
            return {"status": "error", "message": "file_path is required for insights"}
        if not insight_text.strip():
            return {"status": "error", "message": "insight text is required"}

        doc = sem_store.load(file_path)
        if doc is None:
            doc = SemanticDocument(file=file_path, source="mcp")

        insight = Insight(
            insight=insight_text,
            related_symbols=related_symbols or [],
        )
        doc.insights.append(insight)

        sem_store.save(doc)
        logger.info("Insight written for %s via MCP", file_path)
        return {"status": "ok", "file": file_path, "insight": insight_text[:80] + "..."}

    def _add_unknown(symbol: str, question: str, context: str = "",
                     file_path: str = "") -> dict:
        """Record an open question or unclear area about a symbol.

        Unknowns track what we still need to figure out — future Claude Code
        sessions can prioritize resolving them.
        """
        from memorygraph.semantic.models import SemanticDocument, Unknown

        if not file_path:
            return {"status": "error", "message": "file_path is required for unknowns"}
        if not symbol.strip():
            return {"status": "error", "message": "symbol is required for unknowns"}
        if not question.strip():
            return {"status": "error", "message": "question is required for unknowns"}

        doc = sem_store.load(file_path)
        if doc is None:
            doc = SemanticDocument(file=file_path, source="mcp")

        unknown = Unknown(
            symbol=symbol,
            question=question,
            context=context,
        )
        doc.unknowns.append(unknown)

        sem_store.save(doc)
        logger.info("Unknown recorded for %s in %s via MCP", symbol, file_path)
        return {"status": "ok", "symbol": symbol, "file": file_path}

    # ── L5-2: index freshness helpers ──────────────────────────────────

    def _check_freshness() -> dict:
        """Return the startup auto-sync result + current index stats."""
        stats = mgr.stats()
        return {
            "startup_sync": _sync_result,
            "current_stats": {
                "files": stats["file_count"],
                "symbols": stats["symbol_count"],
                "edges": stats["edge_count"],
                "last_updated": stats.get("last_updated", "unknown"),
            },
        }

    def _auto_sync() -> dict:
        """Manually trigger an index freshness check and repair."""
        nonlocal _sync_result
        try:
            from pathlib import Path

            from memorygraph.cli.shared import _collect_files, _compute_hash
            from memorygraph.parsing.batch import ParallelParser
            from memorygraph.parsing.registry import LanguageRegistry

            registry = LanguageRegistry()
            files = _collect_files(project_root, registry)
            if not files:
                return {"status": "no_files"}

            new_files, changed_files, unchanged = [], [], 0
            for fpath in files:
                current_hash = _compute_hash(fpath)
                stored_hash = mgr.get_file_hash(fpath)
                if stored_hash is None:
                    new_files.append(fpath)
                elif current_hash != stored_hash:
                    changed_files.append(fpath)
                else:
                    unchanged += 1

            to_parse = new_files + changed_files
            if not to_parse:
                return {
                    "status": "fresh",
                    "total_files": len(files),
                    "new": 0, "changed": 0, "unchanged": unchanged,
                }

            parser = ParallelParser(registry)
            results = parser.parse_files(
                [Path(f) for f in to_parse], resolve_symbols=True,
            )
            synced = mgr.bulk_upsert(results)

            _sync_result = {
                "status": "synced",
                "total_files": len(files),
                "new": len(new_files),
                "changed": len(changed_files),
                "unchanged": unchanged,
                "synced_count": synced,
            }
            return _sync_result
        except Exception as e:
            logger.exception("Manual auto-sync failed")
            return {"status": "error", "message": str(e)}

    # ── L5-3: conversation → semantic extraction ─────────────────────

    def _ingest_conversation(conversation_text: str,
                             file_path: str = "") -> dict:
        """Extract semantic annotations from a conversation transcript.

        Runs regex heuristics to find symbol descriptions, design decisions,
        and pitfalls mentioned in the conversation. Saves extracted
        annotations to the semantic store.
        """
        from pathlib import Path

        from memorygraph.semantic.conversation import extract_from_conversation

        # Save conversation to .memorygraph/conversations/ for audit trail
        conv_dir = Path(project_root) / ".memorygraph" / "conversations"
        conv_dir.mkdir(parents=True, exist_ok=True)
        import time
        conv_file = conv_dir / f"conv-{int(time.time())}.json"
        conv_file.write_text(json.dumps({
            "timestamp": time.time(),
            "file_path": file_path,
            "text": conversation_text,
        }, indent=2))

        # Extract semantics using existing heuristics
        try:
            docs = extract_from_conversation(str(conv_file))
        except Exception as e:
            logger.exception("Conversation extraction failed")
            return {"status": "error", "message": str(e)}

        # Save extracted documents to semantic store
        saved = 0
        for doc in docs:
            if doc.file == "conversation-extract" and file_path:
                doc.file = file_path
            sem_store.save(doc)
            saved += 1

        logger.info(
            "Conversation ingested: %d annotations extracted from %s",
            saved, conv_file,
        )
        return {
            "status": "ok",
            "conversation_file": str(conv_file),
            "extracted_documents": saved,
        }

    def _save_conversation_context(conversation_json: str) -> dict:
        """Save a conversation transcript to the conversation store.

        The transcript is saved to .memorygraph/conversations/ for later
        batch ingestion or analysis.
        """
        from pathlib import Path
        conv_dir = Path(project_root) / ".memorygraph" / "conversations"
        conv_dir.mkdir(parents=True, exist_ok=True)
        import time
        conv_file = conv_dir / f"conv-{int(time.time())}.json"

        try:
            data = json.loads(conversation_json)
        except json.JSONDecodeError:
            data = {"text": conversation_json}

        data["saved_at"] = time.time()
        conv_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info("Conversation saved: %s", conv_file)
        return {"status": "ok", "file": str(conv_file)}

    # ── tool registration ─────────────────────────────────────────────

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="memorygraph_search",
                description="Search for symbols by name. Returns matching symbols with locations.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Symbol name or partial name to search"},
                        "limit": {"type": "integer", "description": "Maximum results (default: 10)"},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="memorygraph_callers",
                description="List functions that call a given symbol. Optionally filter by file_path to disambiguate same-named symbols.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Name of the symbol to find callers for"},
                        "depth": {"type": "integer", "description": "How many levels up to traverse (default: 1, max: 5)"},
                        "file_path": {"type": "string", "description": "Optional file path to disambiguate same-named symbols"},
                    },
                    "required": ["symbol"],
                },
            ),
            Tool(
                name="memorygraph_callees",
                description="List functions that a given symbol calls. Optionally filter by file_path to disambiguate same-named symbols.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Name of the symbol to find callees for"},
                        "depth": {"type": "integer", "description": "How many levels down to traverse (default: 1, max: 5)"},
                        "file_path": {"type": "string", "description": "Optional file path to disambiguate same-named symbols"},
                    },
                    "required": ["symbol"],
                },
            ),
            Tool(
                name="memorygraph_impact",
                description="Analyze the impact of changing a symbol. Returns all downstream call chains.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Name of the symbol to analyze impact for"},
                        "depth": {"type": "integer", "description": "How deep to traverse (default: 3, max: 5)"},
                    },
                    "required": ["symbol"],
                },
            ),
            Tool(
                name="memorygraph_node",
                description="Get detailed information about a specific symbol. Optionally filter by file_path to disambiguate same-named symbols.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Qualified name of the symbol"},
                        "file_path": {"type": "string", "description": "Optional file path to disambiguate same-named symbols"},
                    },
                    "required": ["symbol"],
                },
            ),
            Tool(
                name="memorygraph_context",
                description="Find relevant symbols and entry points for a task description. Returns entry points with callers and callees context. Automatically attaches semantic data when available.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "Task description in natural language"},
                        "limit": {"type": "integer", "description": "Maximum results (default: 10)"},
                    },
                    "required": ["task"],
                },
            ),
            Tool(
                name="memorygraph_diff",
                description="Analyze a git diff and return affected symbols and call chains.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "diff": {"type": "string", "description": "Git diff text to analyze"},
                    },
                    "required": ["diff"],
                },
            ),
            Tool(
                name="memorygraph_semantic_context",
                description="Get semantic context (annotations, insights, unknowns) for a file or symbol.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file": {"type": "string", "description": "File path to get semantic context for"},
                        "symbol": {"type": "string", "description": "Symbol name to get semantic context for"},
                    },
                },
            ),
            Tool(
                name="memorygraph_annotations",
                description="Get human-written annotations for symbols, optionally filtered by file or symbol name.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file": {"type": "string", "description": "Filter annotations by file path"},
                        "symbol": {"type": "string", "description": "Filter annotations by symbol name"},
                    },
                },
            ),
            Tool(
                name="memorygraph_unknowns",
                description="Get open questions and unclear areas, sorted by reference frequency.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Maximum results (default: 20)"},
                    },
                },
            ),
            Tool(
                name="memorygraph_insights",
                description="Get design insights and architectural observations from documented modules.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Maximum results (default: 20)"},
                    },
                },
            ),
            Tool(
                name="memorygraph_semantic_search",
                description="Semantic search using vector embeddings (all-MiniLM-L6-v2). Falls back to FTS if model unavailable.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Natural language search query"},
                        "limit": {"type": "integer", "description": "Maximum results (default: 10)"},
                        "hybrid": {"type": "boolean", "description": "Use hybrid FTS+vector search (default: true)"},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="memorygraph_annotate",
                description="Write an annotation for a symbol. Use this after understanding what a function/method/class does — record its purpose, design intent, and pitfalls. This builds up the semantic knowledge graph over time (the 'learn while using' loop).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "File path containing the symbol (relative to project root)"},
                        "symbol": {"type": "string", "description": "Symbol name (unqualified, e.g. 'calculate_total')"},
                        "kind": {"type": "string", "description": "Symbol kind: function, method, class, interface, type, variable (default: function)"},
                        "summary": {"type": "string", "description": "Brief summary of what the symbol does (1-2 sentences)"},
                        "design_intent": {"type": "string", "description": "Why was it designed this way? Trade-offs, rationale"},
                        "pitfalls": {"type": "string", "description": "Edge cases, known bugs, things to watch out for"},
                    },
                    "required": ["file_path", "symbol", "summary"],
                },
            ),
            Tool(
                name="memorygraph_add_insight",
                description="Record a design insight or architectural observation about the codebase. Use this for cross-cutting observations that aren't tied to a single symbol — patterns, trade-offs, conventions, why something was built a certain way.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "File path to attach the insight to (relative to project root)"},
                        "insight": {"type": "string", "description": "The insight or observation"},
                        "related_symbols": {"type": "array", "items": {"type": "string"}, "description": "Symbols this insight relates to"},
                    },
                    "required": ["file_path", "insight"],
                },
            ),
            Tool(
                name="memorygraph_add_unknown",
                description="Record an open question or unclear area about a symbol. Unknowns track what we still need to figure out — future sessions can prioritize resolving them. This builds the 'known unknowns' of the codebase.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "File path containing the symbol (relative to project root)"},
                        "symbol": {"type": "string", "description": "Symbol name this question is about"},
                        "question": {"type": "string", "description": "The open question or unclear point"},
                        "context": {"type": "string", "description": "Additional context — what triggered this question?"},
                    },
                    "required": ["file_path", "symbol", "question"],
                },
            ),
            Tool(
                name="memorygraph_check_freshness",
                description="Check whether the code index is up-to-date. Reports file counts (new, changed, unchanged) and whether an auto-sync ran at startup. Use this to verify the knowledge graph reflects the latest code before making decisions based on it.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="memorygraph_auto_sync",
                description="Manually trigger an index freshness check and repair. Scans source files, compares hashes, and re-indexes any changed or new files. Use this after making code changes to ensure the knowledge graph is current.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="memorygraph_ingest_conversation",
                description="Extract semantic annotations from a Claude Code conversation transcript. Uses heuristics to find symbol descriptions, design decisions, and pitfalls mentioned in the conversation, then saves them to the semantic knowledge graph. This turns conversation insights into structured, queryable knowledge.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The conversation transcript text to extract semantics from"},
                        "file_path": {"type": "string", "description": "Optional: associate extracted annotations with a specific file"},
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="memorygraph_save_conversation",
                description="Save a conversation transcript to the conversation store (.memorygraph/conversations/) for later batch ingestion or analysis. Conversations accumulate over time and can be bulk-ingested with memorygraph_ingest_conversation.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The conversation transcript (JSON or plain text) to save"},
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="memorygraph_hot_symbols",
                description="Get the most frequently accessed symbols across all past queries. This shows which parts of the codebase are 'hot' — frequently explored or modified. The more the graph is used, the more accurate this becomes. (L5-4: self-growing graph)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Maximum results (default: 20)"},
                    },
                },
            ),
        ]

    def _require_arg(arguments: dict, *keys: str) -> dict | None:
        """Return error dict if any required key is missing, else None.

        Only checks for key presence — empty strings are valid inputs
        (e.g. empty diff, empty query → empty results).
        """
        for key in keys:
            if key not in arguments:
                return {"status": "error", "message": f"'{key}' is required"}
        return None

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        def _err_response(msg: str) -> list[TextContent]:
            return [TextContent(type="text",
                               text=json.dumps({"status": "error", "message": msg}, indent=2))]

        try:
            result: Any = None
            if name == "memorygraph_search":
                err = _require_arg(arguments, "query")
                if err:
                    return _err_response(err["message"])
                result = _search_tool(
                    query=arguments.get("query", ""),
                    limit=arguments.get("limit", 10),
                )
            elif name == "memorygraph_callers":
                err = _require_arg(arguments, "symbol")
                if err:
                    return _err_response(err["message"])
                result = _get_callers(
                    symbol=arguments.get("symbol", ""),
                    depth=arguments.get("depth", 1),
                    file_path=arguments.get("file_path"),
                )
            elif name == "memorygraph_callees":
                err = _require_arg(arguments, "symbol")
                if err:
                    return _err_response(err["message"])
                result = _get_callees(
                    symbol=arguments.get("symbol", ""),
                    depth=arguments.get("depth", 1),
                    file_path=arguments.get("file_path"),
                )
            elif name == "memorygraph_impact":
                err = _require_arg(arguments, "symbol")
                if err:
                    return _err_response(err["message"])
                result = _get_impact(
                    symbol=arguments.get("symbol", ""),
                    depth=arguments.get("depth", 3),
                )
            elif name == "memorygraph_node":
                err = _require_arg(arguments, "symbol")
                if err:
                    return _err_response(err["message"])
                node = _get_node(
                    symbol=arguments.get("symbol", ""),
                    file_path=arguments.get("file_path"),
                )
                result = {"found": node is not None, "node": node}
            elif name == "memorygraph_context":
                err = _require_arg(arguments, "task")
                if err:
                    return _err_response(err["message"])
                result = _context(
                    task=arguments.get("task", ""),
                    limit=arguments.get("limit", 10),
                )
            elif name == "memorygraph_diff":
                err = _require_arg(arguments, "diff")
                if err:
                    return _err_response(err["message"])
                result = _diff(diff_text=arguments.get("diff", ""))
            elif name == "memorygraph_semantic_context":
                result = _semantic_context(
                    file_path=arguments.get("file", ""),
                    symbol=arguments.get("symbol", ""),
                )
            elif name == "memorygraph_annotations":
                result = _annotations(
                    file_path=arguments.get("file", ""),
                    symbol=arguments.get("symbol", ""),
                )
            elif name == "memorygraph_unknowns":
                result = _unknowns(
                    limit=arguments.get("limit", 20),
                )
            elif name == "memorygraph_insights":
                result = _insights(
                    limit=arguments.get("limit", 20),
                )
            elif name == "memorygraph_semantic_search":
                err = _require_arg(arguments, "query")
                if err:
                    return _err_response(err["message"])
                result = _semantic_search(
                    query=arguments.get("query", ""),
                    limit=arguments.get("limit", 10),
                    hybrid=arguments.get("hybrid", True),
                )
            elif name == "memorygraph_annotate":
                err = _require_arg(arguments, "file_path", "symbol")
                if err:
                    return _err_response(err["message"])
                result = _annotate_symbol(
                    file_path=arguments.get("file_path", ""),
                    symbol=arguments.get("symbol", ""),
                    kind=arguments.get("kind", "function"),
                    summary=arguments.get("summary", ""),
                    design_intent=arguments.get("design_intent", ""),
                    pitfalls=arguments.get("pitfalls", ""),
                )
            elif name == "memorygraph_add_insight":
                result = _add_insight(
                    insight_text=arguments.get("insight", ""),
                    related_symbols=arguments.get("related_symbols"),
                    file_path=arguments.get("file_path", ""),
                )
            elif name == "memorygraph_add_unknown":
                result = _add_unknown(
                    symbol=arguments.get("symbol", ""),
                    question=arguments.get("question", ""),
                    context=arguments.get("context", ""),
                    file_path=arguments.get("file_path", ""),
                )
            elif name == "memorygraph_check_freshness":
                result = _check_freshness()
            elif name == "memorygraph_auto_sync":
                result = _auto_sync()
            elif name == "memorygraph_ingest_conversation":
                err = _require_arg(arguments, "text")
                if err:
                    return _err_response(err["message"])
                result = _ingest_conversation(
                    conversation_text=arguments.get("text", ""),
                    file_path=arguments.get("file_path", ""),
                )
            elif name == "memorygraph_save_conversation":
                err = _require_arg(arguments, "text")
                if err:
                    return _err_response(err["message"])
                result = _save_conversation_context(
                    conversation_json=arguments.get("text", ""),
                )
            elif name == "memorygraph_hot_symbols":
                result = _get_hot_symbols(
                    limit=arguments.get("limit", 20),
                )
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2, default=str)
            )]
        except Exception as e:
            logger.exception(f"Error in tool {name}")
            return [TextContent(
                type="text",
                text=json.dumps({"error": str(e)})
            )]

    # Expose handler for testing (not part of public API)
    server._tool_handler = call_tool  # type: ignore[attr-defined]
    return server


async def run_mcp_server(project_root: str = ".") -> None:
    """Run the MCP server via stdio."""
    server = create_memorygraph_server(project_root)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
