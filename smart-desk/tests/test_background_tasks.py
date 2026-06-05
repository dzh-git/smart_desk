"""Tests for background_tasks module."""
from __future__ import annotations
import tempfile
import os
import pytest
from pathlib import Path


class TestSetupFileLogging:
    """Test file logging setup."""

    def test_setup_file_logging_creates_log_dir_and_file(self):
        """Verify setup_file_logging creates log directory and log file."""
        from backend.services.background_tasks import setup_file_logging

        tmpdir = tempfile.mkdtemp()
        try:
            log_dir = os.path.join(tmpdir, "test_logs")
            logger = setup_file_logging(log_dir=log_dir)

            try:
                # Verify directory was created
                assert os.path.isdir(log_dir)

                # TimedRotatingFileHandler defers file creation until first write
                logger.info("test log message")

                # Verify log file now exists
                log_file = os.path.join(log_dir, "smartdesk.log")
                assert os.path.exists(log_file)
            finally:
                # Close handlers to release file locks on Windows
                for handler in logger.handlers[:]:
                    handler.close()
                    logger.removeHandler(handler)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_setup_file_logging_returns_logger(self):
        """Verify setup_file_logging returns a logger instance."""
        import logging
        from backend.services.background_tasks import setup_file_logging

        tmpdir = tempfile.mkdtemp()
        try:
            logger = setup_file_logging(log_dir=tmpdir)
            try:
                assert isinstance(logger, logging.Logger)
                assert logger.name == "smartdesk"
            finally:
                for handler in logger.handlers[:]:
                    handler.close()
                    logger.removeHandler(handler)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestGetLogger:
    """Test get_logger singleton."""

    def test_get_logger_returns_same_instance(self):
        """Verify get_logger returns the same logger instance."""
        from backend.services.background_tasks import get_logger
        import logging

        # Reset the module-level singleton for testing
        import backend.services.background_tasks as bt
        bt._logger = None

        tmpdir = tempfile.mkdtemp()
        # Override default log_dir so it uses a temp dir
        import backend.services.background_tasks as bt2
        original_setup = bt2.setup_file_logging

        def _setup_to_tmp(log_dir="logs", level=logging.INFO):
            return original_setup(log_dir=tmpdir, level=level)

        bt2.setup_file_logging = _setup_to_tmp

        try:
            logger1 = get_logger()
            logger2 = get_logger()
            assert logger1 is logger2
            assert isinstance(logger1, logging.Logger)
            assert logger1.name == "smartdesk"
        finally:
            bt2.setup_file_logging = original_setup
            bt2._logger = None
            # Close handlers
            for handler in logger1.handlers[:]:
                handler.close()
                logger1.removeHandler(handler)
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_duplicate_handlers_when_setup_then_get_logger(self):
        """SR-001: setup_file_logging() then get_logger() should not add duplicate handlers."""
        from backend.services.background_tasks import setup_file_logging, get_logger
        import logging

        # Reset the module-level singleton for testing
        import backend.services.background_tasks as bt
        bt._logger = None

        tmpdir = tempfile.mkdtemp()
        try:
            # Step 1: call setup_file_logging directly (as main.py lifespan does)
            logger1 = setup_file_logging(log_dir=tmpdir)
            assert logger1 is not None

            # Step 2: call get_logger() — should NOT add a second handler
            logger2 = get_logger()
            assert logger1 is logger2

            # Count RotatingFileHandler / TimedRotatingFileHandler instances
            from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
            file_handlers = [h for h in logger1.handlers
                             if isinstance(h, (RotatingFileHandler, TimedRotatingFileHandler))]
            assert len(file_handlers) == 1, (
                f"Expected 1 file handler, got {len(file_handlers)}. "
                f"setup_file_logging + get_logger should not duplicate handlers."
            )
        finally:
            for handler in logger1.handlers[:]:
                handler.close()
                logger1.removeHandler(handler)
            bt._logger = None
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_handler_uses_timed_daily_rotation(self):
        """SR-002: File logging must use TimedRotatingFileHandler for daily rotation."""
        from backend.services.background_tasks import setup_file_logging
        from logging.handlers import TimedRotatingFileHandler

        # Reset the module-level singleton for testing
        import backend.services.background_tasks as bt
        bt._logger = None

        tmpdir = tempfile.mkdtemp()
        try:
            logger = setup_file_logging(log_dir=tmpdir)
            # Verify a TimedRotatingFileHandler is in the handlers
            timed_handlers = [h for h in logger.handlers
                              if isinstance(h, TimedRotatingFileHandler)]
            assert len(timed_handlers) >= 1, (
                f"Expected at least 1 TimedRotatingFileHandler, got {len(timed_handlers)}. "
                f"Daily rotation requires TimedRotatingFileHandler, not RotatingFileHandler."
            )
        finally:
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)
            bt._logger = None
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestServiceCallTimeoutLoop:
    """Test service_call_timeout_loop."""

    def test_import_does_not_fail(self):
        """Verify the function can be imported without errors."""
        from backend.services.background_tasks import service_call_timeout_loop
        assert callable(service_call_timeout_loop)


class TestTranslationCleanupLoop:
    """Test translation_cleanup_loop."""

    def test_import_does_not_fail(self):
        """Verify the function can be imported without errors."""
        from backend.services.background_tasks import translation_cleanup_loop
        assert callable(translation_cleanup_loop)
