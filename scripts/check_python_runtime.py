"""Fail closed when SmartDesk is started with an unsupported Python."""
from __future__ import annotations

import sys


REQUIRED_VERSION = (3, 11)


def main() -> int:
    actual = sys.version_info[:2]
    executable = sys.executable
    if actual != REQUIRED_VERSION:
        print(
            "SMARTDESK_PYTHON_UNSUPPORTED: "
            f"required 3.11, got {actual[0]}.{actual[1]} at {executable}",
            file=sys.stderr,
        )
        return 1
    print(f"SMARTDESK_PYTHON_OK: {sys.version.split()[0]} at {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
