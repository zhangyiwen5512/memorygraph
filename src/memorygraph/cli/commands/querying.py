"""Query commands: query, context, files, affected, export."""
import contextlib
import json
import logging
import os
import sys
from pathlib import Path

import click

from memorygraph.storage import create_storage_manager

logger = logging.getLogger(__name__)


@click.command()
@click.argument("query")
@click.option("--limit", default=20, help="Max results")
@click.option("--project-root", default=".", help="Project root directory")
def query(query: str, limit: int, project_root: str) -> None:
    """Full-text search for symbols."""
    with create_storage_manager(project_root) as mgr:
        results = mgr.semantic_search(query, limit=limit)

    if not results:
        click.echo("No results found.")
        return

    for r in results:
        file_info = f"{r['file_path']}:{r.get('start_line', '?')}"
        sig = r.get("signature", "")
        click.echo(f"{r['qualified_name']} [{r['kind']}] {file_info}")
        if sig:
            click.echo(f"  {sig}")
        if r.get("_score", 1) > 1:
            click.echo(f"  relevance: {r['_score']}")


@click.command()
@click.argument("task")
@click.option("--limit", default=10, help="Max results")
@click.option("--project-root", default=".", help="Project root directory")
def context(task: str, limit: int, project_root: str) -> None:
    """Find relevant symbols and entry points for a task."""
    with create_storage_manager(project_root) as mgr:
        result = mgr.semantic_search(task, limit=limit)

    if not result:
        click.echo("No relevant symbols found.")
        return

    click.echo(f"Task: {task}\n")
    for r in result:
        click.echo(f"  {r['qualified_name']} [{r['kind']}]")
        click.echo(f"    {r['file_path']}:{r.get('start_line', '?')}")
        if r.get("signature"):
            click.echo(f"    {r['signature']}")
        click.echo()


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
def files(project_root: str) -> None:
    """List all indexed files."""
    with create_storage_manager(project_root) as mgr:
        file_list = mgr.list_files()

    if not file_list:
        click.echo("No indexed files.")
        return

    for f in file_list:
        click.echo(
            f"{f['path']}  [{f['language']}]  "
            f"{f['symbol_count']} symbols  "
            f"{f.get('error_count', 0)} errors  "
            f"last: {f['last_indexed']}"
        )


@click.command()
@click.argument("file_paths", nargs=-1)
@click.option("--project-root", default=".", help="Project root directory")
@click.option("--max-depth", default=5, help="Max call chain depth")
@click.option("--from-diff", is_flag=True, help="Read git diff from stdin")
@click.option("--diff-file", type=click.Path(exists=True), help="Read git diff from file")
def affected(file_paths, project_root: str, max_depth: int, from_diff: bool, diff_file):
    """Show symbols affected by changes to given files, or from git diff."""
    root = Path(project_root).resolve()
    changed_paths: set[str] = set()

    if from_diff:
        if sys.stdin.isatty():
            click.echo("Error: --from-diff requires piped stdin", err=True)
            return
        diff_text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    elif diff_file:
        diff_text = Path(diff_file).read_text()
    else:
        diff_text = None

    if diff_text:
        for line in diff_text.split("\n"):
            if line.startswith("+++ b/") and len(line) > 6 or line.startswith("--- a/") and len(line) > 6:
                path = line[6:]
                if path != "/dev/null":
                    changed_paths.add(path)

    for fp in file_paths:
        changed_paths.add(fp)

    if not changed_paths:
        click.echo("No changed files found.")
        return

    with create_storage_manager(project_root) as mgr:
        for fpath in sorted(changed_paths):
            abs_path = str(root / fpath) if not os.path.isabs(fpath) else fpath
            symbols = mgr.get_symbols_for_file(abs_path)
            if not symbols:
                symbols = mgr.get_symbols_for_file(fpath)

            if not symbols:
                click.echo(f"{fpath}: not indexed")
                continue

            click.echo(f"\n{fpath}:")
            for sym in symbols[:10]:
                qn = sym["qualified_name"]
                impacted = mgr.get_impact(qn, max_depth=max_depth)
                imp_names = [i["target"] for i in impacted[:5]]
                click.echo(f"  {qn} [{sym.get('kind', '?')}]")
                if imp_names:
                    click.echo(f"    → {', '.join(imp_names)}")


@click.command()
@click.option("--output", "-o", required=True, help="Output file path")
@click.option(
    "--format", "-f", "fmt",
    type=click.Choice(["json", "dot", "lsif"]),
    default="json",
    help="Export format: json (Cytoscape.js), dot (Graphviz), or lsif (VS Code)",
)
@click.option("--project-root", default=".", help="Project root directory")
def export(output: str, project_root: str, fmt: str = "json"):
    """Export knowledge graph as JSON, Graphviz DOT, or LSIF."""
    if fmt == "lsif":
        from memorygraph.export import export_lsif
        from memorygraph.storage.connection import get_db_path
        db_path = get_db_path(project_root)
        if not os.path.exists(db_path):
            raise click.ClickException(
                f"No database found at {db_path}. Run 'memorygraph index' first."
            )
        export_lsif(db_path, output, project_root)
        click.echo(f"LSIF exported to {output}")
        return

    nodes: list[dict] = []
    edges_list: list[dict] = []
    seen: set[str] = set()

    with create_storage_manager(project_root) as mgr:
        file_list = mgr.list_files()

        if file_list:
            from memorygraph.semantic.store import SemanticStore
            sem_store = SemanticStore(project_root)
            from memorygraph.cli.shared import _node_to_cyto

            for f in file_list[:50]:  # Limit to prevent huge exports
                syms = mgr.get_symbols_for_file(f["path"])
                for sym in syms:
                    qn = sym.get("qualified_name", "")
                    if qn not in seen:
                        seen.add(qn)
                        node = _node_to_cyto(sym, sem_store)
                        nodes.append(node)
                    callers = mgr.get_callers(qn, depth=1)
                    for c in callers:
                        edges_list.append({
                            "source": c["source"], "target": c["target"], "kind": "calls"
                        })

    if fmt == "dot":
        _write_dot(nodes, edges_list, output)
    else:
        result = {"nodes": nodes, "edges": edges_list}
        with open(output, "w") as fh:
            json.dump(result, fh, indent=2)
        click.echo(f"Exported {len(nodes)} nodes, {len(edges_list)} edges → {output}")


def _write_dot(nodes: list[dict], edges: list[dict], output: str) -> None:
    """Write knowledge graph to Graphviz DOT format."""
    _node_style = {
        "function":  'shape=box style=filled fillcolor="#cfe2ff"',
        "method":    'shape=box style=filled fillcolor="#d1e7dd"',
        "class":     'shape=hexagon style=filled fillcolor="#fff3cd"',
        "interface": 'shape=hexagon style="filled,dashed" fillcolor="#fff3cd"',
        "type":      'shape=ellipse style=filled fillcolor="#e2e3e5"',
        "variable":  'shape=ellipse style="filled,dashed" fillcolor="#f8d7da"',
    }
    _edge_style = {
        "calls":          '[color="#0d6efd" label="calls"]',
        "imports":        '[color="#6c757d" style=dashed label="imports"]',
        "extends":        '[color="#198754" style=bold label="extends"]',
        "implements":     '[color="#198754" style="bold,dashed" label="implements"]',
        "type_refs":      '[color="#6c757d" style=dotted label="type"]',
    }

    def _esc(text: str) -> str:
        """Escape special DOT characters and quotes."""
        return text.replace('"', '\\"').replace("\n", "\\n")

    lines = [
        "digraph memorygraph {",
        '  rankdir=LR;',
        '  splines=polyline;',
        '  nodesep=0.5;',
        '  ranksep=1.0;',
        '  bgcolor=transparent;',
        '  pad=0.2;',
        '  fontname="Helvetica";',
        '  fontsize=12;',
        '  node [shape=box fontname="Helvetica" fontsize=10];',
        '  edge [fontname="Helvetica" fontsize=8];',
        "",
    ]

    # Write nodes
    node_ids: set[str] = set()
    for n in nodes:
        nid = n.get("id", "")
        if not nid or nid in node_ids:
            continue
        node_ids.add(nid)
        kind = n.get("kind", "")
        style = _node_style.get(kind, "")
        label = _esc(n.get("label", nid))
        lines.append(f'  "{_esc(nid)}" [{style} label="{label}"];')

    # Write edges
    edge_keys: set[tuple[str, str, str]] = set()
    for e in edges:
        src = e.get("source", "")
        tgt = e.get("target", "")
        kind = e.get("kind", "calls")
        key = (src, tgt, kind)
        if key in edge_keys:
            continue
        edge_keys.add(key)
        style = _edge_style.get(kind, "")
        lines.append(f'  "{_esc(src)}" -> "{_esc(tgt)}" {style};')

    lines.append("}")
    with open(output, "w") as f:
        f.write("\n".join(lines) + "\n")
    click.echo(
        f"Exported {len(node_ids)} nodes, {len(edge_keys)} edges → {output} (DOT)"
    )


@click.command()
@click.argument("symbol")
@click.option("--project-root", default=".", help="Project root directory")
def git_history(symbol: str, project_root: str):
    """Show git history for a symbol (function/method/class level).

    Uses git log -L to trace changes line-by-line through git history.
    """
    import subprocess

    with create_storage_manager(project_root) as mgr:
        node = mgr.get_node(symbol)

    if not node:
        click.echo(f"Symbol not found: {symbol}")
        return

    file_path = node.get("file_path", "")
    name = node.get("name", symbol)
    start_line = node.get("start_line", 0)
    _end_line = node.get("end_line", start_line + 1)

    if not file_path or not os.path.exists(file_path):
        click.echo(f"File not found: {file_path}")
        return

    # Use git log -L to get function-level history
    line_range = f":{name}"
    try:
        from memorygraph.config import load_config
        cfg = load_config(project_root)
        result = subprocess.run(
            ["git", "-C", str(Path(project_root).resolve()),
             "log", "-L", f"{line_range}:{file_path}",
             "--pretty=format:%h %ad %an: %s", "--date=short",
             "-n", str(cfg.git_log_count)],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            click.echo(f"\nGit history for {symbol} in {file_path}:\n")
            for line in result.stdout.strip().split("\n"):
                if line.startswith("diff --git") or line.startswith("@@"):
                    continue
                click.echo(line)
        else:
            click.echo(f"No git history found for {symbol} (may be uncommitted)")
    except subprocess.TimeoutExpired:
        click.echo("Git log timed out.")
    except FileNotFoundError:
        click.echo("Git not found.")


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
@click.option("--file", "target_file", default=None, help="Analyze specific file")
def patterns(project_root: str, target_file: str):
    """Detect design patterns in indexed code.

    Uses static heuristics to identify 6 common patterns:
    Singleton, Factory, Observer, Strategy, Decorator, Repository.

    Conservative-biased: prefers false positives over misses.
    """
    from memorygraph.semantic.patterns import detect_patterns

    with create_storage_manager(project_root) as mgr:
        files_to_scan = [target_file] if target_file else [
            r["path"] for r in mgr.list_files()
        ]

        all_patterns = []
        for fpath in files_to_scan:
            symbols = mgr.get_symbols_for_file(fpath)
            if not symbols:
                continue
            callers: dict = {}
            callees: dict = {}
            for sym in symbols:
                qn = sym.get("qualified_name", sym.get("name", ""))
                if qn:
                    c_in = mgr.get_callers(qn, depth=1)
                    c_out = mgr.get_callees(qn, depth=1)
                    callers[qn] = [c["source"] for c in c_in]
                    callees[qn] = [c["target"] for c in c_out]

            found = detect_patterns(symbols, callers, callees)
            for p in found:
                p["file"] = fpath
            all_patterns.extend(found)

    if not all_patterns:
        click.echo("No design patterns detected.")
        return

    click.echo(f"Detected {len(all_patterns)} pattern candidate(s):\n")
    for p in sorted(all_patterns, key=lambda x: x.get("confidence", ""),
                    reverse=True):
        click.echo(
            f"[{p['confidence'].upper():8s}] {p['pattern']:12s} "
            f"{p['symbol']} ({p.get('file', '?')})"
        )
        if p.get("evidence"):
            click.echo(f"         → {p['evidence']}")


@click.command()
@click.argument("query")
@click.option("--limit", default=10, help="Max results")
@click.option("--project-root", default=".", help="Project root directory")
@click.option("--file-path", default=None,
              help="Filter results to a specific source file")
@click.option("--hybrid/--no-hybrid", default=True,
              help="Use hybrid search (FTS + vector, default: on)")
def search_semantic(query: str, limit: int, project_root: str, file_path: str | None,
                    hybrid: bool):
    """Semantic search using vector embeddings.

    Uses sentence-transformers (all-MiniLM-L6-v2) to generate embeddings
    for the query and compares against stored symbol embeddings.

    Falls back to FTS keyword search if embeddings are not available.
    """
    from memorygraph.semantic.embeddings import EmbeddingGenerator

    gen = EmbeddingGenerator()

    if not gen.is_available:
        click.echo(
            "sentence-transformers not installed. "
            "Falling back to FTS keyword search.\n"
            "Install with: pip install sentence-transformers"
        )
        with create_storage_manager(project_root) as mgr:
            results = mgr.semantic_search(query, limit=limit, file_path=file_path)
        _print_search_results(results, query)
        return

    # Generate query embedding
    try:
        query_vec = gen.generate("query", query)
    except Exception as e:
        click.echo(f"Error generating embedding: {e}", err=True)
        return

    if query_vec is None:
        click.echo("Failed to generate query embedding.")
        return

    # Get FTS results for hybrid search + stored embeddings
    with create_storage_manager(project_root) as mgr:
        fts_results = []
        if hybrid:
            with contextlib.suppress(Exception):
                fts_results = mgr.semantic_search(query, limit=limit * 2, file_path=file_path)

        stored = _load_stored_embeddings(mgr)

        if not stored:
            click.echo("No embeddings stored. Run 'memorygraph index' first.")
            return

        vector_results = gen.search(query_vec, stored, top_k=limit)

        if hybrid and fts_results:
            results = gen.hybrid_search(
                query_vec, fts_results, vector_results,
                fts_weight=0.4, vector_weight=0.6
            )
        else:
            results = vector_results

    _print_search_results(results, query)


def _load_stored_embeddings(mgr) -> list[dict]:
    """Load stored embeddings from SQLite database."""
    try:
        conn = mgr.get_conn()
        rows = conn.execute(
            "SELECT f.symbol_name, f.qualified_name, f.signature, "
            "f.file_path, f.kind, e.embedding "
            "FROM fts_index f "
            "JOIN embeddings e ON e.qualified_name = f.qualified_name "
            "AND e.file_path = f.file_path"
        ).fetchall()
        import numpy as np
        stored = []
        for row in rows:
            blob = row[5]
            if blob and len(blob) == 384 * 4:  # 384 floats × 4 bytes
                vec = np.frombuffer(blob, dtype=np.float32)
                stored.append({
                    "name": row[0],
                    "qualified_name": row[1],
                    "signature": row[2],
                    "file_path": row[3],
                    "kind": row[4],
                    "embedding": vec,
                })
        return stored
    except Exception:
        logger.warning("Failed to load stored embeddings", exc_info=True)
        return []


def _print_search_results(results: list[dict], query: str) -> None:
    """Print search results to stdout."""
    if not results:
        click.echo(f"No results found for: {query}")
        return

    click.echo(f"\nResults for: {query}\n")
    for i, r in enumerate(results[:20], 1):
        name = r.get("qualified_name", r.get("name", "?"))
        kind = r.get("kind", "?")
        file_path = r.get("file_path", "?")
        sig = r.get("signature", "")
        score = r.get("_combined", r.get("_similarity", r.get("_score", 0)))

        click.echo(f"{i:2d}. {name} [{kind}]")
        if sig:
            click.echo(f"    {sig}")
        click.echo(f"    {file_path}  (score: {score:.3f})")
        if i < len(results):
            click.echo("")


def register(cli):
    cli.add_command(query)
    cli.add_command(context)
    cli.add_command(files)
    cli.add_command(affected)
    cli.add_command(export)
    cli.add_command(git_history)
    cli.add_command(patterns)
    cli.add_command(search_semantic)

