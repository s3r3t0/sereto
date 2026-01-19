"""Centralized Loguru logger setup for SeReTo."""

from __future__ import annotations

import os
import pathlib
from enum import StrEnum

import click
import jinja2
import loguru
import pydantic
import pypdf
from rich.markup import escape
from rich.traceback import Traceback

from sereto.cli.utils import Console


class LogLevel(StrEnum):
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


DEFAULT_LOG_LEVEL = LogLevel.INFO
LEVEL_STYLES = {
    LogLevel.TRACE: "bright_black",
    LogLevel.DEBUG: "cyan",
    LogLevel.INFO: "white",
    LogLevel.SUCCESS: "green",
    LogLevel.WARNING: "yellow",
    LogLevel.ERROR: "red",
    LogLevel.CRITICAL: "bold red",
}

_console = Console()


def _resolve_level(level: LogLevel | None) -> LogLevel:
    """Resolve the effective log level from CLI arg or environment."""
    if level is None:
        try:
            level = LogLevel(os.getenv("SERETO_LOG_LEVEL", ""))
        except ValueError:
            level = None
    if level is None and os.getenv("DEBUG") == "1":
        level = LogLevel.DEBUG
    if level is None:
        level = DEFAULT_LOG_LEVEL

    return level


def setup_logging(level: LogLevel | None = None) -> None:
    """Configure Loguru to emit logs through Rich's console.log."""

    def _rich_sink(message: loguru.Message) -> None:
        record = message.record
        level_name: str = record["level"].name
        markup = record.get("extra", {}).get("markup", False)
        try:
            log_level = LogLevel(level_name)
        except ValueError:
            log_level = LogLevel.INFO
        level_style = LEVEL_STYLES.get(log_level, "white")
        rendered_message = escape(record["message"]) if not markup else record["message"]
        decorated = f"[{level_style}]{rendered_message}[/]"
        _console.log(decorated, markup=True, _stack_offset=6)  # TODO: cleaner solution for stack offset?

        if (exc := record["exception"]) is not None:
            exc_type, exc_value, exc_traceback = exc.type, exc.value, exc.traceback
            if exc_type is None or exc_value is None or exc_traceback is None:
                return
            tb = Traceback.from_exception(
                exc_type,
                exc_value,
                exc_traceback,
                show_locals=os.getenv("DEBUG", "0") == "1",
                suppress=[loguru, click, jinja2, pathlib, pydantic, pypdf],
                width=_console.width,
                code_width=120,
            )
            _console.print(tb)

    loguru.logger.remove()
    loguru.logger.add(_rich_sink, level=_resolve_level(level), format="{message}", colorize=False, enqueue=False)


# Re-export configured logger for convenience
logger = loguru.logger

__all__ = ["logger", "LogLevel", "setup_logging"]
