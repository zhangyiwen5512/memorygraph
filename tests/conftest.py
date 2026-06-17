"""Shared test fixtures."""
import os
import subprocess
from pathlib import Path

import pytest


def _setup_multiprocess_coverage():
    """Configure coverage.py for multiprocess (ProcessPoolExecutor) tracking.

    Sets COVERAGE_PROCESS_STARTUP so worker processes know where the
    coverage config lives.  Also adds the project root to PYTHONPATH so
    ``sitecustomize.py`` is importable (needed for ``spawn`` start method
    on macOS/Windows).
    """
    project_root = str(Path(__file__).resolve().parent.parent)
    config_path = os.path.join(project_root, ".coveragerc")

    # Let worker processes discover the coverage config
    if "COVERAGE_PROCESS_STARTUP" not in os.environ and os.path.exists(config_path):
        os.environ["COVERAGE_PROCESS_STARTUP"] = config_path

    # Ensure project root is importable (for sitecustomize.py discovery)
    if project_root not in os.environ.get("PYTHONPATH", ""):
        existing = os.environ.get("PYTHONPATH", "")
        if existing:
            os.environ["PYTHONPATH"] = f"{project_root}{os.pathsep}{existing}"
        else:
            os.environ["PYTHONPATH"] = project_root


_setup_multiprocess_coverage()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repo with sample Python files for e2e tests.

    Returns the path to the repo root.
    """
    repo = tmp_path / "test_repo"
    repo.mkdir()

    # Init git
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo, check=True, capture_output=True,
    )

    # Write sample Python files
    (repo / "main.py").write_text(
        "import utils\n\ndef greet(name):\n    return f'Hello, {name}'\n\n"
        "if __name__ == '__main__':\n    print(greet('world'))\n"
    )
    (repo / "utils.py").write_text(
        "def format_message(msg):\n    return msg.strip().upper()\n\n"
        "def helper(x):\n    return x * 2\n"
    )

    # Stage to avoid untracked warnings
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)

    return repo
