from enum import Enum

import click
from prompt_toolkit.shortcuts import radiolist_dialog
from rich.console import Console as RichConsole

from sereto.cli.aliases import cli_aliases
from sereto.singleton import Singleton


def guard_ni_only_options(
    click_ctx: click.Context,
    non_interactive: bool,
    ni_only: dict[str, str],
) -> None:
    """Validate that NI-only options are not provided without -N/--non-interactive.

    Raises an error when any option that only applies in non-interactive mode is explicitly
    passed on the command line without the -N/--non-interactive flag.

    Args:
        click_ctx: The current Click context (from ``click.get_current_context()``).
        non_interactive: Value of the -N/--non-interactive flag.
        ni_only: Mapping of Python parameter name → CLI flag name for options that only
            apply in non-interactive mode.
    """
    if non_interactive:
        return

    ni_options = [
        option
        for param, option in ni_only.items()
        if click_ctx.get_parameter_source(param) == click.ParameterSource.COMMANDLINE
    ]
    if ni_options:
        from sereto.exceptions import SeretoValueError

        options = ", ".join(ni_options)
        raise SeretoValueError(f"Options {options} require -N/--non-interactive flag.")


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

        # if command is on the first position (has no context parent), check for explicit alias
        if ctx.parent is None and cmd_name in cli_aliases:
            # look up an explicit command alias
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


def load_enum[E: Enum](enum: type[E], message: str) -> E:
    """Let user select a value from enum."""
    choice = radiolist_dialog(
        title="Select value",
        text=message,
        values=[(e.name, e.value) for e in enum],
    ).run()

    return enum(choice)


class Console(RichConsole, metaclass=Singleton):
    """Singleton wrapper around Rich's Console."""
