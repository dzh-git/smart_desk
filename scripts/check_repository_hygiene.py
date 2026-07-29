"""Fail when Git tracks secrets, local device config, models, or build output."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {
    ".aab",
    ".apk",
    ".db",
    ".jks",
    ".keystore",
    ".onnx",
    ".p12",
    ".pfx",
    ".pt",
    ".pth",
    ".sqlite",
    ".sqlite3",
    ".tflite",
}
FORBIDDEN_EXACT_PATHS = {
    "config/smartdesk.integration.json",
}
FORBIDDEN_PARTS = {
    "node_modules",
    "__pycache__",
    ".gradle",
    ".pio",
    ".smartdesk-runtime",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r'(?i)"(?:deviceToken|token)"\s*:\s*"'
        r'(?!<|replace-|example-|test-|fixture-|'
        r'unique-device-token-|unique-random-token-)([^"]{20,})"'
    ),
)


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("git ls-files failed")
    return [
        item.decode("utf-8", errors="strict").replace("\\", "/")
        for item in result.stdout.split(b"\0")
        if item
    ]


def main() -> int:
    problems: list[str] = []
    for relative in tracked_files():
        path = ROOT / relative
        if not path.is_file():
            continue
        parts = set(Path(relative).parts)
        suffix = path.suffix.lower()
        if relative in FORBIDDEN_EXACT_PATHS:
            problems.append(f"local runtime config is tracked: {relative}")
        if suffix in FORBIDDEN_SUFFIXES:
            problems.append(f"binary/runtime artifact is tracked: {relative}")
        if parts & FORBIDDEN_PARTS:
            problems.append(f"generated directory is tracked: {relative}")
        if path.is_file() and path.stat().st_size > 20 * 1024 * 1024:
            problems.append(f"tracked file exceeds 20 MiB: {relative}")
        if path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                problems.append(f"suspected secret in tracked file: {relative}")
                break

    if problems:
        print("REPOSITORY_HYGIENE_FAILED")
        for problem in sorted(set(problems)):
            print(f"- {problem}")
        return 1
    print("REPOSITORY_HYGIENE_OK")
    print("No tracked database, model, package, private key, or live device config.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
