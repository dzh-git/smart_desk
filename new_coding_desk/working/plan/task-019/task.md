# Task 019: Service Call Timeout + File Logging + Translation Cleanup

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite

## Task Objective

Implement three P2 enhancements: (C2) Service call 5-minute timeout auto-cancel, (C3) Translation history 180-day retention cleanup, (C4) File logging to `logs/` directory with daily rotation. These are background tasks that run in the FastAPI lifespan.

This is Task 19 of 26.

---

**Files:**
- Create: `D:\learning\smart_desktop\smart-desk\backend\services\background_tasks.py`
- Modify: `D:\learning\smart_desktop\smart-desk\backend\main.py`
- Create directory: `D:\learning\smart_desktop\smart-desk\logs\`

- [ ] **Step 1: Create background_tasks.py**

```python
# backend/services/background_tasks.py
"""Background maintenance tasks: service call timeout, translation cleanup, logging setup."""
from __future__ import annotations
import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


# ── Logging Setup ──

def setup_file_logging(log_dir: str = "logs", level: int = logging.INFO):
    """Configure file logging with daily rotation."""
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)

    logger = logging.getLogger("smartdesk")
    logger.setLevel(level)

    # Rotating file handler (10 MB per file, 5 backup files)
    handler = RotatingFileHandler(
        log_path / "smartdesk.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(handler)
    return logger


_logger = None


def get_logger():
    global _logger
    if _logger is None:
        _logger = setup_file_logging()
    return _logger


# ── Service Call Timeout Task ──

async def service_call_timeout_loop(timeout_seconds: int = 300, interval: int = 30):
    """Periodic check: auto-cancel pending service calls older than timeout."""
    from backend.database import SessionLocal
    from backend.repositories.service_call_repository import ServiceCallRepository
    from backend.services.event_bus import event_bus
    from backend.services.event_bus import BaseEvent

    logger = get_logger()
    while True:
        await asyncio.sleep(interval)
        try:
            db = SessionLocal()
            try:
                repo = ServiceCallRepository(db)
                expired = repo.cancel_expired(timeout_seconds)
                for sc in expired:
                    event_bus.publish(BaseEvent(
                        name="service_call_cancelled",
                        payload={"call_id": sc.id, "reason": "TIMEOUT"},
                    ))
                    logger.info(f"Service call {sc.id} auto-cancelled (TIMEOUT)")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Service call timeout check failed: {e}")


# ── Translation Cleanup Task ──

async def translation_cleanup_loop(retention_days: int = 180, interval: int = 86400):
    """Daily cleanup: delete translation records older than retention_days."""
    from backend.database import SessionLocal
    from backend.repositories.translation_repository import TranslationRepository

    logger = get_logger()
    while True:
        await asyncio.sleep(interval)
        try:
            db = SessionLocal()
            try:
                repo = TranslationRepository(db)
                count = repo.cleanup_expired(retention_days)
                if count > 0:
                    logger.info(f"Cleaned up {count} expired translation records")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Translation cleanup failed: {e}")
```

- [ ] **Step 2: Register background tasks in main.py lifespan**

In `backend/main.py` lifespan function, add:
```python
from backend.services.background_tasks import (
    setup_file_logging,
    service_call_timeout_loop,
    translation_cleanup_loop,
)

# Setup file logging
setup_file_logging()

# Start background tasks
service_call_timeout_task = asyncio.create_task(service_call_timeout_loop(timeout_seconds=300))
translation_cleanup_task = asyncio.create_task(translation_cleanup_loop(retention_days=180))

yield

# Cleanup
service_call_timeout_task.cancel()
translation_cleanup_task.cancel()
```

- [ ] **Step 3: Create logs directory**

```bash
mkdir -p D:\learning\smart_desktop\smart-desk\logs
```

- [ ] **Step 4: Add logging to key events**

In `backend/services/seat_service.py`, add logging to state transitions:
```python
from backend.services.background_tasks import get_logger
logger = get_logger()

# In checkin, on_seat_occupied, etc.:
logger.info(f"Seat {seat_id} checkin: attendee_id={attendee_id}")
```

In `backend/services/serial_service.py` heartbeat timeout:
```python
logger.warning(f"Seat {seat_id} serial disconnected (heartbeat timeout)")
```

In `backend/services/ws_service.py` disconnect:
```python
logger.info(f"WebSocket disconnected: meeting_id={meeting_id}, seat_id={seat_id}")
```

- [ ] **Step 5: Verify background tasks run**

Run the backend and check:
```bash
cd D:\learning\smart_desktop\smart-desk && python -c "
from backend.main import app
# Check that logs/smartdesk.log is created
import os
assert os.path.exists('logs/smartdesk.log')
print('OK')
"
```
