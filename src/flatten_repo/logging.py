from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pathlib import Path

_LOGGING_CONFIGURED = False


def setup_logging(filename: str | Path | None = None) -> structlog.BoundLogger:
    """Set up structured logging for the flatten_repo module.

    Args:
        filename: Optional path to a log file. If None, logs are written to stderr.

    Returns:
        A structlog logger instance configured for the flatten_repo module.
    """
    global _LOGGING_CONFIGURED  # noqa: PLW0603
    if not _LOGGING_CONFIGURED:
        handlers: list[logging.Handler] = []
        if filename:
            handlers.append(logging.FileHandler(str(filename), encoding="utf-8"))
        else:
            handlers.append(logging.StreamHandler(sys.stderr))

        logging.basicConfig(
            level=logging.INFO,
            handlers=handlers,
            format="%(message)s",
        )
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level,
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        _LOGGING_CONFIGURED = True

    return structlog.get_logger("flatten_repo")


logger = setup_logging()
