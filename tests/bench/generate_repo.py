"""Generate a synthetic Python repo with N files for stress testing."""

import argparse
from pathlib import Path


def generate_repo(target: str, num_files: int, classes_per_file: int = 3,
                  methods_per_class: int = 5):
    """Generate a synthetic Python project for benchmarking.

    Args:
        target: Output directory.
        num_files: Number of .py files to generate.
        classes_per_file: Classes per file.
        methods_per_class: Methods per class.
    """
    root = Path(target)
    root.mkdir(parents=True, exist_ok=True)

    for i in range(num_files):
        module = f"module_{i:04d}"
        file_path = root / f"{module}.py"
        lines = []
        # Imports: each file imports the previous 2 modules
        if i >= 2:
            lines.append(f"from module_{i-2:04d} import *  # noqa: F403")
        if i >= 1:
            lines.append(f"import module_{i-1:04d}")
        lines.append("")

        for c in range(classes_per_file):
            class_name = f"Class{i:04d}_{c}"
            lines.append(f"class {class_name}:")
            lines.append(f'    """Auto-generated class {class_name}."""')
            lines.append("")
            for m in range(methods_per_class):
                method_name = f"method_{m}"
                lines.append(f"    def {method_name}(self, x: int) -> int:")
                lines.append(f'        """Return x + {i + c + m}."""')
                lines.append(f"        return x + {i + c + m}")
                lines.append("")

        file_path.write_text("\n".join(lines))

    # Write a main entry point that imports all modules
    main_lines = ['"""Auto-generated stress test entry point."""', ""]
    for i in range(num_files):
        main_lines.append(f"import module_{i:04d}  # noqa: F401")
    (root / "__init__.py").write_text("")
    (root / "main.py").write_text("\n".join(main_lines))

    print(f"Generated {num_files} files in {target}")
    print(f"  Classes: {num_files * classes_per_file}")
    print(f"  Methods: {num_files * classes_per_file * methods_per_class}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic Python repo")
    parser.add_argument("target", help="Output directory")
    parser.add_argument("--files", "-n", type=int, default=1000,
                        help="Number of files (default: 1000)")
    parser.add_argument("--classes", "-c", type=int, default=3,
                        help="Classes per file (default: 3)")
    parser.add_argument("--methods", "-m", type=int, default=5,
                        help="Methods per class (default: 5)")
    args = parser.parse_args()
    generate_repo(args.target, args.files, args.classes, args.methods)
