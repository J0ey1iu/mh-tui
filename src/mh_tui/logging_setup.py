"""Logging configuration for the mh-tui client.

Writes logs to the resolved config dir (default ``~/.minimal_harness/log/``)
with daily rotation. Service-mode logging (``setup_service_logging``) lives
in ``minimal_harness.client.logging_setup`` and is shared across all SDK
consumers — that is intentionally not exported here.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from minimal_harness.log_utils import CorrelationFilter


def _get_log_dir() -> Path:
    from mh_tui.config.paths import get_config_dir

    return get_config_dir() / "log"


_FORMAT = "%(asctime)s | %(name)s | %(levelname)-8s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_LOG_LEVEL_MAP: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _resolve_level(level: str | int | None) -> int:
    if level is None:
        return logging.INFO
    if isinstance(level, int):
        return level
    return _LOG_LEVEL_MAP.get(level.upper(), logging.INFO)


def setup_logging(level: str | int | None = None) -> None:
    """Configure root logger for the TUI.

    Idempotent — if root logger already has handlers, this function is a
    no-op. This allows callers who configure logging themselves to bypass
    this setup.

    Writes to ``{config_dir}/log/tui.log`` and ``{config_dir}/log/error.log``
    with daily rotation.
    """
    log_dir = _get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    resolved_level = _resolve_level(
        level if level is not None else os.environ.get("MH_LOG_LEVEL", "INFO")
    )
    root_logger.setLevel(resolved_level)
    root_logger.addFilter(CorrelationFilter())

    handler = TimedRotatingFileHandler(
        filename=log_dir / "tui.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    handler.setLevel(resolved_level)
    handler.setFormatter(logging.Formatter(_FORMAT, _DATE_FORMAT))
    root_logger.addHandler(handler)

    error_handler = TimedRotatingFileHandler(
        filename=log_dir / "error.log",
        when="midnight",
        interval=1,
        backupCount=60,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(_FORMAT, _DATE_FORMAT))
    root_logger.addHandler(error_handler)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(logging.Formatter(_FORMAT, _DATE_FORMAT))
    root_logger.addHandler(stderr_handler)

    logging.getLogger(__name__).info("Logging initialised — log_dir=%s", log_dir)
