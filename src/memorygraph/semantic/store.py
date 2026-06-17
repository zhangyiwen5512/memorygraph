"""SemanticStore — semantic data persistence with optional PG backend.

When a :class:`AbstractSemanticRepository` is injected, all reads and writes
go through PostgreSQL.  When ``repo`` is ``None`` (legacy mode), the store
falls back to JSON files under ``.memorygraph/semantic/``.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from filelock import FileLock

from memorygraph.semantic.models import (
    Annotation,
    Insight,
    SemanticDocument,
    Unknown,
    file_path_hash,
)

if TYPE_CHECKING:
    from memorygraph.storage.semantic_repo import AbstractSemanticRepository  # pragma: no cover

logger = logging.getLogger(__name__)


class SemanticStore:
    """Manages semantic documents (annotations, unknowns, insights, modules).

    Two backends, selected by constructor injection:

    * **PG (recommended)**: pass an ``AbstractSemanticRepository`` — all data
      lives in PostgreSQL tables, one row per annotation.
    * **JSON (legacy)**: omit ``repo`` — data is stored as per-file JSON
      documents under ``.memorygraph/semantic/<hash>.json``.

    The public API is identical regardless of backend.
    """

    def __init__(
        self,
        project_root: str = ".",
        repo: AbstractSemanticRepository | None = None,
    ):
        root = Path(project_root).resolve()
        self._semantic_dir = root / ".memorygraph" / "semantic"
        self._project_root = root
        self._repo = repo

    # ── JSON-file helpers (legacy path) ────────────────────────────────

    def ensure_dir(self) -> None:
        """Ensure the semantic directory exists (JSON backend only)."""
        self._semantic_dir.mkdir(parents=True, exist_ok=True)

    def _doc_path(self, relative_path: str) -> Path:
        return self._semantic_dir / f"{file_path_hash(relative_path)}.json"

    def _load_json(self, relative_path: str) -> SemanticDocument | None:
        """Load semantic document from a JSON file."""
        path = self._doc_path(relative_path)
        if not path.exists():
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            return SemanticDocument.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to load semantic document %s: %s", path, e)
            return None

    def _save_json(self, doc: SemanticDocument) -> None:
        """Save a semantic document to a JSON file, merging with existing."""
        self.ensure_dir()
        path = self._doc_path(doc.file)
        lock = FileLock(str(path) + ".lock", timeout=10)

        acquired = False
        try:
            lock.acquire()
            acquired = True
        except TimeoutError:
            logger.warning(
                "Could not acquire lock for %s within 10s, skipping save", path
            )
            return

        try:
            existing = self._load_json(doc.file)
            if existing:
                existing.merge_from(doc)
                doc = existing

            with open(path, "w") as f:
                json.dump(doc.to_dict(), f, indent=2, ensure_ascii=False)
        finally:
            if acquired:
                lock.release()

    # ── Public API ─────────────────────────────────────────────────────

    def load(self, relative_path: str) -> SemanticDocument | None:
        """Load semantic document for a file. Returns None if not found."""
        if self._repo is not None:
            return self._load_from_repo(relative_path)
        return self._load_json(relative_path)

    def save(self, doc: SemanticDocument) -> None:
        """Save a semantic document, merging with existing if present."""
        if self._repo is not None:
            self._save_to_repo(doc)
            return
        self._save_json(doc)

    def load_all(self) -> list[SemanticDocument]:
        """Load all semantic documents in the store."""
        if self._repo is not None:
            return self._load_all_from_repo()
        self.ensure_dir()
        docs = []
        for f in sorted(self._semantic_dir.glob("*.json")):
            try:
                with open(f) as fh:
                    data = json.load(fh)
                doc = SemanticDocument.from_dict(data)
                docs.append(doc)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning("Failed to load semantic document %s: %s", f, e)
                continue
        return docs

    def count_annotated_symbols(self) -> int:
        """Count total annotated symbols across all documents."""
        if self._repo is not None:
            return self._repo.count_annotated_symbols()
        docs = self.load_all()
        count = 0
        seen: set[str] = set()
        for doc in docs:
            for ann in doc.annotations:
                key = f"{doc.file}:{ann.symbol}"
                if key not in seen:
                    seen.add(key)
                    count += 1
        return count

    def get_coverage(self, total_symbols: int, file_count: int = 0) -> str:
        """Calculate semantic coverage as percentage string."""
        if file_count == 0 and total_symbols == 0:
            return "0% files, 0% symbols"

        documented_files = len(self.list_documented_files())
        file_pct = round(documented_files / file_count * 100, 1) if file_count > 0 else 0

        annotated = self.count_annotated_symbols()
        sym_pct = round(annotated / total_symbols * 100, 1) if total_symbols > 0 else 0

        return f"{file_pct}% files, {sym_pct}% symbols"

    def list_documented_files(self) -> set[str]:
        """Return set of file paths that have semantic documents."""
        if self._repo is not None:
            return self._repo.list_documented_files()
        return {doc.file for doc in self.load_all() if doc.module_summary or doc.annotations}

    def remove(self, relative_path: str) -> None:
        """Remove the semantic document for a file."""
        if self._repo is not None:
            self._repo.remove_all_for_file(relative_path)
            return
        path = self._doc_path(relative_path)
        lock = FileLock(str(path) + ".lock", timeout=10)
        with lock:
            if path.exists():
                path.unlink()

    def delete_annotation(self, file_path: str, symbol: str, index: int = 0) -> bool:
        """Delete a specific annotation by symbol and index."""
        if self._repo is not None:
            return self._repo.delete_annotation(file_path, symbol)
        self.ensure_dir()
        path = self._doc_path(file_path)
        lock = FileLock(str(path) + ".lock", timeout=10)

        with lock:
            doc = self._load_json(file_path)
            if doc is None:
                return False
            matches = [i for i, a in enumerate(doc.annotations) if a.symbol == symbol]
            if index >= len(matches):
                return False
            doc.annotations.pop(matches[index])
            with open(path, "w") as f:
                json.dump(doc.to_dict(), f, indent=2, ensure_ascii=False)
            return True

    # ── PG backend helpers ─────────────────────────────────────────────

    def _save_to_repo(self, doc: SemanticDocument) -> None:
        """Persist a SemanticDocument to PostgreSQL row by row."""
        assert self._repo is not None
        fp = doc.file
        src = doc.source

        # Annotations — upsert each (UNIQUE on file_path, symbol)
        for ann in doc.annotations:
            self._repo.upsert_annotation(
                file_path=fp,
                symbol=ann.symbol,
                kind=ann.kind,
                summary=ann.summary,
                design_intent=ann.design_intent,
                pitfalls=ann.pitfalls,
                source=src,
            )

        # Unknowns — insert each (UNIQUE on file_path, symbol, question)
        for unk in doc.unknowns:
            self._repo.upsert_unknown(
                file_path=fp,
                symbol=unk.symbol,
                question=unk.question,
                context=unk.context,
                source=src,
            )

        # Insights — insert each (no dedup — append-only)
        for ins in doc.insights:
            self._repo.upsert_insight(
                file_path=fp,
                insight=ins.insight,
                related_symbols=ins.related_symbols,
                source=src,
            )

        # Module metadata
        self._repo.upsert_module(
            file_path=fp,
            module_summary=doc.module_summary,
            module_roles=doc.module_roles,
            metrics=doc.metrics,
            odors=doc.odors,
            source=src,
        )

    def _load_from_repo(self, relative_path: str) -> SemanticDocument | None:
        """Reconstruct a SemanticDocument from PG rows."""
        assert self._repo is not None
        fp = relative_path

        annotations_raw = self._repo.get_annotations_for_file(fp)
        unknowns_raw = self._repo.get_unknowns_for_file(fp)
        insights_raw = self._repo.get_insights_for_file(fp)
        module = self._repo.get_module(fp)

        has_data = annotations_raw or unknowns_raw or insights_raw or module
        if not has_data:
            return None

        doc = SemanticDocument(file=fp)
        doc.annotations = [
            Annotation(
                symbol=a["symbol"],
                kind=a.get("kind", "unknown"),
                summary=a.get("summary", ""),
                design_intent=a.get("design_intent", ""),
                pitfalls=a.get("pitfalls", ""),
            )
            for a in annotations_raw
        ]
        doc.unknowns = [
            Unknown(
                symbol=u["symbol"],
                question=u.get("question", ""),
                context=u.get("context", ""),
            )
            for u in unknowns_raw
        ]
        doc.insights = [
            Insight(
                insight=i["insight"],
                related_symbols=i.get("related_symbols", []),
            )
            for i in insights_raw
        ]
        if module:
            doc.module_summary = module.get("module_summary", "")
            doc.module_roles = module.get("module_roles", {})
            doc.metrics = module.get("metrics", {})
            doc.odors = module.get("odors", [])
            doc.source = module.get("source", "manual")
            doc.ingested_at = module.get("ingested_at", "")

        return doc

    def _load_all_from_repo(self) -> list[SemanticDocument]:
        """Load all semantic data from PG, grouping by file_path."""
        assert self._repo is not None

        annotations = self._repo.load_all_annotations()
        unknowns = self._repo.load_all_unknowns()
        insights = self._repo.load_all_insights()
        modules = self._repo.load_all_modules()

        # Index by file_path
        by_file: dict[str, dict[str, list]] = {}
        for a in annotations:
            fp = a["file_path"]
            if fp not in by_file:
                by_file[fp] = {"annotations": [], "unknowns": [], "insights": []}
            by_file[fp]["annotations"].append(a)
        for u in unknowns:
            fp = u["file_path"]
            if fp not in by_file:
                by_file[fp] = {"annotations": [], "unknowns": [], "insights": []}
            by_file[fp]["unknowns"].append(u)
        for i in insights:
            fp = i["file_path"]
            if fp not in by_file:
                by_file[fp] = {"annotations": [], "unknowns": [], "insights": []}
            by_file[fp]["insights"].append(i)

        # Modules indexed by file_path
        mod_by_file: dict[str, dict] = {m["file_path"]: m for m in modules}

        docs: list[SemanticDocument] = []
        for fp, groups in by_file.items():
            doc = SemanticDocument(file=fp)
            doc.annotations = [
                Annotation(
                    symbol=a["symbol"],
                    kind=a.get("kind", "unknown"),
                    summary=a.get("summary", ""),
                    design_intent=a.get("design_intent", ""),
                    pitfalls=a.get("pitfalls", ""),
                )
                for a in groups["annotations"]
            ]
            doc.unknowns = [
                Unknown(
                    symbol=u["symbol"],
                    question=u.get("question", ""),
                    context=u.get("context", ""),
                )
                for u in groups["unknowns"]
            ]
            doc.insights = [
                Insight(
                    insight=i["insight"],
                    related_symbols=i.get("related_symbols", []),
                )
                for i in groups["insights"]
            ]
            mod = mod_by_file.get(fp)
            if mod:
                doc.module_summary = mod.get("module_summary", "")
                doc.module_roles = mod.get("module_roles", {})
                doc.metrics = mod.get("metrics", {})
                doc.odors = mod.get("odors", [])
                doc.source = mod.get("source", "manual")
                doc.ingested_at = mod.get("ingested_at", "")
            docs.append(doc)

        # Include modules that have no annotations/unknowns/insights
        for fp, mod in mod_by_file.items():
            if fp not in by_file:
                doc = SemanticDocument(file=fp)
                doc.module_summary = mod.get("module_summary", "")
                doc.module_roles = mod.get("module_roles", {})
                doc.metrics = mod.get("metrics", {})
                doc.odors = mod.get("odors", [])
                doc.source = mod.get("source", "manual")
                doc.ingested_at = mod.get("ingested_at", "")
                docs.append(doc)

        return docs

