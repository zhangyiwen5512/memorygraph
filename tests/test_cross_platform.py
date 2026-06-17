"""Cross-platform compatibility tests for memorygraph."""
from click.testing import CliRunner

from memorygraph.cli.main import cli


class TestPlatformGuards:
    """Verify platform-specific guards work correctly."""

    def test_background_rejected_on_macos(self, monkeypatch):
        """--background on macOS should error with clear message."""
        monkeypatch.setattr(
            "memorygraph.cli.commands.serving.sys.platform", "darwin"
        )
        runner = CliRunner()
        result = runner.invoke(cli, [
            "serve", "--web", "--background", "--project-root", "."
        ])
        assert result.exit_code != 0
        assert "only supported on Linux" in result.output
        assert "darwin" in result.output

    def test_background_rejected_on_windows(self, monkeypatch):
        """--background on Windows should error with clear message."""
        monkeypatch.setattr(
            "memorygraph.cli.commands.serving.sys.platform", "win32"
        )
        runner = CliRunner()
        result = runner.invoke(cli, [
            "serve", "--web", "--background", "--project-root", "."
        ])
        assert result.exit_code != 0
        assert "only supported on Linux" in result.output
        assert "win32" in result.output

    def test_background_without_web_rejected(self):
        """--background without --web should error."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "serve", "--background", "--project-root", "."
        ])
        assert result.exit_code != 0
        assert "requires --web" in result.output.lower()

    def test_daemon_flag_maps_to_background(self):
        """--daemon should map to --background with deprecation warning."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "serve", "--daemon", "--project-root", "."
        ])
        # Should warn about deprecation and error (no --web)
        assert "deprecated" in result.output.lower() or \
            "requires --web" in result.output.lower()
