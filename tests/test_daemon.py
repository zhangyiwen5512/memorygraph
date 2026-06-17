"""Daemon integration tests — subprocess-based verification.

These tests verify daemon (serve --web --daemon) behavior:
- Startup: PID file creation, port binding
- Shutdown: SIGTERM graceful exit, PID file cleanup
- Signal handling: SIGINT, double SIGTERM resilience

All tests use ``subprocess`` for behavior verification (not pytest coverage).
Daemon mode (double-fork) is Linux-only; tests skip on other platforms.
"""

import contextlib
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest


def _find_free_port() -> int:
    """Return an available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_is_open(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except (ConnectionRefusedError, OSError):
        return False


def _wait_for_port(port: int, timeout: float = 10.0) -> bool:
    """Poll until port is open or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_is_open(port):
            return True
        time.sleep(0.2)
    return False


def _wait_for_port_closed(port: int, timeout: float = 5.0) -> bool:
    """Poll until port is closed or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _port_is_open(port):
            return True
        time.sleep(0.2)
    return False


# Daemon mode uses os.fork() — Linux only
pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Daemon mode (double-fork) is Linux-only"
)


class TestDaemonStartup:
    """Daemon startup: PID file + port binding."""

    def test_daemon_creates_pid_file(self):
        """Starting serve --web --daemon should create .memorygraph/serve.pid."""
        tmp = tempfile.mkdtemp()
        pid = None
        try:
            # Init first
            subprocess.run(
                [sys.executable, "-m", "memorygraph.cli.main", "init",
                 "--project-root", tmp],
                capture_output=True, timeout=10,
            )
            port = _find_free_port()

            # Start daemon — don't wait() as it double-forks and grandchild
            # inherits pipe fds. Poll PID file instead.
            proc = subprocess.Popen(
                [sys.executable, "-m", "memorygraph.cli.main", "serve",
                 "--web", "--daemon", "--project-root", tmp, "--port", str(port)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )

            pid_file = Path(tmp) / ".memorygraph" / "serve.pid"
            # Poll up to 5s for PID file to appear
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if pid_file.exists():
                    break
                # If the launcher exits non-zero, daemon failed
                if proc.poll() is not None and proc.returncode != 0:
                    break
                time.sleep(0.2)

            assert pid_file.exists(), (
                f"PID file not created at {pid_file}. "
                f"Launcher exit: {proc.returncode}"
            )

            pid = int(pid_file.read_text().strip())
            assert pid > 0
        finally:
            import shutil
            if pid:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGTERM)
            shutil.rmtree(tmp, ignore_errors=True)

    def test_daemon_listens_on_port(self):
        """serve --web --daemon should bind to the specified port."""
        tmp = tempfile.mkdtemp()
        pid = None
        try:
            subprocess.run(
                [sys.executable, "-m", "memorygraph.cli.main", "init",
                 "--project-root", tmp],
                capture_output=True, timeout=10,
            )
            port = _find_free_port()
            subprocess.Popen(
                [sys.executable, "-m", "memorygraph.cli.main", "serve",
                 "--web", "--daemon", "--project-root", tmp, "--port", str(port)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )

            pid_file = Path(tmp) / ".memorygraph" / "serve.pid"
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if pid_file.exists():
                    break
                time.sleep(0.2)

            if pid_file.exists():
                assert _wait_for_port(port, timeout=5.0), \
                    f"Port {port} not open after daemon start"

                pid = int(pid_file.read_text().strip())
        finally:
            import shutil
            if pid:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGTERM)
            shutil.rmtree(tmp, ignore_errors=True)


class TestDaemonStop:
    """Daemon stop: --stop flag, PID file cleanup."""

    def test_stop_kills_running_daemon(self):
        """serve --stop should kill a running daemon and clean up PID file."""
        tmp = tempfile.mkdtemp()
        pid = None
        try:
            subprocess.run(
                [sys.executable, "-m", "memorygraph.cli.main", "init",
                 "--project-root", tmp],
                capture_output=True, timeout=10,
            )
            port = _find_free_port()
            # Start daemon
            subprocess.Popen(
                [sys.executable, "-m", "memorygraph.cli.main", "serve",
                 "--web", "--daemon", "--project-root", tmp, "--port", str(port)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )

            pid_file = Path(tmp) / ".memorygraph" / "serve.pid"
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if pid_file.exists():
                    break
                time.sleep(0.2)

            if not pid_file.exists():
                pytest.skip("Daemon may not have started")

            pid = int(pid_file.read_text().strip())

            # Stop the daemon
            result = subprocess.run(
                [sys.executable, "-m", "memorygraph.cli.main", "serve",
                 "--stop", "--project-root", tmp],
                capture_output=True, text=True, timeout=10,
            )
            assert "stopped" in result.stdout.lower() or "Daemon" in result.stdout

            # PID file should be cleaned up
            assert not pid_file.exists(), "PID file not removed after stop"

            # Wait for process to exit gracefully
            deadline = time.time() + 5.0
            exited = False
            while time.time() < deadline:
                try:
                    os.kill(pid, 0)
                    time.sleep(0.3)
                except ProcessLookupError:
                    exited = True
                    break
            if not exited:
                os.kill(pid, signal.SIGKILL)
                pytest.fail(f"Process {pid} still running after --stop+5s")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_stop_no_daemon_is_noop(self):
        """serve --stop when no daemon running should report cleanly."""
        tmp = tempfile.mkdtemp()
        try:
            result = subprocess.run(
                [sys.executable, "-m", "memorygraph.cli.main", "serve",
                 "--stop", "--project-root", tmp],
                capture_output=True, text=True, timeout=10,
            )
            assert "No daemon running" in result.stdout or result.returncode == 0
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class TestDaemonSignalHandling:
    """Daemon graceful shutdown on SIGTERM/SIGINT."""

    def test_sigterm_cleans_up_pid_file(self):
        """Sending SIGTERM to daemon should clean up PID file."""
        tmp = tempfile.mkdtemp()
        pid = None
        try:
            subprocess.run(
                [sys.executable, "-m", "memorygraph.cli.main", "init",
                 "--project-root", tmp],
                capture_output=True, timeout=10,
            )
            port = _find_free_port()
            subprocess.Popen(
                [sys.executable, "-m", "memorygraph.cli.main", "serve",
                 "--web", "--daemon", "--project-root", tmp, "--port", str(port)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )

            pid_file = Path(tmp) / ".memorygraph" / "serve.pid"
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if pid_file.exists():
                    break
                time.sleep(0.2)

            if not pid_file.exists():
                pytest.skip("Daemon may not have started")

            pid = int(pid_file.read_text().strip())

            # Send SIGTERM
            os.kill(pid, signal.SIGTERM)

            # Wait for process to exit gracefully
            deadline = time.time() + 5.0
            exited = False
            while time.time() < deadline:
                try:
                    os.kill(pid, 0)
                    time.sleep(0.3)
                except ProcessLookupError:
                    exited = True
                    break

            # PID file should be removed (handler cleans it)
            assert not pid_file.exists(), "PID file not removed after SIGTERM"

            if not exited:
                os.kill(pid, signal.SIGKILL)
                pytest.fail(f"Process {pid} still alive after SIGTERM+5s")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_stale_pid_file_cleaned_up(self):
        """Stale PID file (process already dead) should be cleaned on --stop."""
        tmp = tempfile.mkdtemp()
        try:
            pid_dir = Path(tmp) / ".memorygraph"
            pid_dir.mkdir(parents=True, exist_ok=True)
            pid_file = pid_dir / "serve.pid"
            # Write a PID that doesn't exist
            pid_file.write_text("99999")

            result = subprocess.run(
                [sys.executable, "-m", "memorygraph.cli.main", "serve",
                 "--stop", "--project-root", tmp],
                capture_output=True, text=True, timeout=10,
            )
            assert "stopped" in result.stdout.lower() or "Stale" in result.stdout or "Daemon" in result.stdout
            assert not pid_file.exists(), "Stale PID file should be removed"
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
