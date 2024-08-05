import functools
import os
import pathlib
import sys
from collections.abc import Callable
from enum import Enum
from typing import Any, ParamSpec, TypeVar

import click
import jinja2
import pydantic
from pydantic import validate_call
from rich.prompt import Prompt

from sereto.cli.aliases import cli_aliases
from sereto.cli.console import Console
from sereto.exceptions import SeretoException


class AliasedGroup(click.Group):
    """A click Group subclass that allows for writing aliases and prefixes of any command."""

    def get_command(self, ctx: click.core.Context, cmd_name: str) -> click.Command | None:
        """Retrieves the command with the given name.

        If the command is not found, it looks up an explicit command alias or a command prefix.

        Args:
            ctx: The click context object.
            cmd_name: The name of the command to retrieve.

        Returns:
            The command with the given name, or None if no command is found.
        """
        # built-in commands
        rv = click.Group.get_command(self, ctx, cmd_name)
        if rv is not None:
            return rv

        # look up an explicit command alias
        if cmd_name in cli_aliases:
            actual_cmd = cli_aliases[cmd_name]
            return click.Group.get_command(self, ctx, actual_cmd)

        # look up a command prefix
        matches = [x for x in self.list_commands(ctx) if x.lower().startswith(cmd_name.lower())]
        if not matches:
            return None
        elif len(matches) == 1:
            return click.Group.get_command(self, ctx, matches[0])
        ctx.fail(f"Too many matches: {', '.join(sorted(matches))}")

    def resolve_command(
        self, ctx: click.core.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        """Resolves the full command's name."""
        _, cmd, args = super().resolve_command(ctx, args)
        if cmd is None:
            ctx.fail("No such command")
        return cmd.name, cmd, args


# Param = ParamSpec("Param")
# RetType = TypeVar("RetType")


# def settings_require(vars: set[Literal["reports_path", "templates_path"]]
#                      ) -> Callable[[Callable[Param, RetType]], Callable[Param, RetType]]:
#     """Decorator marking the optional attributes of Settings as required.

#     It load the CliContext through `click.get_current_context().obj`, which much already exist.

#     Usage:
#         `@settings_require(vars={"reports_path", "templates_path"})`
#     """

#     def decorator(func: Callable[Param, RetType]) -> Callable[Param, RetType]:
#         @functools.wraps(func)
#         def wrapper(*args: Param.args, **kwargs: Param.kwargs) -> RetType:
#             if len(vars) == 0:
#                 raise SeretoValueError("no parameter provided to settings decorator")
#             cli_ctx: CliContext = click.get_current_context().obj

#             for var_path in vars:
#                 if getattr(cli_ctx.settings, var_path) is None:
#                     Console().print(dedent(f"""\
#                         [yellow]WARNING: {var_path!r} directory not defined

#                         Your choices:
#                         1) Fill in the path interactively through the active prompt.
#                         The configuration regarding its location will be written
#                         to "{get_settings_path()}".
#                         2) Set environment variable SERETO_{var_path.upper()}
#                         3) Manually create/edit the settings file.
#                         You can use `sereto settings edit`.
#                         """))
#                     input: str = Prompt.ask(var_path, console=Console())
#                     path = pathlib.Path(input).resolve()

#                     if not path.exists():
#                         if Confirm.ask(f"[yellow]Directory '{path}' does not exist. Create?",
#                                        console=Console(), default=False):
#                             path.mkdir(parents=True)
#                         else:
#                             raise SeretoPathError(f"{var_path!r} not provided")

#                     setattr(cli_ctx.settings, var_path, path)
#                     write_settings(cli_ctx.settings)

#             return func(*args, **kwargs)
#         return wrapper
#     return decorator


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
            if isinstance(e, SeretoException):
                Console().print(f"[red]Error: {e}")
            if os.environ.get("DEBUG", False):
                Console().print_exception(show_locals=True, suppress=[click, jinja2, pydantic, pathlib])
            else:
                Console().print("\n[yellow]Set environment variable [blue]DEBUG=1[/blue] for more details.")
            sys.exit(1)

    return outer_function


@validate_call
def edit_list(list: list[Any], prompt: str) -> list[str]:
    """Edit a list of objects using the user's default editor.

    Args:
        list: A list of objects (convertable to str) initially loaded to the editor. It remains unmodified.
        prompt: A prompt to be displayed to the user before the editor is opened.

    Returns:
        New list entered by user to the text editor.

    The edit_list function prompts the user to edit a list of strings using their default editor. It first prints the
    given prompt to the console and waits for the user to press Enter. Then it opens the user's default editor with the
    list of strings as the initial content. If the user saves and closes the editor, the edited content is returned as
    a list of strings. If the user closes the editor without saving, an empty list is returned.

    The function also removes any empty lines and lines starting with `#` from the edited content before returning it.
    """
    Console().print(prompt)
    input("Press Enter to continue...")
    res: str | None = click.edit("\n".join(list))
    if res is None:
        return []
    return [line.strip() for line in res.split("\n") if len(line.strip()) > 0 and line[0] != "#"]


EnumType = TypeVar("EnumType", bound=Enum)


def load_enum(enum: type[EnumType], prompt: str) -> EnumType:
    """Let user select a value from enum."""
    choice = Prompt.ask(prompt=prompt, choices=[e.value for e in enum])
    return enum(choice)
