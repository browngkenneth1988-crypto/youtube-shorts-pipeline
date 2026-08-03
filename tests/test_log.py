"""Tests for verticals/log.py — logger singleton + verbosity toggle."""

import logging

from verticals import log as logmod


def _console_handler(logger):
    for h in logger.handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            return h
    return None


class TestGetLogger:
    def test_returns_singleton(self):
        first = logmod.get_logger()
        second = logmod.get_logger()
        assert first is second

    def test_named_pipeline(self):
        assert logmod.get_logger().name == "pipeline"


class TestSetVerbose:
    def test_toggles_console_level(self):
        logmod.set_verbose(True)
        console = _console_handler(logmod.get_logger())
        assert console is not None
        assert console.level == logging.DEBUG

        logmod.set_verbose(False)
        assert console.level == logging.INFO

    def test_file_handler_stays_debug(self):
        logmod.set_verbose(False)
        logger = logmod.get_logger()
        file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        for fh in file_handlers:
            assert fh.level == logging.DEBUG


class TestLog:
    def test_log_emits_info(self, caplog):
        with caplog.at_level(logging.INFO, logger="pipeline"):
            logmod.log("hello from test")
        assert "hello from test" in caplog.text
