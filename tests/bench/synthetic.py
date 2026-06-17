"""Synthetic project generator for benchmark stress testing.

Generates a configurable number of Python files with realistic function/class
definitions and cross-file import relationships. Used by the benchmark suite
to measure indexing performance at scale without external dependencies.

Complexity Control
------------------
Since iter-62, the generator supports controlled cyclomatic complexity
distribution via the ``complexity_profile`` parameter. Six profiles are
available (see :func:`generate_synthetic_project`), each targeting a
different distribution of complexity ranks (A-F per radon/ISO):

+---------+-------+-------+-------+-------+-------+------+
| Profile |  A%   |  B%   |  C%   |  D%   |  E%   |  F%  |
+=========+=======+=======+=======+=======+=======+======+
| flat    | 100%  |  0%   |  0%   |  0%   |  0%   |  0%  |
+---------+-------+-------+-------+-------+-------+------+
| typical |  60%  |  20%  |  10%  |   5%  |   3%  |  2%  |
+---------+-------+-------+-------+-------+-------+------+
| complex |  20%  |  20%  |  25%  |  15%  |  10%  | 10%  |
+---------+-------+-------+-------+-------+-------+------+

All profiles are reproducible (fixed random seed) and produce the same
total number of symbols for a given ``num_files × symbols_per_file``.
"""

import random
import string
from pathlib import Path
from typing import Optional

# ── Complexity profiles ──────────────────────────────────────────────
# Each profile maps rank→probability. Ranks map to cyclomatic complexity:
#   A: 1–5   B: 6–10   C: 11–20   D: 21–30   E: 31–40   F: 41+
COMPLEXITY_PROFILES: dict[str, dict[str, float]] = {
    "flat":    {"A": 1.0, "B": 0.0, "C": 0.0, "D": 0.0, "E": 0.0, "F": 0.0},
    "typical": {"A": 0.6, "B": 0.2, "C": 0.1, "D": 0.05, "E": 0.03, "F": 0.02},
    "complex": {"A": 0.2, "B": 0.2, "C": 0.25, "D": 0.15, "E": 0.1, "F": 0.1},
}

# Complexity → target score range (midpoint used for generation)
_RANK_TARGETS: dict[str, tuple[int, int]] = {
    "A": (1, 5), "B": (6, 10), "C": (11, 20),
    "D": (21, 30), "E": (31, 40), "F": (41, 55),
}


def _random_name(min_len: int = 3, max_len: int = 20) -> str:
    """Generate a random Python identifier."""
    length = random.randint(min_len, max_len)
    first = random.choice(string.ascii_lowercase + "_")
    rest = ''.join(
        random.choice(string.ascii_lowercase + string.digits + "_")
        for _ in range(length - 1)
    )
    return first + rest


def _pick_rank(profile: dict[str, float]) -> str:
    """Pick a complexity rank according to the profile probabilities."""
    r = random.random()
    cumulative = 0.0
    for rank in ("A", "B", "C", "D", "E", "F"):
        cumulative += profile.get(rank, 0.0)
        if r < cumulative:
            return rank
    return "F"


def _generate_function_with_complexity(
    name: str,
    target_rank: str,
    known_names: Optional[list[str]] = None,
    num_calls: int = 2,
) -> str:
    """Generate a function with a target cyclomatic complexity rank.

    Produces a function with enough ``if/elif/else`` branches to reach the
    target complexity range for *rank*.  Also sprinkles in cross-file calls
    when *known_names* is provided.
    """
    low, high = _RANK_TARGETS.get(target_rank, (1, 5))
    target_complexity = random.randint(low, high)
    # Each if/elif/else block adds 1 to cyclomatic complexity (base = 1)
    num_branches = max(0, target_complexity - 1)

    lines = [f"def {name}():"]

    # Add cross-file calls if available (doesn't increase complexity)
    call_targets: list[str] = []
    if known_names and num_calls > 0:
        available = [n for n in known_names if n != name]
        if available:
            call_targets = random.sample(
                available, min(num_calls, len(available))
            )

    if num_branches == 0:
        # Flat function
        if call_targets:
            for c in call_targets:
                lines.append(f"    {c}()")
            lines.append("    return True")
        else:
            lines.append("    return True")
    else:
        # Generate branching structure
        for i in range(num_branches):
            if i == 0:
                lines.append(f"    if x_{i} > 0:")
            elif i < num_branches - 1:
                lines.append(f"    elif x_{i} > 0:")
            else:
                lines.append("    else:")

            # Body: call a target or do simple arithmetic
            indent = "        "
            if call_targets and i < len(call_targets):
                lines.append(f"{indent}{call_targets[i]}()")
            else:
                lines.append(f"{indent}y = x_{max(0, i-1)} + {i}")

        lines.append("    return y" if num_branches > 0 else "    return True")

    return '\n'.join(lines)


def _generate_function(name: str, num_calls: int = 2, known_names: Optional[list[str]] = None) -> str:
    """Generate a simple function (complexity rank A, backward-compatible)."""
    return _generate_function_with_complexity(
        name, target_rank="A", known_names=known_names, num_calls=num_calls
    )


def _generate_class(
    name: str,
    num_methods: int = 3,
    known_names: Optional[list[str]] = None,
    profile: dict[str, float] | None = None,
) -> str:
    """Generate a class with methods that follow the complexity profile."""
    lines = [f"class {name}:"]
    if num_methods == 0:
        lines.append("    pass")
        return '\n'.join(lines)

    for _i in range(num_methods):
        mname = f"{name}_{_random_name(3, 10)}"
        # Generate method body following the same complexity profile
        rank = _pick_rank(profile) if profile else "A"
        fn_body = _generate_function_with_complexity(
            mname, target_rank=rank,
            known_names=known_names,
            num_calls=random.randint(0, 2),
        )
        # Indent the function body into the class
        for j, line in enumerate(fn_body.split('\n')):
            if j == 0:
                lines.append(f"    {line}")
            else:
                lines.append(f"    {line}")
    return '\n'.join(lines)


def generate_synthetic_project(
    root: str | Path,
    num_files: int = 1000,
    symbols_per_file: int = 8,
    edge_density: float = 0.3,
    language: str = "python",
    seed: int = 42,
    num_dirs: int = 20,
    complexity_profile: str = "flat",
) -> Path:
    """Generate a synthetic project with configurable scale and complexity.

    Args:
        root: Directory to create the project in.
        num_files: Number of source files to generate.
        symbols_per_file: Average number of functions/classes per file.
        edge_density: Probability of cross-file symbol references (0.0-1.0).
        language: Target language ('python' supported; others TBD).
        seed: Random seed for reproducibility.
        num_dirs: Number of subdirectories to distribute files across.
        complexity_profile: Complexity distribution profile name.
            ``"flat"`` (default) — all rank A (1–5), simple functions.
            ``"typical"`` — 60% A, 20% B, 10% C, 5% D, 3% E, 2% F.
            ``"complex"`` — 20% A, 20% B, 25% C, 15% D, 10% E, 10% F.

    Returns:
        Path to the generated project root.
    """
    random.seed(seed)
    project_root = Path(root)
    project_root.mkdir(parents=True, exist_ok=True)

    profile = COMPLEXITY_PROFILES.get(complexity_profile, COMPLEXITY_PROFILES["flat"])

    # Pre-generate the global symbol name pool
    total_symbols = num_files * symbols_per_file
    symbol_names: list[str] = []
    for _ in range(total_symbols):
        symbol_names.append(_random_name(3, 20))

    # Create subdirectories
    dirs: list[Path] = []
    for i in range(num_dirs):
        d = project_root / f"pkg_{i:03d}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "__init__.py").write_text("# auto-generated\n")
        dirs.append(d)

    # Distribute files across directories
    symbol_idx = 0

    for file_idx in range(num_files):
        d = dirs[file_idx % num_dirs]
        fpath = d / f"mod_{file_idx:05d}.py"

        lines = []
        # Module docstring
        lines.append(f'"""Module {file_idx} — auto-generated benchmark target (profile={complexity_profile})."""')
        lines.append("")

        # Imports: reference symbols from other modules
        if edge_density > 0 and file_idx > 0:
            num_imports = max(1, int(symbols_per_file * edge_density))
            # Pick symbols from previously generated modules
            available = symbol_names[:symbol_idx]
            if available:
                imported = random.sample(
                    available,
                    min(num_imports, len(available))
                )
                for imp in imported:
                    if random.random() < 0.5:
                        lines.append(f"from other_module import {imp}  # cross-ref")
                    else:
                        lines.append(f"# reference: {imp}")

        lines.append("")

        # Generate symbols for this file
        file_symbols: list[str] = []
        num_symbols = random.randint(
            max(1, symbols_per_file - 2),
            symbols_per_file + 2
        )

        for _ in range(num_symbols):
            if symbol_idx >= len(symbol_names):
                break
            name = symbol_names[symbol_idx]
            symbol_idx += 1
            file_symbols.append(name)

            is_class = random.random() < 0.2  # 20% classes
            if is_class:
                lines.append(_generate_class(name, num_methods=random.randint(1, 4),
                                            known_names=symbol_names[:symbol_idx],
                                            profile=profile))
            else:
                rank = _pick_rank(profile)
                lines.append(_generate_function_with_complexity(
                    name, target_rank=rank,
                    known_names=symbol_names[:symbol_idx],
                    num_calls=random.randint(0, 3),
                ))
            lines.append("")

        # Ensure file has at least pass if empty
        if not file_symbols:
            lines.append("x = 1")

        fpath.write_text('\n'.join(lines))

    # Create a .gitignore for realism
    (project_root / ".gitignore").write_text("__pycache__/\n*.pyc\n")

    return project_root


# ── Standalone test entry point ──
if __name__ == "__main__":
    import tempfile
    import time

    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.perf_counter()
        root = generate_synthetic_project(tmp, num_files=100, symbols_per_file=8)
        elapsed = time.perf_counter() - t0

        py_files = list(Path(root).rglob("*.py"))
        total_lines = sum(len(f.read_text().splitlines()) for f in py_files)

        print(f"Generated {len(py_files)} files in {elapsed:.2f}s")
        print(f"Total lines: {total_lines}")
        print(f"Root: {root}")
