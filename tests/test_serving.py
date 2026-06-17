"""Tests for serving.py daemon management functions."""
import os
import tempfile
from pathlib import Path
from unittest import mock

from memorygraph.cli.commands.serving import (
    PID_FILE_NAME,
    _detach_terminal,
    _remove_pid,
    _stop_daemon,
    _write_pid,
)


class TestDetachTerminal:
    def test_detach_terminal_calls_setsid(self):
        """_detach_terminal should call os.setsid()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("os.setsid") as mock_setsid:
                with mock.patch("os.chdir"):
                    with mock.patch("os.umask"):
                        with mock.patch("sys.stdin"):
                            with mock.patch("sys.stdout"):
                                with mock.patch("sys.stderr"):
                                    _detach_terminal(tmpdir)
                                    mock_setsid.assert_called_once()

    def test_detach_terminal_changes_directory(self):
        """_detach_terminal should chdir to project_root."""
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch("os.setsid"):
            with mock.patch("os.chdir") as mock_chdir:
                with mock.patch("os.umask"):
                    with mock.patch("sys.stdin"):
                        with mock.patch("sys.stdout"):
                            with mock.patch("sys.stderr"):
                                _detach_terminal(tmpdir)
                                mock_chdir.assert_called_once_with(tmpdir)

    def test_detach_terminal_redirects_stdin_to_devnull(self):
        """_detach_terminal should redirect stdin to /dev/null."""
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch("os.setsid"):
            with mock.patch("os.chdir"):
                with mock.patch("os.umask"):
                    with mock.patch("builtins.open") as mock_open:
                        with mock.patch("sys.stdin"):
                            with mock.patch("sys.stdout"):
                                with mock.patch("sys.stderr"):
                                    _detach_terminal(tmpdir)
                                    # Verify os.devnull was opened for reading
                                    devnull_calls = [
                                        c for c in mock_open.call_args_list
                                        if c[0][0] == os.devnull
                                    ]
                                    assert len(devnull_calls) >= 1


class TestPidFile:
    def test_write_pid_creates_file(self):
        """_write_pid should create .memorygraph/serve.pid with current PID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_pid(tmpdir)
            pid_file = Path(tmpdir) / ".memorygraph" / PID_FILE_NAME
            assert pid_file.exists()
            pid = int(pid_file.read_text().strip())
            assert pid == os.getpid()

    def test_remove_pid_deletes_file(self):
        """_remove_pid should delete the PID file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_pid(tmpdir)
            _remove_pid(tmpdir)
            pid_file = Path(tmpdir) / ".memorygraph" / PID_FILE_NAME
            assert not pid_file.exists()

    def test_remove_pid_nonexistent_no_error(self):
        """_remove_pid should not raise when PID file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _remove_pid(tmpdir)  # Should not raise

    def test_stop_daemon_no_pid_file_returns_false(self):
        """_stop_daemon should return False when no PID file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            assert _stop_daemon(tmpdir) is False

    def test_stop_daemon_stale_pid(self):
        """PID file pointing to nonexistent process -> clean stale file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_pid(tmpdir)
            pid_file = Path(tmpdir) / ".memorygraph" / PID_FILE_NAME
            pid_file.write_text("99999")
            with mock.patch("os.kill", side_effect=ProcessLookupError):
                assert _stop_daemon(tmpdir) is True
            assert not pid_file.exists()
