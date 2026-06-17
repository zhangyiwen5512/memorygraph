"""Semantic analysis CLI commands."""
from pathlib import Path

import click

from memorygraph.cli.shared import _extract_summary
from memorygraph.storage import create_storage_manager


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
@click.option("--file", "target_file", default=None, help="Target file path for semantic ingestion")
@click.option("--all", "all_files", is_flag=True, default=False, help="Ingest all indexed files")
@click.option("--summary", default="", help="Module summary")
@click.option("--source", default="manual", help="Annotation source")
def semantic_ingest(project_root: str, target_file: str, all_files: bool,
                    summary: str, source: str) -> None:
    """Ingest semantic annotations for a file."""
    from memorygraph.semantic.models import SemanticDocument
    from memorygraph.semantic.store import SemanticStore

    store = SemanticStore(project_root)
    with create_storage_manager(project_root) as mgr:
        files_to_process = []
        if all_files:
            files_to_process = [r["path"] for r in mgr.list_files()]
        elif target_file:
            files_to_process = [target_file]
        else:
            click.echo("Use --file or --all.", err=True)
            return

        count = 0
        for fpath in files_to_process:
            file_path = Path(fpath)
            if not file_path.is_absolute():
                file_path = (Path(project_root) / fpath).resolve()
            if not file_path.exists():
                continue
            auto_summary = _extract_summary(file_path, "")
            doc = SemanticDocument(
                file=fpath,
                source=source,
                module_summary=summary or auto_summary,
            )
            store.save(doc)
            count += 1

        click.echo(f"Semantic ingest complete: {count} file(s).")


def register(cli) -> None:
    cli.add_command(semantic_ingest)
    cli.add_command(analyze)
    cli.add_command(smells)
    cli.add_command(metrics)


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
@click.option("--file", "target_file", default=None, help="File to analyze")
@click.option("--all", "all_files", is_flag=True, default=False, help="Analyze all indexed files")
def analyze(project_root: str, target_file: str, all_files: bool) -> None:
    """Run semantic analysis (complexity, smells, role) on files."""
    from memorygraph.cli.shared import _analyze_files

    with create_storage_manager(project_root) as mgr:
        files_to_analyze: list[str] = []
        if all_files:
            files_to_analyze = [r["path"] for r in mgr.list_files()]
        elif target_file:
            files_to_analyze = [target_file]

    if not files_to_analyze:
        click.echo("Use --file or --all.", err=True)
        return

    analyzed = _analyze_files(project_root, files_to_analyze)
    click.echo(f"Analysis complete: {analyzed} file(s).")


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
@click.option("--file", "target_file", default=None, help="File to check")
@click.option("--all", "all_files", is_flag=True, default=False)
@click.option("--severity", default=None, help="Filter: info, warning")
def smells(project_root: str, target_file: str, all_files: bool, severity: str) -> None:
    """List code smells detected in analyzed files."""
    from memorygraph.semantic.store import SemanticStore
    store = SemanticStore(project_root)
    docs = store.load_all()
    if target_file:
        target = target_file
        if not Path(target).is_absolute():
            target = str((Path(project_root) / target).resolve())
        docs = [d for d in docs if d.file == target or d.file == target_file]
    count = 0
    for doc in docs:
        for odor in doc.odors:
            if severity and odor.get("severity") != severity:
                continue
            click.echo(f"[{odor.get('severity', '?')}] {odor['rule']}: {odor['symbol']} ({doc.file})")
            count += 1
    if count == 0:
        click.echo("No smells found.")
    else:
        click.echo(f"\n{count} smell(s) total.")


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
@click.option("--file", "target_file", default=None, help="File to check")
def metrics(project_root: str, target_file: str) -> None:
    """Show complexity metrics for analyzed files."""
    from memorygraph.semantic.store import SemanticStore
    store = SemanticStore(project_root)
    docs = store.load_all()
    if target_file:
        target = target_file
        if not Path(target).is_absolute():
            target = str((Path(project_root) / target).resolve())
        docs = [d for d in docs if d.file == target or d.file == target_file]
    for doc in docs:
        if not doc.metrics:
            continue
        click.echo(f"\n{doc.file}:")
        for item in doc.metrics.get("complexity", []):
            click.echo(f"  [{item['rank']}] {item['name']} (line {item['lineno']}): complexity={item['complexity']}")
