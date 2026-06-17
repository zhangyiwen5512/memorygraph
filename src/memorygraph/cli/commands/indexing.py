"""Indexing commands: init, uninit, index, sync, watch."""
import json
import logging
import shutil
from pathlib import Path

import click

from memorygraph.parsing.batch import ParallelParser
from memorygraph.parsing.registry import LanguageRegistry
from memorygraph.storage import create_storage_manager

logger = logging.getLogger(__name__)


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
def init(project_root: str) -> None:
    """Initialize .memorygraph/ directory and database."""
    db_path = Path(project_root) / ".memorygraph" / "memorygraph.db"
    if db_path.exists():
        click.echo(f"Already initialized: {db_path}")
        return

    mgr = create_storage_manager(project_root)
    mgr.initialize()
    mgr.close()
    click.echo(f"Initialized: {db_path}")
    click.echo("Next: 'memorygraph index' to build the knowledge graph.")
    click.echo("      'memorygraph watch' to keep it updated automatically.")


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
@click.confirmation_option(prompt="Remove .memorygraph/ directory?")
def uninit(project_root: str) -> None:
    """Remove .memorygraph/ directory and all indexed data.

    Also cleans up memorygraph MCP server registration from
    ~/.claude.json and ~/.claude/claude.json.
    """
    cg_dir = Path(project_root) / ".memorygraph"
    if cg_dir.exists():
        shutil.rmtree(cg_dir)
        click.echo(f"Removed: {cg_dir}")
    else:
        click.echo("No .memorygraph/ directory found.")

    # Clean MCP registration from Claude config files
    claude_config_paths = [
        Path.home() / ".claude.json",
        Path.home() / ".claude" / "claude.json",
    ]
    for config_path in claude_config_paths:
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
                if "mcpServers" in config:
                    removed = False
                    for key in ("memorygraph",):
                        if key in config["mcpServers"]:
                            del config["mcpServers"][key]
                            removed = True
                    if removed:
                        config_path.write_text(json.dumps(config, indent=2))
                        click.echo(f"Cleaned MCP registration from {config_path}")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read/parse config %s: %s", config_path, e)


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
@click.option("--embed/--no-embed", default=False,
              help="Generate vector embeddings for indexed symbols (requires sentence-transformers)")
@click.option("--jobs", "-j", default=0, type=int,
              help="Number of parallel parse workers (0 = auto: cpu_count)")
def index(project_root: str, embed: bool, jobs: int) -> None:
    """Full index of the project (parse all files)."""
    import os as _os

    from memorygraph.cli.shared import _collect_files

    registry = LanguageRegistry()

    with create_storage_manager(project_root) as mgr:
        files = _collect_files(project_root, registry)
        if not files:
            click.echo("No source files found.")
            return

        nworkers = jobs if jobs > 0 else min(_os.cpu_count() or 4, 8)
        click.echo(f"Indexing {len(files)} files (--jobs={nworkers})...")

        count = 0
        batch_size = max(500, len(files) // (nworkers * 2)) if nworkers > 1 else 500
        total = len(files)
        parse_errors: list[str] = []
        skipped_files: list[tuple[str, str]] = []

        parser = ParallelParser(registry, max_workers=nworkers)
        for i in range(0, total, batch_size):
            chunk = files[i:i + batch_size]
            pct = min(100, (i + len(chunk)) * 100 // total)
            click.echo(f"[{pct:3d}%] Parsing {i + 1}-{min(i + batch_size, total)}/{total}")

            chunk_paths = [Path(f) for f in chunk]
            results = parser.parse_files(chunk_paths, resolve_symbols=True)

            # Separate valid and errored results
            valid = {}
            for path, result in results.items():
                if result.fatal_error:
                    skipped_files.append((result.file.path, result.fatal_error))
                    click.echo(f"  SKIP {result.file.path}: {result.fatal_error}", err=True)
                else:
                    if result.errors:
                        for err in result.errors[:5]:
                            parse_errors.append(f"  {result.file.path}: {err}")
                    valid[path] = result
            if valid:
                count += mgr.bulk_upsert(valid)

    # ── Error summary ──
    if skipped_files:
        click.echo(f"\n⚠️  {len(skipped_files)} file(s) skipped due to fatal errors:")
        for path, err in skipped_files[:10]:
            click.echo(f"  {path}: {err}")
    if parse_errors:
        shown = parse_errors[:20]
        click.echo(f"\n⚠️  {len(parse_errors)} non-fatal parse error(s):")
        for err in shown:
            click.echo(err)
        if len(parse_errors) > 20:
            click.echo(f"  ... and {len(parse_errors) - 20} more")  # pragma: no cover — needs >20 errors across ≥5 files

    if embed:
        _generate_embeddings(project_root)

    click.echo(f"\nIndexed {count} files.")
    if not embed:
        click.echo("Tip: 'memorygraph serve --web' to explore, 'memorygraph watch' to auto-update.")
    from memorygraph.cli.commands.utils import status as status_cmd
    ctx = click.get_current_context()
    ctx.invoke(status_cmd, project_root=project_root)


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
@click.option("--analyze/--no-analyze", default=False,
              help="Auto-run semantic analysis on synced files")
def sync(project_root: str, analyze: bool) -> None:
    """Incremental sync — only re-parse changed files (O(changed))."""
    from memorygraph.cli.shared import _do_sync

    result = _do_sync(project_root, analyze=analyze)

    if result["synced_count"] == 0 and result["unchanged_count"] > 0:
        click.echo(f"Everything up to date. ({result['unchanged_count']} files unchanged)")
        if not analyze:
            click.echo("Tip: run 'memorygraph sync --analyze' for complexity & smell analysis.")
        return

    parts = [
        f"New: {result['new_count']}",
        f"Changed: {result['changed_count']}",
        f"Unchanged: {result['unchanged_count']}",
        f"Synced: {result['synced_count']}",
    ]
    if analyze and result.get("analyzed_count", 0) > 0:
        parts.append(f"Analyzed: {result['analyzed_count']}")
    click.echo(", ".join(parts))


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
@click.option("--stop", "stop_daemon", is_flag=True, help="Stop running watcher")
@click.option("--interval", default=5.0, type=float,
              help="Polling interval in seconds (default: 5.0)")
@click.option("--once", "run_once", is_flag=True, default=False,
              help="Run a single sync pass and exit (testing)")
@click.option("--native/--poll", "use_native", is_flag=True, default=True,
              help="Use native OS events (inotify/FSEvents) instead of polling")
def watch(project_root: str, stop_daemon: bool, interval: float,
          run_once: bool, use_native: bool) -> None:
    """Watch project files and auto-sync on changes.

    Uses native OS filesystem events (inotify/FSEvents) by default,
    falling back to mtime polling when watchdog is unavailable.
    Gracefully shuts down on SIGTERM or SIGINT.
    """
    import os
    import signal
    import time

    from memorygraph.cli.shared import _do_sync

    root = Path(project_root).resolve()
    pid_file = root / ".memorygraph" / "watch.pid"

    if stop_daemon:
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                pid_file.unlink()
                click.echo(f"Stopped watch daemon (PID {pid}).")
            except (ProcessLookupError, ValueError):
                pid_file.unlink()
                click.echo("Removed stale pid file.")
        else:
            click.echo("No watch daemon running.")
        return

    # Pre-flight: ensure project is initialized
    mg_dir = root / ".memorygraph"
    if not mg_dir.is_dir():
        click.echo(
            "Not a memorygraph project. Run 'memorygraph init' first.",
            err=True,
        )
        return

    # Register signal handlers for graceful shutdown
    stop_event = False

    def _on_stop(_signum, _frame):
        nonlocal stop_event
        stop_event = True

    _orig_sigterm = signal.signal(signal.SIGTERM, _on_stop)
    _orig_sigint = signal.signal(signal.SIGINT, _on_stop)

    # Try native OS event watching first (inotify/FSEvents)
    if use_native:
        native_result = _watch_native(str(root), run_once)
        if native_result is not False:
            signal.signal(signal.SIGTERM, _orig_sigterm)
            signal.signal(signal.SIGINT, _orig_sigint)
            return

    # Fallback: mtime polling mode
    # Single-pass mode (testing): scan, sync, print, exit
    if run_once:
        _mtimes: dict[str, float] = {}
        changed = _scan_changes(root, _mtimes)
        if changed:
            from memorygraph.cli.shared import _do_sync
            result = _do_sync(str(root), analyze=False)
            click.echo(f"Synced: {result['synced_count']}, "
                       f"Changed: {len(changed)} file(s)")
        else:
            click.echo("No changes detected.")
        return

    # Write PID for daemon management
    try:
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()))

        click.echo(f"Watching {root} for changes... (interval={interval}s, Ctrl+C to stop)")

        # Track file mtimes: path → mtime
        mtimes: dict[str, float] = {}
        poll_count = 0
        synced_total = 0

        while not stop_event:
            poll_count += 1
            changed = _scan_changes(root, mtimes)

            if changed:
                click.echo(f"\n[{poll_count}] {len(changed)} file(s) changed, syncing...")
                result = _do_sync(str(root), analyze=False)
                synced_total += result["synced_count"]
                parts = [
                    f"  Synced: {result['synced_count']}",
                    f"New: {result['new_count']}",
                    f"Changed: {result['changed_count']}",
                    f"Unchanged: {result['unchanged_count']}",
                ]
                click.echo(", ".join(parts))
                # Reset mtimes after sync to pick up new/modified files
                _scan_changes(root, mtimes)

            # Sleep in short increments for responsive shutdown
            elapsed = 0.0
            step = min(0.5, interval)
            while elapsed < interval and not stop_event:
                time.sleep(step)
                elapsed += step

        click.echo(f"\nWatch stopped. {synced_total} total synced across {poll_count} polls.")

    finally:
        signal.signal(signal.SIGTERM, _orig_sigterm)
        signal.signal(signal.SIGINT, _orig_sigint)
        if pid_file.exists():
            pid_file.unlink()


def _scan_changes(root: Path, mtimes: dict[str, float]) -> list[str]:
    """Scan project directory and return list of changed file paths.

    Updates *mtimes* in-place: new files added, deleted files removed.
    Skips hidden directories, __pycache__, and .memorygraph/.
    """
    import os

    changed: list[str] = []
    seen: set[str] = set()
    skip_prefixes = (".", "__pycache__")

    for dirpath, dirnames, filenames in os.walk(root):
        # Filter out hidden dirs and caches
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(skip_prefixes)
        ]

        for fname in filenames:
            if fname.startswith(".") and fname != ".env":
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                stat = os.stat(fpath)
                current_mtime = stat.st_mtime
            except OSError:
                continue

            seen.add(fpath)
            prev = mtimes.get(fpath)
            if prev is None:
                # New file
                changed.append(fpath)
                mtimes[fpath] = current_mtime
            elif current_mtime > prev:
                # Modified file
                changed.append(fpath)
                mtimes[fpath] = current_mtime

    # Remove deleted files from mtimes
    deleted = [p for p in mtimes if p not in seen]
    for p in deleted:
        del mtimes[p]

    return changed


def _watch_native(root: str, run_once: bool) -> bool:
    """Watch project directory using native OS filesystem events via watchdog.

    Uses inotify on Linux, FSEvents on macOS, ReadDirectoryChanges on Windows.
    Falls back to mtime polling if watchdog is not installed.
    """
    import signal
    import time

    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        click.echo("watchdog not installed, falling back to polling mode")
        return False  # Signal caller: native mode unavailable

    # Detect and log which native backend is in use
    import platform
    _system = platform.system()
    _backend_names = {"Linux": "inotify", "Darwin": "FSEvents", "Windows": "ReadDirectoryChangesW"}
    _backend = _backend_names.get(_system, "unknown")
    logger.info("Native watch using %s backend on %s", _backend, _system)

    stop_event = False

    def _on_stop(_signum, _frame):
        nonlocal stop_event
        stop_event = True

    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)

    # Collect changed files
    changed_files: set[str] = set()

    class ChangeHandler(FileSystemEventHandler):
        def on_modified(self, event):
            if not event.is_directory:
                changed_files.add(event.src_path)

        def on_created(self, event):
            if not event.is_directory:
                changed_files.add(event.src_path)

        def on_deleted(self, event):
            if not event.is_directory:
                changed_files.add(event.src_path)

        def on_moved(self, event):
            if not event.is_directory:
                changed_files.add(event.dest_path)

    observer = Observer()
    handler = ChangeHandler()
    observer.schedule(handler, root, recursive=True)

    try:
        observer.start()
        click.echo(f"Watching {root} for changes... (native, Ctrl+C to stop)")

        if run_once:
            time.sleep(1.0)  # Brief wait for initial events
            observer.stop()
            observer.join(timeout=2)
            if changed_files:
                from memorygraph.cli.shared import _do_sync
                result = _do_sync(root, analyze=False)
                click.echo(f"Synced: {result['synced_count']}, "
                           f"Changed: {len(changed_files)} file(s)")
            else:
                click.echo("No changes detected.")
            return True

        # Continuous mode: sync every 2s if changes detected
        sync_total = 0
        while not stop_event:
            time.sleep(2.0)
            if changed_files:
                pending = list(changed_files)
                changed_files.clear()
                click.echo(f"\n{len(pending)} file(s) changed, syncing...")
                from memorygraph.cli.shared import _do_sync
                result = _do_sync(root, analyze=False)
                sync_total += result["synced_count"]
                parts = [
                    f"  Synced: {result['synced_count']}",
                    f"New: {result['new_count']}",
                    f"Changed: {result['changed_count']}",
                    f"Unchanged: {result['unchanged_count']}",
                ]
                click.echo(", ".join(parts))

        click.echo(f"\nWatch stopped. {sync_total} total synced.")

    finally:
        observer.stop()
        observer.join(timeout=3)

    return True


def _generate_embeddings(project_root: str) -> None:
    """Generate vector embeddings for all indexed symbols.

    Note: creates its own StorageManager because it is also called
    directly from tests.  The ``index`` command passes via *project_root*
    to avoid holding two open connections.
    """
    try:
        from memorygraph.semantic.embeddings import EmbeddingGenerator
    except ImportError:
        click.echo("Embeddings not available — sentence-transformers not installed.")
        return

    gen = EmbeddingGenerator()
    if not gen.is_available:
        click.echo("Embeddings not available — sentence-transformers not installed.")
        return

    from memorygraph.storage import create_storage_manager

    logger = logging.getLogger(__name__)
    with create_storage_manager(project_root) as mgr:
        files = mgr.list_files()
        total = 0
        embed_error_count = 0

        conn = mgr.get_conn()
        for f in files:
            symbols = mgr.get_symbols_for_file(f["path"])
            if not symbols:
                continue
            for sym in symbols:
                name = sym.get("name", sym.get("qualified_name", ""))
                qn = sym.get("qualified_name", name)
                sig = sym.get("signature", "")
                vec = gen.generate(name, sig)
                if vec is None:
                    continue
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO embeddings "
                        "(qualified_name, file_path, embedding) VALUES (?, ?, ?)",
                        (qn, f["path"], vec.tobytes())
                    )
                except Exception:
                    logger.exception("Failed to store embedding for %s", qn)
                    embed_error_count += 1
                total += 1

        conn.commit()
        if embed_error_count:
            click.echo(f"Generated {total} embeddings ({embed_error_count} failures).")
        else:
            click.echo(f"Generated {total} embeddings.")


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
@click.option("--output", "-o", default=None, help="Output path (default: project-root/memorygraph-backup-TIMESTAMP.tar.gz)")
def backup(project_root: str, output: str) -> None:
    """Backup the memorygraph database and semantic store."""
    import tarfile
    import time
    from pathlib import Path

    root = Path(project_root).resolve()
    mg_dir = root / ".memorygraph"
    if not mg_dir.is_dir():
        click.echo(
            "Not a memorygraph project. Run 'memorygraph init' first.",
            err=True,
        )
        raise SystemExit(1)

    if output is None:
        ts = time.strftime("%Y%m%d-%H%M%S")
        output = str(root / f"memorygraph-backup-{ts}.tar.gz")

    try:
        with tarfile.open(output, "w:gz") as tar:
            tar.add(str(mg_dir), arcname=".memorygraph")
        size_mb = Path(output).stat().st_size / (1024 * 1024)
        click.echo(f"Backup saved: {output} ({size_mb:.1f} MB)")
    except OSError as e:
        click.echo(f"Backup failed: {e}", err=True)
        raise SystemExit(1) from e


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
@click.argument("backup_file")
def restore(project_root: str, backup_file: str) -> None:
    """Restore memorygraph database from a backup archive."""
    import shutil
    import tarfile
    from pathlib import Path

    root = Path(project_root).resolve()
    backup_path = Path(backup_file).resolve()

    if not backup_path.exists():
        click.echo(f"Backup file not found: {backup_file}", err=True)
        raise SystemExit(1)

    if not tarfile.is_tarfile(str(backup_path)):
        click.echo(f"Not a valid tar archive: {backup_file}", err=True)
        raise SystemExit(1)

    mg_dir = root / ".memorygraph"
    if mg_dir.is_dir():
        click.echo(
            ".memorygraph already exists. Run 'memorygraph uninit' first "
            "or use --project-root with a different directory.",
            err=True,
        )
        raise SystemExit(1)

    try:
        with tarfile.open(str(backup_path), "r:gz") as tar:
            tar.extractall(path=str(root), filter="data")
        click.echo(f"Restored from: {backup_file}")
        click.echo("Project ready. Run 'memorygraph doctor' to verify.")
    except (tarfile.TarError, OSError) as e:
        click.echo(f"Restore failed: {e}", err=True)
        # Clean up partial extraction
        if mg_dir.is_dir():
            shutil.rmtree(str(mg_dir), ignore_errors=True)
        raise SystemExit(1) from e


def register(cli) -> None:
    cli.add_command(init)
    cli.add_command(uninit)
    cli.add_command(index)
    cli.add_command(sync)
    cli.add_command(watch)
    cli.add_command(backup)
    cli.add_command(restore)
