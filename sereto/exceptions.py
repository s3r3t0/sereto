import functools
import os
import pathlib
import sys
from collections.abc import Callable
from typing import ParamSpec, TypeVar

import click
import jinja2
import pydantic
import pypdf
from pydantic import ValidationError
from rich.markup import escape

from sereto.cli.utils import Console


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


P = ParamSpec("P")
R = TypeVar("R")


def handle_exceptions(func: Callable[P, R]) -> Callable[P, R]:
    """Decorator for pretty printing SeReTo exceptions in debug mode.

    If the exception is a subclass of SeretoException and DEBUG environment variable is set to '1', the full exception
    traceback will be printed with local variables shown.
    """

    @functools.wraps(func)
    def outer_function(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if isinstance(e, SeretoException | ValidationError):
                Console().print(f"[red]Error:[/red] {escape(str(e))}")
            if os.environ.get("DEBUG", "0") == "1":
                Console().print_exception(show_locals=True, suppress=[click, jinja2, pathlib, pydantic, pypdf])
            else:
                Console().print("\n[yellow]Set environment variable [blue]DEBUG=1[/blue] for more details.")
            sys.exit(1)

    return outer_function
