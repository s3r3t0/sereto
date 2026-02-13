import functools
from collections.abc import Callable

from pydantic import ValidationError

from sereto.logging import get_log_config, logger


class SeretoException(Exception):
    """There was an ambiguous exception."""


class SeretoEncryptionError(SeretoException):
    """Encryption error."""


class SeretoPathError(SeretoException):
    """Path error."""


class SeretoRuntimeError(SeretoException):
    """Runtime error."""


class SeretoTypeError(SeretoException):
    """Type error."""


class SeretoValueError(SeretoException, ValueError):
    """Value error."""


class SeretoCalledProcessError(SeretoException):
    """Called process error."""


def handle_exceptions[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Decorator for pretty printing SeReTo exceptions."""

    @functools.wraps(func)
    def outer_function(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except SystemExit:
            raise
        except KeyboardInterrupt:
            logger.warning("Operation interrupted by user")
            raise SystemExit(1) from None
        except (SeretoException, ValidationError) as e:
            logger.error(str(e))
            _log_debug_traceback(e)
            raise SystemExit(1) from None
        except Exception as e:
            logger.error("Unexpected error occurred: {}", type(e).__name__)
            _log_debug_traceback(e)
            raise SystemExit(1) from None

    return outer_function


def _log_debug_traceback(e: Exception) -> None:
    """Log debug traceback if configured, otherwise hint the user."""
    config = get_log_config()

    if config.show_exceptions:
        logger.opt(exception=e).exception("Debug traceback")
    else:
        logger.info("Increase the log level for more details.")
