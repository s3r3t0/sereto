"""Centralized Loguru logger setup for SeReTo."""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
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


@dataclass
class LogConfig:
    level: LogLevel

    @property
    def show_exceptions(self) -> bool:
        return self.level in {LogLevel.DEBUG, LogLevel.TRACE}

    @property
    def show_locals(self) -> bool:
        return self.level == LogLevel.TRACE


def _resolve_level(level: LogLevel | None) -> LogLevel:
    """Resolve log level from argument or SERETO_LOG_LEVEL / DEBUG environment variables."""
    if level is not None:
        return level

    env_level = os.getenv("SERETO_LOG_LEVEL")
    if env_level is not None:
        try:
            return LogLevel(env_level.upper())
        except ValueError:
            pass

    if os.getenv("DEBUG", "0").strip() in {"1", "true", "yes"}:
        return LogLevel.DEBUG

    return DEFAULT_LOG_LEVEL


_current_config: LogConfig | None = None


def is_logging_configured() -> bool:
    """Check whether logging has been configured via `setup_logging`."""
    return _current_config is not None


def get_log_config() -> LogConfig:
    """Return the current logging configuration.

    If `setup_logging` has not been called yet, returns a default configuration with INFO level.
    """
    if _current_config is None:
        return LogConfig(level=DEFAULT_LOG_LEVEL)
    return _current_config


def setup_logging(level: LogLevel | None = None) -> LogConfig:
    """Configure Loguru to emit logs through Rich's console.log."""
    global _current_config
    effective_level = _resolve_level(level)
    config = LogConfig(level=effective_level)
    _current_config = config

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
                show_locals=config.show_locals,
                suppress=[loguru, click, jinja2, pathlib, pydantic, pypdf],
                width=_console.width,
                code_width=120,
            )
            _console.print(tb)

    loguru.logger.remove()
    loguru.logger.add(_rich_sink, level=config.level, format="{message}", colorize=False, enqueue=False)
    return config


# Re-export configured logger for convenience
logger = loguru.logger

__all__ = ["LogConfig", "LogLevel", "get_log_config", "is_logging_configured", "logger", "setup_logging"]
