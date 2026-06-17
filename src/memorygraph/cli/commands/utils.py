"""Utility commands: status, plugins."""
from pathlib import Path

import click

from memorygraph.storage import create_storage_manager


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Output as JSON (machine-readable)")
def status(project_root: str, as_json: bool) -> None:
    """Show project index statistics and health overview."""
    import json as _json
    from pathlib import Path

    with create_storage_manager(project_root) as mgr:
        stats = mgr.stats()

    if as_json:
        db_path = Path(project_root) / ".memorygraph" / "memorygraph.db"
        sem_dir = Path(project_root) / ".memorygraph" / "semantic"
        output = {
            "project_root": str(Path(project_root).resolve()),
            "files_indexed": stats["file_count"],
            "symbols": stats["symbol_count"],
            "edges": stats["edge_count"],
            "last_updated": stats["last_updated"],
            "backend": stats.get("backend", "sqlite"),
            "embeddings_available": stats.get("embeddings_available", False),
            "db_size_mb": round(db_path.stat().st_size / (1024 * 1024), 1) if db_path.exists() else None,
            "semantic_docs": len(list(sem_dir.glob("*.json"))) if sem_dir.is_dir() else 0,
        }
        click.echo(_json.dumps(output, indent=2, default=str))
        return

    click.secho("═" * 50, fg="blue")
    click.secho("  memorygraph — Project Status", fg="blue", bold=True)
    click.secho("═" * 50, fg="blue")

    # Database stats
    click.echo()
    click.secho("📊 Index", fg="cyan", bold=True)
    click.echo(f"  Files:     {stats['file_count']:>8,}")
    click.echo(f"  Symbols:   {stats['symbol_count']:>8,}")
    click.echo(f"  Edges:     {stats['edge_count']:>8,}")
    click.echo(f"  Updated:   {stats['last_updated']}")

    # Semantic layer
    click.echo()
    click.secho("🧠 Semantic", fg="cyan", bold=True)
    try:
        from memorygraph.semantic.store import SemanticStore
        sem_store = SemanticStore(project_root)
        coverage = sem_store.get_coverage(
            total_symbols=stats["symbol_count"],
            file_count=stats["file_count"]
        )
        click.echo(f"  Coverage:  {coverage}")
    except Exception:
        click.echo("  Coverage:  not available")

    # Infrastructure
    click.echo()
    click.secho("⚙️  Infrastructure", fg="cyan", bold=True)
    click.echo(f"  Backend:     {stats.get('backend', 'sqlite')}")
    embeddings = "available" if stats.get("embeddings_available") else "none (run index --embed)"
    click.echo(f"  Embeddings:  {embeddings}")

    # Database size
    db_path = Path(project_root) / ".memorygraph" / "memorygraph.db"
    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        click.echo(f"  DB size:     {size_mb:.1f} MB")

    # Semantic docs count
    sem_dir = Path(project_root) / ".memorygraph" / "semantic"
    if sem_dir.is_dir():
        doc_count = len(list(sem_dir.glob("*.json")))
        click.echo(f"  Sem docs:    {doc_count}")

    # Quick actions
    click.echo()
    click.secho("💡 Quick Actions", fg="cyan", bold=True)
    click.echo("  memorygraph watch      — auto-sync on file changes")
    click.echo("  memorygraph serve --web — launch graph explorer")
    click.echo("  memorygraph doctor     — full health check")
    click.echo("  memorygraph backup     — backup database")
    click.echo()


@click.group()
def plugins() -> None:
    """Manage memorygraph plugins."""
    pass


@plugins.command("list")
def plugins_list():
    """List installed language and analyzer plugins."""
    from memorygraph.plugins import builtin_languages, discover_plugins

    click.echo("Built-in languages:")
    for lang in builtin_languages():
        click.echo(f"  {lang['name']} ({', '.join(lang['extensions'])})")

    discovered = discover_plugins()
    if discovered["language"]:
        click.echo("\nThird-party language plugins:")
        for p in discovered["language"]:
            click.echo(f"  {p.language} ({', '.join(p.extensions)})")
    if discovered["analyzer"]:
        click.echo("\nAnalyzer plugins:")
        for p in discovered["analyzer"]:
            click.echo(f"  {p.name}")

    if not discovered["language"] and not discovered["analyzer"]:
        click.echo("\nNo third-party plugins installed.")
        click.echo(
            "Install plugins via pyproject.toml entry_points: "
            "memorygraph.plugins"
        )


@click.command()
@click.option("--input", "-i", "input_file", required=True,
              type=click.Path(exists=True), help="Conversation JSON file")
@click.option("--project-root", default=".", help="Project root directory")
def extract_from_conversation(input_file: str, project_root: str) -> None:
    """Extract semantic annotations from Claude Code conversation export.

    Uses heuristic regex patterns to find function/class descriptions,
    design decisions, and bug notes in conversation text.

    Extracted annotations are saved to .memorygraph/semantic/.
    """
    from memorygraph.semantic.conversation import extract_from_conversation
    from memorygraph.semantic.store import SemanticStore

    try:
        docs = extract_from_conversation(input_file)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        return

    if not docs:
        click.echo("No annotations extracted from conversation.")
        return

    store = SemanticStore(project_root)
    saved = 0
    for doc in docs:
        if doc.annotations or doc.module_summary:
            store.save(doc)
            saved += 1

    click.echo(f"Extracted {saved} annotation document(s) from conversation.")
    dest = Path(project_root) / ".memorygraph" / "semantic"
    click.echo(f"Saved to {dest}/")


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
@click.option("--uninstall", "do_uninstall", is_flag=True, default=False,
              help="Remove the hook")
@click.option("--claude", "claude_hook", is_flag=True, default=False,
              help="Install Claude Code Stop hook (auto semantic ingestion)")
def hook(project_root: str, do_uninstall: bool, claude_hook: bool) -> None:
    """Install or uninstall automation hooks.

    Without --claude: installs a git pre-commit hook that runs
    'memorygraph sync' before each commit.

    With --claude: installs a Claude Code Stop hook that auto-ingests
    conversation semantics after each response (L5 auto-precipitation).
    Requires the memorygraph MCP server to be configured.
    """
    root = Path(project_root).resolve()

    if claude_hook:
        _install_claude_hook(root, do_uninstall)
        return

    git_dir = root / ".git"
    if not git_dir.exists():
        click.echo("Not a git repository (no .git directory found).", err=True)
        return

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook_path = hooks_dir / "pre-commit"

    if do_uninstall:
        if hook_path.exists():
            hook_path.unlink()
            click.echo("Pre-commit hook removed.")
        else:
            click.echo("No pre-commit hook installed.")
        return

    hook_script = (
        "#!/bin/sh\n"
        "# memorygraph pre-commit hook — auto-sync before commit\n"
        f"memorygraph sync --project-root {root}\n"
    )
    hook_path.write_text(hook_script)
    hook_path.chmod(0o755)
    click.echo(f"Pre-commit hook installed: {hook_path}")
    click.echo("memorygraph sync will run before each commit.")


def _install_claude_hook(project_root: Path, do_uninstall: bool) -> None:
    """Install a Claude Code Stop hook for L5 auto semantic precipitation.

    Writes a hook to .claude/settings.local.json that calls
    memorygraph_ingest_conversation after each Claude response.
    """
    import json as _json

    claude_dir = project_root / ".claude"
    settings_path = claude_dir / "settings.local.json"

    if do_uninstall:
        if settings_path.exists():
            try:
                uninstall_settings: dict = _json.loads(settings_path.read_text())
                uninstall_hooks: dict = uninstall_settings.get("hooks", {})
                removed = False
                for event in ("Stop",):
                    event_hooks: list = uninstall_hooks.get(event, [])
                    new_hooks = [
                        h for h in event_hooks
                        if "memorygraph" not in _json.dumps(h)
                    ]
                    if len(new_hooks) != len(event_hooks):
                        uninstall_hooks[event] = new_hooks
                        removed = True
                if removed:
                    uninstall_settings["hooks"] = uninstall_hooks
                    settings_path.write_text(_json.dumps(uninstall_settings, indent=2) + "\n")
                    click.echo("Claude Code hook removed.")
                else:
                    click.echo("No memorygraph hook found.")
            except Exception as e:
                click.echo(f"Failed to read settings: {e}", err=True)
        else:
            click.echo("No .claude/settings.local.json found.")
        return

    # Read existing settings or create
    install_settings: dict = {}
    if settings_path.exists():
        try:
            install_settings = _json.loads(settings_path.read_text())
        except Exception:
            click.echo("Warning: could not parse existing settings, overwriting.", err=True)

    # Build Stop hook: call memorygraph extract-from-conversation after each response
    hook_command = (
        "memorygraph extract-from-conversation "
        "--input \"${CLAUDE_CONVERSATION_FILE:-/dev/null}\" "
        f"--project-root {project_root}"
    )
    stop_hook = {
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": hook_command,
        }],
    }

    install_hooks: dict = install_settings.get("hooks", {})
    stop_hooks: list = install_hooks.get("Stop", [])
    # Deduplicate: don't add if already present
    existing_commands = {
        h.get("hooks", [{}])[0].get("command", "")  # type: ignore[index]
        for h in stop_hooks  # type: ignore[union-attr]
    }
    if hook_command not in existing_commands:
        stop_hooks.append(stop_hook)
    install_hooks["Stop"] = stop_hooks
    install_settings["hooks"] = install_hooks

    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(_json.dumps(install_settings, indent=2) + "\n")
    click.echo(f"Claude Code Stop hook installed: {settings_path}")
    click.echo("After each response, conversation semantics will be auto-ingested.")


def register(cli) -> None:
    cli.add_command(status)
    cli.add_command(plugins)
    cli.add_command(extract_from_conversation)
    cli.add_command(hook)


