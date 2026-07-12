import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import structlog

_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def configure_logging(level: str = "INFO") -> None:
    numeric_level = _LEVEL_MAP.get(level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=numeric_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


@contextmanager
def bind_run_id(run_id: str) -> Iterator[None]:
    structlog.contextvars.bind_contextvars(run_id=run_id)
    try:
        yield
    finally:
        structlog.contextvars.unbind_contextvars("run_id")
