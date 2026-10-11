"""structlog configuration. Stdlib loggers (uvicorn, duckdb, mcp) share the formatter."""

import logging
import sys
from typing import TextIO

import structlog
from structlog.typing import Processor

from app.core.config import LogFormat, LogLevel


def configure_logging(level: LogLevel, fmt: LogFormat, stream: TextIO | None = None) -> None:
    """Route every log line through structlog with the request context merged in.

    `stream` defaults to stdout; the MCP stdio server passes stderr, because its
    stdout carries protocol frames only.
    """
    out = stream or sys.stdout
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=out.isatty())
    )
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
        foreign_pre_chain=shared,
    )
    handler = logging.StreamHandler(out)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # The request-id middleware logs every request; uvicorn's access log would duplicate it.
    logging.getLogger("uvicorn.access").disabled = True
