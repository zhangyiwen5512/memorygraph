"""Tests for memorygraph.config module."""


from memorygraph.config import load_config


class TestMemoryGraphConfig:
    """Tests for configuration loading and defaults."""

    def test_defaults(self):
        """Should return sensible defaults when no config sources present."""
        cfg = load_config("/nonexistent/path")
        assert cfg.port == 8765
        assert cfg.git_log_count == 20

    def test_env_overrides_port(self, monkeypatch):
        """MEMORYGRAPH_PORT should override the default."""
        monkeypatch.setenv("MEMORYGRAPH_PORT", "9999")
        cfg = load_config(".")
        assert cfg.port == 9999

    def test_toml_config(self, tmp_path):
        """memorygraph.toml should override defaults."""
        toml_path = tmp_path / "memorygraph.toml"
        toml_path.write_text("""[memorygraph]
port = 7777
git_log_count = 50
""")
        cfg = load_config(str(tmp_path))
        assert cfg.port == 7777
        assert cfg.git_log_count == 50

    def test_env_takes_priority_over_toml(self, tmp_path, monkeypatch):
        """Environment variables should override TOML values."""
        toml_path = tmp_path / "memorygraph.toml"
        toml_path.write_text("[memorygraph]\nport = 7777\n")
        monkeypatch.setenv("MEMORYGRAPH_PORT", "8888")
        cfg = load_config(str(tmp_path))
        assert cfg.port == 8888

    def test_invalid_env_does_not_crash(self, monkeypatch):
        """Invalid env var value should log warning but not crash."""
        monkeypatch.setenv("MEMORYGRAPH_PORT", "not_a_number")
        cfg = load_config(".")
        # Should fall back to default
        assert cfg.port == 8765

    def test_type_stability(self):
        """Config values should have correct types."""
        cfg = load_config(".")
        assert isinstance(cfg.port, int)
        assert isinstance(cfg.git_log_count, int)

    def test_missing_toml_file_is_graceful(self, tmp_path):
        """_apply_toml_overrides should return early when toml file missing (line 64-65)."""
        cfg = load_config(str(tmp_path))
        assert cfg.port == 8765  # default

    def test_invalid_toml_syntax_is_graceful(self, tmp_path):
        """_apply_toml_overrides should handle TOML parse error (line 77-79)."""
        toml_path = tmp_path / "memorygraph.toml"
        toml_path.write_text("[invalid {{{ toml")
        cfg = load_config(str(tmp_path))
        assert cfg.port == 8765  # fallback to default

    def test_tomli_fallback_when_tomllib_missing(self, tmp_path, monkeypatch):
        """_apply_toml_overrides should try tomli when tomllib unavailable (line 68-73)."""
        import sys
        # Force tomllib ImportError to exercise tomli fallback
        monkeypatch.setitem(sys.modules, "tomllib", None)
        try:
            toml_path = tmp_path / "memorygraph.toml"
            toml_path.write_text("[memorygraph]\nport = 6666\n")
            cfg = load_config(str(tmp_path))
            assert cfg.port == 6666
        finally:
            # Restore tomllib by deleting from sys.modules cache
            sys.modules.pop("tomllib", None)
            sys.modules.pop("tomli", None)

    def test_tomllib_and_tomli_both_missing(self, tmp_path, monkeypatch):
        """_apply_toml_overrides should return early when both tomllib and tomli missing (line 71-73)."""
        import sys
        toml_path = tmp_path / "memorygraph.toml"
        toml_path.write_text("[memorygraph]\nport = 7777\n")

        # Simulate both tomllib and tomli unavailable
        import builtins
        orig_import = builtins.__import__
        def block_toml(name, *args, **kwargs):
            if name in ("tomllib", "tomli"):
                raise ImportError(f"No module named '{name}'")
            return orig_import(name, *args, **kwargs)
        monkeypatch.setattr("builtins.__import__", block_toml)
        # Also remove from sys.modules cache
        sys.modules.pop("tomllib", None)
        sys.modules.pop("tomli", None)
        try:
            cfg = load_config(str(tmp_path))
            assert cfg.port == 8765  # default, TOML skipped
        finally:
            sys.modules.pop("tomllib", None)
            sys.modules.pop("tomli", None)
