"""Semantic data models — structured JSON for human-curated code understanding."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Annotation:
    """Human-written annotation for a specific symbol."""

    symbol: str
    kind: str  # function, method, class, interface, type, variable
    summary: str = ""
    design_intent: str = ""
    pitfalls: str = ""


@dataclass
class Unknown:
    """Open question / unclear area about a symbol."""

    symbol: str
    question: str
    context: str = ""


@dataclass
class Insight:
    """Design insight or architectural observation."""

    insight: str
    related_symbols: list[str] = field(default_factory=list)


@dataclass
class SemanticDocument:
    """Per-file semantic document stored in .memorygraph/semantic/<hash>.json.

    Append-only: each ingestion adds new annotations/insights without
    removing existing ones (unless explicitly overwriting the same symbol).
    """

    file: str  # relative path from project root
    file_hash: str = ""
    ingested_at: str = ""
    source: str = "manual"
    module_summary: str = ""
    annotations: list[Annotation] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)
    insights: list[Insight] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    odors: list = field(default_factory=list)
    module_roles: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.ingested_at:
            self.ingested_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SemanticDocument":
        # Use `or default` instead of `.get(key, default)` because JSON null
        # would make .get() return None instead of the default.
        raw_annotations = data.get("annotations") or []
        raw_unknowns = data.get("unknowns") or []
        raw_insights = data.get("insights") or []
        annotations = [
            Annotation(**a) if isinstance(a, dict) else a
            for a in raw_annotations
        ]
        unknowns = [
            Unknown(**u) if isinstance(u, dict) else u
            for u in raw_unknowns
        ]
        insights = [
            Insight(**i) if isinstance(i, dict) else i
            for i in raw_insights
        ]
        return cls(
            file=data.get("file") or "",
            file_hash=data.get("file_hash") or "",
            ingested_at=data.get("ingested_at") or "",
            source=data.get("source") or "manual",
            module_summary=data.get("module_summary") or "",
            annotations=annotations,
            unknowns=unknowns,
            insights=insights,
            metrics=data.get("metrics") or {},
            odors=data.get("odors") or [],
            module_roles=data.get("module_roles") or {},
        )

    def merge_from(self, other: "SemanticDocument") -> None:
        """Merge another document into this one (append-only).

        - module_summary: updated (overwritten)
        - annotations: merge by symbol (deduplicate by symbol)
        - unknowns: merge by symbol (deduplicate by symbol + question)
        - insights: append all
        """
        if other.module_summary:
            self.module_summary = other.module_summary

        # Merge annotations by symbol name
        existing_ann_symbols = {a.symbol for a in self.annotations}
        for ann in other.annotations:
            if ann.symbol in existing_ann_symbols:
                # Update existing annotation
                for i, existing in enumerate(self.annotations):
                    if existing.symbol == ann.symbol:
                        self.annotations[i] = ann
                        break
            else:
                self.annotations.append(ann)
                existing_ann_symbols.add(ann.symbol)

        # Merge unknowns by symbol + question
        existing_unk_keys = {(u.symbol, u.question) for u in self.unknowns}
        for unk in other.unknowns:
            key = (unk.symbol, unk.question)
            if key not in existing_unk_keys:
                self.unknowns.append(unk)
                existing_unk_keys.add(key)

        # Insights — always append
        self.insights.extend(other.insights)

        # Phase 3: metrics, odors, roles
        if other.metrics:
            self.metrics.update(other.metrics)
        self.odors.extend(other.odors)
        if other.module_roles:
            self.module_roles.update(other.module_roles)

        self.ingested_at = datetime.now(timezone.utc).isoformat()


def file_path_hash(relative_path: str) -> str:
    """Compute a stable hash for a file path to use as semantic document key."""
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]
