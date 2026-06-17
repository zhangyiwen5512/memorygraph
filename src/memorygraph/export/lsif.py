"""LSIF (Language Server Index Format) exporter.

Converts memorygraph symbol/edge data to LSIF JSON lines format,
compatible with VS Code and other LSIF-consuming tools.

.. code-block:: python

    from memorygraph.export import export_lsif

    export_lsif("/project/.memorygraph/db.sqlite", "dump.lsif", "/project")
"""

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# Incrementing ID counter for LSIF vertices and edges
_ID_COUNTER_START = 1


def _next_id(counter: list[int]) -> int:
    """Return next monotonic ID."""
    vid = counter[0]
    counter[0] += 1
    return vid


def _emit_vertex(out, vid: int, label: str, **kwargs) -> None:
    """Write a single LSIF vertex as a JSON line."""
    obj = {"id": vid, "type": "vertex", "label": label}
    obj.update(kwargs)
    out.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _emit_edge(out, eid: int, label: str, outV: int, inV: int | list[int], **kwargs) -> None:  # noqa: N803,N803
    """Write a single LSIF edge as a JSON line."""
    obj = {"id": eid, "type": "edge", "label": label, "outV": outV, "inV": inV}
    obj.update(kwargs)
    out.write(json.dumps(obj, ensure_ascii=False) + "\n")


# Map memorygraph symbol kinds to LSIF-ish kinds (used in hover content)
_KIND_TO_SHORT: dict[str, str] = {
    "function": "func",
    "method": "method",
    "class": "class",
    "interface": "interface",
    "type_alias": "type",
    "variable": "var",
}


def export_lsif(db_path: str, output_path: str, project_root: str = ".") -> int:
    """Export memorygraph database to LSIF format.

    Args:
        db_path: Path to the memorygraph SQLite database.
        output_path: Path to write the LSIF JSON lines output.
        project_root: Root directory of the project (for absolute URIs).

    Returns:
        Number of LSIF lines (vertices + edges) written.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    counter = [_ID_COUNTER_START]
    line_count = 0

    try:
        with open(output_path, "w", encoding="utf-8") as out:
            line_count = _build_lsif(conn, out, counter, project_root)
    finally:
        conn.close()

    logger.info("LSIF export complete: %d lines → %s", line_count, output_path)
    return line_count


def _build_lsif(conn: sqlite3.Connection, out, counter: list[int],
                project_root: str) -> int:
    """Build and emit LSIF vertices and edges from the database."""
    lines = 0
    project_uri = f"file://{Path(project_root).resolve()}"

    # ── Metadata vertex ──
    meta_id = _next_id(counter)
    _emit_vertex(out, meta_id, "metaData",
                 version="0.6.0", projectRoot=project_uri,
                 toolInfo={"name": "memorygraph", "version": "1.5.0"})
    lines += 1

    # ── Project vertex ──
    proj_id = _next_id(counter)
    _emit_vertex(out, proj_id, "project", kind="python", resource=project_uri)
    lines += 1

    # ── Documents ──
    files = conn.execute("SELECT id, path, language FROM files ORDER BY path").fetchall()
    file_vertex_ids: dict[int, int] = {}

    for frow in files:
        fid = frow["id"]
        fpath = frow["path"]
        doc_id = _next_id(counter)
        file_vertex_ids[fid] = doc_id
        file_uri = f"file://{fpath}"
        lang_id = _map_language(frow["language"])

        _emit_vertex(out, doc_id, "document",
                     uri=file_uri, languageId=lang_id)
        lines += 1

        # Connect project → document
        eid = _next_id(counter)
        _emit_edge(out, eid, "contains", proj_id, [doc_id])
        lines += 1

    # ── Symbols → range + hoverResult + definitionResult ──
    symbol_tables = {
        "functions": "function",
        "methods": "method",
        "classes": "class",
        "interfaces": "interface",
        "type_aliases": "type_alias",
        "variables": "variable",
    }

    # Map qualified_name → definitionResult vertex ID for reference edges
    def_result_ids: dict[str, int] = {}

    for table, kind in symbol_tables.items():
        safe_table = f'"{table}"'
        rows = conn.execute(
            f"SELECT * FROM {safe_table} ORDER BY qualified_name"  # nosec B608
        ).fetchall()

        for row in rows:
            file_id = row["file_id"]
            sym_doc_id: int | None = file_vertex_ids.get(file_id)
            if sym_doc_id is None:
                continue

            qname = row["qualified_name"]
            name = row["name"]
            sl, sc = row["start_line"], row["start_col"]
            el, ec = row["end_line"], row["end_col"]

            # Range vertex — one per symbol definition
            range_id = _next_id(counter)
            _emit_vertex(out, range_id, "range",
                         start={"line": sl, "character": sc},
                         end={"line": el, "character": ec},
                         tag={"function": "de", "method": "de",
                              "class": "c", "interface": "struct",
                              "type_alias": "type", "variable": "variable"}.get(kind, "de"))
            lines += 1

            # Document contains range
            eid = _next_id(counter)
            _emit_edge(out, eid, "contains", sym_doc_id, [range_id])
            lines += 1

            # hoverResult — shows name, kind, signature on hover
            hover_id = _next_id(counter)
            # sqlite3.Row has no .get() — use 'in' check
            sig = row["signature"] if "signature" in row else ""  # noqa: SIM401
            hover_contents = {
                "language": "python",
                "value": f"{_KIND_TO_SHORT.get(kind, kind)} {name}: {sig}"
            }
            _emit_vertex(out, hover_id, "hoverResult",
                         result={"contents": hover_contents})
            lines += 1

            # textDocument/hover edge
            eid = _next_id(counter)
            _emit_edge(out, eid, "textDocument/hover", range_id, hover_id)
            lines += 1

            # definitionResult — "where is this defined?"
            def_id = _next_id(counter)
            _emit_vertex(out, def_id, "definitionResult")
            lines += 1

            # textDocument/definition edge
            eid = _next_id(counter)
            _emit_edge(out, eid, "textDocument/definition", range_id, def_id)
            lines += 1

            # item edge: definitionResult → range
            eid = _next_id(counter)
            _emit_edge(out, eid, "item", def_id, range_id,
                       property="definitions")
            lines += 1

            def_result_ids[qname] = def_id

    # ── Edges → referenceResult ──
    edge_rows = conn.execute(
        "SELECT source, target, kind, source_file_id, "
        "source_start_line, source_start_col, source_end_line, source_end_col "
        "FROM edges WHERE kind = 'calls' ORDER BY source"
    ).fetchall()

    # Group edge targets by source for referenceResult
    ref_map: dict[str, list[dict]] = {}
    for erow in edge_rows:
        src = erow["source"]
        src_fid = erow["source_file_id"]
        src_doc_id = file_vertex_ids.get(src_fid)
        if src_doc_id is None:
            continue
        ref_map.setdefault(src, []).append({
            "doc_id": src_doc_id,
            "sl": erow["source_start_line"],
            "sc": erow["source_start_col"],
            "el": erow["source_end_line"],
            "ec": erow["source_end_col"],
        })

    for qname, refs in ref_map.items():
        # Don't create referenceResult for symbols with def but no callers
        ref_ranges = []
        for ref in refs:
            range_id = _next_id(counter)
            _emit_vertex(out, range_id, "range",
                         start={"line": ref["sl"], "character": ref["sc"]},
                         end={"line": ref["el"], "character": ref["ec"]},
                         tag="ref")
            lines += 1
            eid = _next_id(counter)
            _emit_edge(out, eid, "contains", ref["doc_id"], [range_id])
            lines += 1
            ref_ranges.append(range_id)

        ref_result_id = _next_id(counter)
        _emit_vertex(out, ref_result_id, "referenceResult")
        lines += 1

        for rr_id in ref_ranges:
            eid = _next_id(counter)
            _emit_edge(out, eid, "item", ref_result_id, rr_id,
                       property="references")
            lines += 1

        # Connect the source's definitionResult to its referenceResult
        def_id_found: int | None = def_result_ids.get(qname)
        if def_id_found is not None:
            eid = _next_id(counter)
            _emit_edge(out, eid, "item", def_id_found, ref_result_id,
                       property="references")
            lines += 1

    return lines


def _map_language(lang: str) -> str:
    """Normalize language identifier to LSIF languageId."""
    mapping = {
        "python": "python",
        "typescript": "typescript",
        "javascript": "javascript",
        "go": "go",
        "rust": "rust",
        "java": "java",
        "csharp": "csharp",
    }
    return mapping.get(lang.lower(), lang.lower())
