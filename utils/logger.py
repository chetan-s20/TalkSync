"""Centralized logging for TalkSync Pro."""
import logging
import sys
from pathlib import Path
from typing import Optional


LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _setup_file_handler(log_dir: str = "logs") -> logging.FileHandler:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(
        str(Path(log_dir) / "talksync.log"), encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    return handler


def _setup_console_handler() -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    return handler


_logger_initialized = False
_current_level = logging.INFO


def get_logger(name: str) -> logging.Logger:
    global _logger_initialized
    logger = logging.getLogger(name)
    if not _logger_initialized:
        root = logging.getLogger()
        root.setLevel(_current_level)
        root.addHandler(_setup_console_handler())
        root.addHandler(_setup_file_handler())
        root.propagate = False
        _logger_initialized = True
    logger.setLevel(_current_level)
    return logger


def set_level(level_name: str) -> None:
    global _current_level
    _current_level = LOG_LEVELS.get(level_name.upper(), logging.INFO)
    logging.getLogger().setLevel(_current_level)
