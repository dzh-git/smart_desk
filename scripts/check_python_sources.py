"""Compile every Git-tracked Python source as UTF-8 without scanning venvs."""
from __future__ import annotations

import subprocess
import sys
import tokenize
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "*.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print("PYTHON_STATIC_CHECK_FAILED: git ls-files", file=sys.stderr)
        return 1
    paths = [
        ROOT / line
        for line in result.stdout.splitlines()
        if line.strip()
    ]
    failures: list[str] = []
    for path in paths:
        try:
            with tokenize.open(path) as stream:
                source = stream.read()
            compile(source, str(path), "exec", dont_inherit=True)
        except (OSError, SyntaxError, UnicodeError) as error:
            failures.append(f"{path.relative_to(ROOT)}: {error}")
    if failures:
        print("PYTHON_STATIC_CHECK_FAILED", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print(f"PYTHON_STATIC_CHECK_OK: {len(paths)} tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
