from enum import Enum
from typing import TypeVar

import click
from prompt_toolkit.shortcuts import radiolist_dialog
from rich.console import Console as RichConsole

from sereto.cli.aliases import cli_aliases
from sereto.singleton import Singleton


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


EnumType = TypeVar("EnumType", bound=Enum)


def load_enum(enum: type[EnumType], message: str) -> EnumType:
    """Let user select a value from enum."""
    choice = radiolist_dialog(
        title="Select value",
        text=message,
        values=[(e.name, e.value) for e in enum],
    ).run()

    return enum(choice)


class Console(RichConsole, metaclass=Singleton):
    """Singleton wrapper around Rich's Console."""
