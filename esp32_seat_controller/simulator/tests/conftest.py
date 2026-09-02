from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DESK_ROOT = ROOT / "new_coding_desk"
for path in (ROOT, DESK_ROOT):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)
