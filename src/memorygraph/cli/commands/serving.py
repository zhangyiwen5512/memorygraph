"""Server commands: serve, install."""
import contextlib
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

import click

logger = logging.getLogger(__name__)

PID_FILE_NAME = "serve.pid"
LOG_FILE_NAME = "serve.log"


def _detach_terminal(project_root: str) -> None:
    """将当前进程脱离终端（单次 fork，父进程退出子进程继续）。

    fork 是 os.setsid() 的前置条件（子进程不是进程组 leader），
    同时确保子进程被 init (PID 1) 收养，退出时自动回收，避免僵尸进程。
    进程生命周期应由外部管理（systemd/supervisord/nohup）。
    """
    # Fork: parent exits so child is re-parented to init and can setsid()
    pid = os.fork()
    if pid > 0:
        # Parent: wait briefly for child to initialize, then exit
        os._exit(0)  # pragma: no cover — parent process exits, coverage cannot track

    # Child continues — we are no longer the process group leader
    os.setsid()
    os.chdir(project_root)
    os.umask(0o022)
    # 重定向 stdio
    log_dir = Path(project_root) / ".memorygraph"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_FILE_NAME
    sys.stdin = open(os.devnull, 'r')  # noqa: SIM115
    sys.stdout = sys.stderr = open(str(log_file), 'a')  # noqa: SIM115


def _write_pid(project_root: str) -> None:
    """Write current PID to .memorygraph/serve.pid."""
    pid_dir = Path(project_root) / ".memorygraph"
    pid_dir.mkdir(parents=True, exist_ok=True)
    pid_file = pid_dir / PID_FILE_NAME
    pid_file.write_text(str(os.getpid()))


def _remove_pid(project_root: str) -> None:
    """Remove the serve PID file if it exists."""
    pid_file = Path(project_root) / ".memorygraph" / PID_FILE_NAME
    if pid_file.exists():
        pid_file.unlink()


def _stop_daemon(project_root: str) -> bool:
    """Stop a running daemon by sending SIGTERM. Returns True if stopped."""
    pid_file = Path(project_root) / ".memorygraph" / PID_FILE_NAME
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        pid_file.unlink()
        logger.info("Stopped daemon (PID %d)", pid)
        return True
    except ProcessLookupError:
        pid_file.unlink()
        logger.warning("Stale PID file removed (process not found)")
        return True
    except (ValueError, OSError) as e:
        logger.warning("Could not stop daemon: %s", e)
        return False


@click.command()
@click.option("--project-root", default=".", help="Project root directory")
@click.option("--mcp", "mode_mcp", is_flag=True, help="Start MCP server (stdio)")
@click.option("--web", "mode_web", is_flag=True, help="Start web server (HTTP)")
@click.option("--port", default=8765, help="Web server port")
@click.option("--host", default="127.0.0.1", help="Web server bind address")
@click.option("--log-format", "log_format", default="text",
              type=click.Choice(["text", "json"]),
              help="Log output format (text or json)")
@click.option("--daemon", "as_daemon", is_flag=True, default=False,
              help="Run in background (deprecated, use --background)")
@click.option("--background", "as_background", is_flag=True, default=False,
              help="Run in background (detach from terminal)")
@click.option("--stop", "do_stop", is_flag=True, default=False,
              help="Stop a running daemon")
def serve(project_root: str, mode_mcp: bool, mode_web: bool, port: int,
          host: str, log_format: str, as_daemon: bool, as_background: bool,
          do_stop: bool) -> None:
    """Start memorygraph server.

    Default: MCP server via stdio.
    Use --web for HTTP web UI, --mcp for explicit MCP mode.
    Use --background to detach from terminal, --stop to stop a running daemon.
    """
    if do_stop:
        if _stop_daemon(project_root):
            click.echo("Daemon stopped.")
        else:
            click.echo("No daemon running.")
        return

    from memorygraph.cli.shared import setup_logging
    setup_logging(fmt=log_format)

    # --daemon backward compat: maps to --background
    background = as_background or as_daemon
    if as_daemon and not as_background:
        click.echo(
            "Warning: --daemon is deprecated, use --background instead",
            err=True,
        )

    if background and not mode_web:
        raise click.ClickException("Background mode requires --web.")

    if background and sys.platform != "linux":
        raise click.ClickException(
            f"Background mode is only supported on Linux "
            f"(current: {sys.platform}). "
            "Use 'serve --web' without --background for foreground mode."
        )

    if background:
        _detach_terminal(project_root)  # pragma: no cover — forks, cannot track in pytest
        _write_pid(project_root)  # pragma: no cover — background-only path

    if mode_web:
        import uvicorn

        from memorygraph.storage import create_storage_manager
        from memorygraph.storage.backend import create_semantic_store
        from memorygraph.storage.connection import get_db_path
        from memorygraph.web.server import SSEManager, create_asgi_app

        sse = SSEManager()
        mgr = create_storage_manager(project_root)
        mgr.initialize()
        sem_store = create_semantic_store(project_root)
        db_path = get_db_path(project_root)

        asgi_app = create_asgi_app(
            project_root, mgr, sem_store, sse,
            time.time(), db_path,
        )

        def _on_signal(_signum, _frame):
            with contextlib.suppress(Exception):
                mgr.close()

        _orig_sigterm = signal.signal(signal.SIGTERM, _on_signal)
        _orig_sigint = signal.signal(signal.SIGINT, _on_signal)

        try:
            logger.info("memorygraph web server (uvicorn) at http://%s:%d", host, port)
            uvicorn.run(
                asgi_app, host=host, port=port,
                log_level="warning",
            )
        except KeyboardInterrupt:
            pass
        finally:
            signal.signal(signal.SIGTERM, _orig_sigterm)
            signal.signal(signal.SIGINT, _orig_sigint)
            with contextlib.suppress(Exception):
                mgr.close()
            if background:
                _remove_pid(project_root)
    elif mode_mcp:
        import asyncio

        from memorygraph.mcp.server import run_mcp_server
        asyncio.run(run_mcp_server(project_root))
    else:
        import asyncio

        from memorygraph.mcp.server import run_mcp_server
        asyncio.run(run_mcp_server(project_root))


@click.command()
@click.option("--project-root", default=".", help="Project root directory (unused)")
def install(project_root: str) -> None:
    """Register memorygraph MCP server in Claude config."""
    abs_root = str(Path(project_root).resolve())

    claude_config_paths = [
        Path.home() / ".claude.json",
        Path.home() / ".claude" / "claude.json",
    ]

    config_path = None
    for p in claude_config_paths:
        if p.exists():
            config_path = p
            break

    if config_path is None:
        config_path = Path.home() / ".claude.json"

    config = {}
    if config_path.exists():
        config = json.loads(config_path.read_text())

    if "mcpServers" not in config:
        config["mcpServers"] = {}

    if "memorygraph" in config["mcpServers"]:
        click.echo("memorygraph already registered. Updating...")

    config["mcpServers"]["memorygraph"] = {
        "command": "memorygraph",
        "args": ["serve", "--mcp", "--project-root", abs_root],
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2))
    click.echo(f"Registered memorygraph MCP server in {config_path}")


def register(cli) -> None:
    cli.add_command(serve)
    cli.add_command(install)
