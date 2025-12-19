import functools
import os
import sys
from collections.abc import Callable

from pydantic import ValidationError

from sereto.logging import logger


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
    """Decorator for pretty printing SeReTo exceptions in debug mode

    If the exception is a subclass of SeretoException and DEBUG environment variable is set to '1', the full exception
    traceback will be printed with local variables shown.
    """

    @functools.wraps(func)
    def outer_function(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if isinstance(e, SeretoException | ValidationError):
                logger.error(str(e))
            else:
                logger.error("Unexpected error occurred")

            if os.environ.get("DEBUG", "0") == "1":
                logger.opt(exception=e).exception("Debug traceback")
            else:
                logger.info("Set environment variable [blue]DEBUG=1[/] for more details.", markup=True)
            sys.exit(1)

    return outer_function
