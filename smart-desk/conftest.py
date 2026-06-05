import os
import tempfile
from pathlib import Path


TEST_TMP_DIR = Path(tempfile.gettempdir()) / "smart_desk_tests"
TEST_TMP_DIR.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEST_TMP_DIR)

_mkdtemp_counter = 0


def _stable_mkdtemp(suffix=None, prefix=None, dir=None):
    """Create test temp dirs with normal writable ACLs on this Windows setup."""
    global _mkdtemp_counter
    _mkdtemp_counter += 1
    base = Path(dir) if dir else TEST_TMP_DIR
    base.mkdir(parents=True, exist_ok=True)
    name = f"{prefix or 'tmp'}{os.getpid()}_{_mkdtemp_counter}{suffix or ''}"
    path = base / name
    path.mkdir()
    return str(path)


tempfile.mkdtemp = _stable_mkdtemp

TEST_DB_PATH = TEST_TMP_DIR / f"test_smart_desk_{os.getpid()}.db"
TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
for suffix in ("", "-journal", "-wal", "-shm"):
    (TEST_DB_PATH.parent / f"{TEST_DB_PATH.name}{suffix}").unlink(missing_ok=True)

os.environ.setdefault("SMART_DESK_DB_PATH", str(TEST_DB_PATH))
