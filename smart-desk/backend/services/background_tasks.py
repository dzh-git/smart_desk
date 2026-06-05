"""Background maintenance tasks: service call timeout, translation cleanup, logging setup."""
from __future__ import annotations
import asyncio
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


# ── Logging Setup ──

def setup_file_logging(log_dir: str = "logs", level: int = logging.INFO):
    """Configure file logging with daily rotation."""
    global _logger

    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)

    logger = logging.getLogger("smartdesk")
    logger.setLevel(level)

    # Only add handler if one for this file path is not already present
    target_file = str(log_path / "smartdesk.log")
    if not any(
        isinstance(h, TimedRotatingFileHandler) and h.baseFilename == target_file
        for h in logger.handlers
    ):
        # Daily rotation at midnight, keep 180 days of backups
        handler = TimedRotatingFileHandler(
            log_path / "smartdesk.log",
            when="midnight",
            interval=1,
            backupCount=180,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)

    _logger = logger
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
