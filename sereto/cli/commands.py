import os
from pathlib import Path
from typing import Literal

import click
from click import Group, get_app_dir
from click_repl import exit as click_repl_exit  # type: ignore[import-untyped]
from click_repl import repl
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from pydantic import Field, validate_call
from rich import box
from rich.table import Table

from sereto.cli.utils import Console
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.project import Project
from sereto.models.settings import Settings
from sereto.settings import load_settings
from sereto.singleton import Singleton
from sereto.types import TypeProjectId

__all__ = ["sereto_ls", "sereto_repl"]


@validate_call
def sereto_ls(settings: Settings) -> None:
    """List all reports in the user's reports directory.

    Print a table with the details to the console.

    Args:
        settings: The Settings object.
    """
    project_paths: list[Path] = [d for d in settings.reports_path.iterdir() if Project.is_project_dir(d)]
    table = Table("ID", "Name", "Location", title="Reports", box=box.MINIMAL)

    for dir in project_paths:
        try:
            report_name = Project.load_from(dir).config.last_config().name
        except (RuntimeError, SeretoValueError):
            report_name = "n/a"

        table.add_row(dir.name, report_name, f"[link {dir.as_uri()}]{dir}")

    Console().print(table, justify="center")


class WorkingDir(metaclass=Singleton):
    """Helper class for REPL implementing the `cd` command.

    Attributes:
        old_cwd: The previous working directory.
    """

    old_cwd: Path = Field(default_factory=Path.cwd)

    def change(self, dst: Path, /) -> None:
        """Change the current working directory to the new location.

        Also saves the previous location for future reference.

        Args:
            dst: The new working directory

        Raises:
            SeretoPathError: If the provided path is not an existing directory.
        """
        if not dst.is_dir():
            raise SeretoPathError(f"Directory '{dst}' does not exist.")

        cwd = Path.cwd()
        os.chdir(dst)
        self.old_cwd = cwd

    def go_back(self) -> None:
        """Change the current working directory to the previous location."""
        self.change(self.old_cwd)


def _get_repl_prompt() -> list[tuple[str, str]]:
    """Get the prompt for the Read-Eval-Print Loop (REPL).

    Returns:
        The prompt string.
    """
    # Determine if the current working directory is a report directory
    project_id: TypeProjectId | None = None
    cwd = Path.cwd()
    if Project.is_project_dir(cwd):
        # Load the report to get the ID (this can be different from the directory name)
        project = Project.load_from()
        project_id = project.config.last_config().id

    final_prompt: list[tuple[str, str]] = []

    if os.environ.get("DEBUG", "0") == "1":
        final_prompt += [("class:debug", "DEBUG ")]

    if project_id is not None:
        final_prompt += [
            ("class:bracket", "("),
            ("class:project_id", f"{project_id}"),
            ("class:bracket", ") "),
        ]

    final_prompt += [("class:sereto", "sereto")]
    final_prompt += [("class:gt", " > ")]

    return final_prompt


@click.command(name="cd")
@click.argument("project_id", type=str)
@load_settings
@validate_call
def repl_cd(settings: Settings, project_id: TypeProjectId | Literal["-"]) -> None:
    """Switch the active project in the REPL.

    Args:
        settings: The Settings object.
        project_id: The ID of the project to switch to. Use '-' to go back to the previous working directory.

    Raises:
        SeretoValueError: If the report ID is invalid.
        SeretoPathError: If the report's path does not exist.
    """
    wd = WorkingDir()

    # `cd -` ... Go back to the previous working directory
    if project_id == "-":
        wd.go_back()
        return

    # Check if the report's location exists
    # TODO: Should we iterate over all reports and read the config to get the correct path?
    report_path = settings.reports_path / project_id
    if not Project.is_project_dir(report_path):
        raise SeretoPathError(f"Report '{project_id}' does not exist. Use 'ls' to list reports.")

    # Change the current working directory to the new location
    wd.change(report_path)


@click.command(name="exit")
def repl_exit() -> None:
    """Exit from the Read-Eval-Print Loop (REPL)."""
    click_repl_exit()


@click.command(name="debug")
def repl_toggle_debug() -> None:
    """Toggle the debug mode."""
    if os.environ.get("DEBUG", "0") == "1":
        del os.environ["DEBUG"]
    else:
        os.environ["DEBUG"] = "1"


def sereto_repl(cli: Group) -> None:
    """Start an interactive Read-Eval-Print Loop (REPL) session.

    Args:
        cli: The main CLI group.
    """
    Console().log(r"""
  ____       ____     _____
 / ___|  ___|  _ \ __|_   _|__
 \___ \ / _ \ |_) / _ \| |/ _ \
  ___) |  __/  _ <  __/| | (_) |
 |____/ \___|_| \_\___||_|\___/

Welcome to [blue]SeReTo Interactive Mode[/blue]!
-------------------------------------------
Type 'exit' or press 'Ctrl+D' to quit.
Use 'cd <ID>' to change the active project.
Type '-h'/'--help' to see available commands.
    """)

    # Add REPL specific commands
    cli.add_command(repl_cd)
    cli.add_command(repl_exit)
    cli.add_command(repl_toggle_debug)

    # Define the prompt style
    prompt_style = Style.from_dict(
        {
            "debug": "red",
            "sereto": "#02a0f0 bold",
            "bracket": "#8a8a8a",
            "project_id": "#00ff00",
            "gt": "#8a8a8a bold",
        }
    )

    prompt_kwargs = {
        "message": _get_repl_prompt,
        "history": FileHistory(Path(get_app_dir(app_name="sereto")) / ".sereto_history"),
        "style": prompt_style,
    }
    repl(click.get_current_context(), prompt_kwargs=prompt_kwargs)
