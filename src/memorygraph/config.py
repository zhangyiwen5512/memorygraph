"""Typed configuration with TOML file + env var fallback.

Priority: env var > memorygraph.toml > defaults.

Usage::

    from memorygraph.config import load_config
    cfg = load_config(".")
    print(cfg.port, cfg.log_level)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Union

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────

DEFAULT_PORT = 8765
DEFAULT_QUERY_LIMIT = 20
DEFAULT_GIT_LOG_COUNT = 20


@dataclass
class MemoryGraphConfig:
    """Immutable configuration for a memorygraph project."""

    project_root: str

    # ── Server ──
    port: int = DEFAULT_PORT

    # ── Query ──
    git_log_count: int = DEFAULT_GIT_LOG_COUNT


# ── Env var mapping ───────────────────────────────────────────────────

_EnvConverter = Union[type, Callable[[str], Any]]
_ENV_MAP: dict[str, tuple[str, _EnvConverter]] = {
    "MEMORYGRAPH_PORT": ("port", int),
}


def _apply_env_overrides(cfg: MemoryGraphConfig) -> None:
    """Apply environment variable overrides in-place."""
    for env_var, (attr_name, converter) in _ENV_MAP.items():
        raw = os.environ.get(env_var)
        if raw is None:
            continue
        try:
            setattr(cfg, attr_name, converter(raw))
        except (TypeError, ValueError) as exc:
            logger.warning("Invalid value for %s=%r: %s", env_var, raw, exc)


def _apply_toml_overrides(cfg: MemoryGraphConfig, toml_path: Path) -> None:
    """Apply memorygraph.toml overrides in-place (lower priority than env)."""
    if not toml_path.exists():
        return
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            logger.debug("tomllib/tomli not available, skipping TOML config")
            return

    try:
        data: dict[str, Any] = tomllib.loads(toml_path.read_text())
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", toml_path, exc)
        return

    section: dict[str, Any] = data.get("memorygraph", data)

    for attr_name in ("port", "git_log_count"):
        if attr_name in section:
            setattr(cfg, attr_name, type(getattr(cfg, attr_name))(section[attr_name]))


def load_config(project_root: str = ".") -> MemoryGraphConfig:
    """Load configuration for *project_root*.

    Priority: env vars > memorygraph.toml > defaults.
    """
    cfg = MemoryGraphConfig(project_root=str(Path(project_root).resolve()))

    toml_path = Path(project_root) / "memorygraph.toml"
    _apply_toml_overrides(cfg, toml_path)
    _apply_env_overrides(cfg)

    return cfg
