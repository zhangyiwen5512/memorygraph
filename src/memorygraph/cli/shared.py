"""Shared helpers for CLI command modules."""
import hashlib
import logging
import os
import re
from pathlib import Path

from memorygraph.parsing.batch import ParallelParser
from memorygraph.parsing.registry import LanguageRegistry
from memorygraph.storage import create_storage_manager

logger = logging.getLogger(__name__)

ALWAYS_EXCLUDE = {
    "node_modules", "vendor", "dist", "build", "target",
    ".venv", ".next", "__pycache__", ".memorygraph", ".git",
    ".idea", ".vscode",
}


def _load_gitignore_patterns(project_root: str) -> list[str]:
    gi_path = Path(project_root) / ".gitignore"
    if not gi_path.exists():
        return []
    patterns = []
    with open(gi_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
    return patterns


def _should_exclude(rel_path: str, project_root: str, gitignore_patterns: list[str]) -> bool:
    parts = set(Path(rel_path).parts)
    if parts & ALWAYS_EXCLUDE:
        return True
    import fnmatch
    for pattern in gitignore_patterns:
        if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(rel_path, pattern + "/*"):
            return True
    return False


def _collect_files(project_root: str, registry: LanguageRegistry) -> list[str]:
    """Collect source files using os.scandir (faster than os.walk)."""
    root = Path(project_root).resolve()
    gitignore_patterns = _load_gitignore_patterns(str(root))
    all_extensions = set(registry.supported_extensions())
    files: list[str] = []

    def _scan(directory: Path) -> None:
        try:
            with os.scandir(str(directory)) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name not in ALWAYS_EXCLUDE and not entry.name.startswith("."):
                            _scan(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in all_extensions:
                            rel_path = str(Path(entry.path).relative_to(root))
                            if not _should_exclude(rel_path, str(root), gitignore_patterns):
                                files.append(entry.path)
        except OSError:  # pragma: no cover — requires OS-level error (permission, vanished dir, etc.)
            pass

    _scan(root)
    return sorted(files)


def _compute_hash(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_summary(file_path: Path, language: str) -> str:
    try:
        text = file_path.read_text(errors="replace")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Failed to read %s: %s", file_path, e)
        return f"{language} source file: {file_path.name}"
    if language == "python" and file_path.suffix == ".py":
        try:
            import ast
            tree = ast.parse(text)
            doc = ast.get_docstring(tree)
            if doc:
                return doc[:200]
        except SyntaxError:
            pass
    block_comment = re.search(r'/\*[\s\S]*?\*/', text)
    if block_comment:
        content = block_comment.group(0)
        content = content[2:-2]
        lines = [re.sub(r'^\s*\*\s?', '', line) for line in content.strip().split('\n')]
        summary = ' '.join(line.strip() for line in lines if line.strip())
        if summary:
            return summary[:200]
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            comment = stripped.lstrip("/# \t").strip()
            if comment and len(comment) > 5:
                return comment[:200]
    import_keywords = ("import ", "from ", "package ", "using ", "#include", "module ")
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped and not any(stripped.startswith(kw) for kw in import_keywords):
            return stripped[:200]
    return f"{language} source file: {file_path.name}"


def _analyze_files(project_root: str, file_paths: list[str]) -> int:
    """Run semantic analysis on the given file paths. Returns count of analyzed files."""
    import ast

    from memorygraph.semantic.analysis import (
        SmellDetector,
        analyze_complexity,
        analyze_raw,
        infer_role,
    )
    from memorygraph.semantic.models import SemanticDocument
    from memorygraph.semantic.store import SemanticStore

    with create_storage_manager(project_root) as mgr:
        store = SemanticStore(project_root)
        root = Path(project_root).resolve()
        analyzed = 0

        for fpath in file_paths:
            abs_path = Path(fpath)
            if not abs_path.is_absolute():
                abs_path = root / fpath
            if not abs_path.exists():
                continue
            try:
                source = abs_path.read_text(errors="replace")
            except OSError as e:
                logger.warning("Failed to read %s for analysis: %s", abs_path, e)
                continue
            symbols = mgr.get_symbols_for_file(str(abs_path))
            if not symbols:
                continue
            complexity = analyze_complexity(source)
            raw_metrics = analyze_raw(source)
            try:
                tree = ast.parse(source)
            except SyntaxError:
                tree = ast.parse("")
            detector = SmellDetector()
            node_map = detector._build_node_map(tree)  # once per file, not per symbol
            all_odors, roles = [], {}
            for sym in symbols:
                qn = sym["qualified_name"]
                callers = mgr.get_callers(qn, depth=1)
                callees = mgr.get_callees(qn, depth=1)
                odors = detector.detect(tree, qn, callers, callees, node_map=node_map)
                all_odors.extend(odors)
                role = infer_role(qn, sym.get("parent_class"), len(callers), len(callees))
                roles[qn] = role
            try:
                rel_path = str(Path(abs_path).relative_to(root))
            except ValueError:
                rel_path = str(abs_path)
            doc = SemanticDocument(
                file=rel_path, source="auto-analysis",
                metrics={"complexity": complexity, "raw": raw_metrics},
                odors=all_odors, module_roles=roles,
            )
            store.save(doc)
            analyzed += 1

        return analyzed


def _do_sync(project_root: str, analyze: bool = False,
             semantic: bool = True) -> dict:
    """Incremental sync: parse changed files, upsert, optionally analyze + semantic ingest.

    When *semantic* is True (default), auto-generates a SemanticDocument for
    each changed file —实现 L5 「边使用、边沉淀」的智能自动化.
    """
    registry = LanguageRegistry()
    with create_storage_manager(project_root) as mgr:
        files = _collect_files(project_root, registry)
        if not files:
            return {"new_count": 0, "changed_count": 0, "unchanged_count": 0, "synced_count": 0}
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
            return {"new_count": 0, "changed_count": 0, "unchanged_count": unchanged, "synced_count": 0}
        count = 0
        parser = ParallelParser(registry)
        results = parser.parse_files([Path(f) for f in to_parse], resolve_symbols=True)
        count = mgr.bulk_upsert(results)
        result = {
            "new_count": len(new_files), "changed_count": len(changed_files),
            "unchanged_count": unchanged, "synced_count": count,
        }
        if analyze and to_parse:
            analyzed = _analyze_files(project_root, to_parse)
            result["analyzed_count"] = analyzed
        # L5 智能沉淀: auto-generate semantic documents for changed files
        if semantic and to_parse:
            try:
                from memorygraph.semantic.models import SemanticDocument
                from memorygraph.semantic.store import SemanticStore
                store = SemanticStore(project_root)
                ingested = 0
                for fpath in to_parse:
                    auto_summary = _extract_summary(Path(fpath), "")
                    doc = SemanticDocument(
                        file=fpath,
                        source="auto-sync",
                        module_summary=auto_summary,
                    )
                    store.save(doc)
                    ingested += 1
                result["semantic_ingested"] = ingested
            except Exception:
                logger.debug("Semantic ingest skipped (store unavailable)", exc_info=True)
        return result


def _node_to_cyto(node: dict, sem_store) -> dict:
    qn = node.get("qualified_name", "?")
    kind = node.get("kind", "?")
    result = {"id": qn, "kind": str(kind), "line": node.get("start_line", "?")}
    for key in ("file_path", "file", "path"):
        if key in node:
            result["file"] = node[key]
            break
    for doc in sem_store.load_all():
        if doc.module_roles and qn in doc.module_roles:
            result["role"] = doc.module_roles[qn]
        if doc.metrics and doc.metrics.get("complexity"):
            for c in doc.metrics["complexity"]:
                if c["name"] == node.get("name"):
                    result["complexity"] = c["complexity"]
                    result["rank"] = c["rank"]
                    break
    return result


class JSONFormatter(logging.Formatter):
    """Log formatter that emits one JSON object per line for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        import time as _time
        payload: dict = {
            "ts": _time.strftime("%Y-%m-%dT%H:%M:%S", _time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(fmt: str = "text", level: int = logging.INFO) -> None:
    """Configure root logger with the requested format.

    Args:
        fmt: ``"text"`` (default, human-readable) or ``"json"`` (one JSON
            object per line, suitable for log aggregators).
        level: Python logging level (default: ``logging.INFO``).
    """
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))
    root.addHandler(handler)
