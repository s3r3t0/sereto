import os
import readline
from pathlib import Path
from types import TracebackType
from typing import Self

from click import Group, get_app_dir
from pydantic import Field, TypeAdapter, ValidationError, validate_call
from rich import box
from rich.markup import escape
from rich.table import Table

from sereto.cli.utils import Console
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.base import SeretoBaseModel
from sereto.models.project import Project
from sereto.models.settings import Settings
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
            report_name: str = Project.load_from(dir).config.name
        except (RuntimeError, SeretoValueError):
            report_name = "n/a"

        table.add_row(dir.name, report_name, f"[link {dir.as_uri()}]{dir}")

    Console().print(table, justify="center")


class WorkingDir(SeretoBaseModel):
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


class REPLHistory(SeretoBaseModel):
    """Context manager to handle the command history in the REPL.

    Attributes:
        history_file_path: The path to the history file.
    """

    history_file: Path = Field(default=Path(get_app_dir(app_name="sereto")) / ".sereto_history")

    def __enter__(self) -> Self:
        """Load the command history from the previous sessions."""
        # Enable auto-saving of the history
        readline.set_auto_history(True)

        # Enable tab completion
        readline.parse_and_bind("tab: complete")

        # Load the history from the file
        if self.history_file.is_file():
            readline.read_history_file(self.history_file)

        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None
    ) -> None:
        """Save the command history to a file for future sessions."""
        readline.write_history_file(self.history_file)


def _get_repl_prompt() -> str:
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
        project_id = project.config.at_version(project.config.last_version()).id

    # Define the prompt
    base_prompt = "sereto > "
    return f"({project_id}) {base_prompt}" if project_id else base_prompt


@validate_call
def _change_repl_dir(settings: Settings, cmd: str, wd: WorkingDir) -> None:
    """Change the current working directory in the Read-Eval-Print Loop (REPL).

    Args:
        settings: The Settings object.
        cmd: The user input command.
        wd: The WorkingDir object.

    Raises:
        SeretoValueError: If the report ID is invalid.
        SeretoPathError: If the report's path does not exist.
    """
    if len(cmd) < (prefix_len := len("cd ")):
        raise SeretoValueError(f"Invalid command '{cmd}'. Use 'cd ID' to change active project.")

    user_input = cmd[prefix_len:].strip()

    # `cd -` ... Go back to the previous working directory
    if user_input == "-":
        wd.go_back()
        return

    # Extract the report ID from the user input
    try:
        ta: TypeAdapter[TypeProjectId] = TypeAdapter(TypeProjectId)  # hack for mypy
        report_id = ta.validate_python(user_input)
    except ValidationError as e:
        raise SeretoValueError(f"Invalid report ID. {e.errors()[0]['msg']}") from e

    # Check if the report's location exists
    # TODO: Should we iterate over all reports and read the config to get the correct path?
    report_path = settings.reports_path / report_id
    if not Project.is_project_dir(report_path):
        raise SeretoPathError(f"Report '{report_id}' does not exist. Use 'ls' to list reports.")

    # Change the current working directory to the new location
    wd.change(report_path)


def sereto_repl(cli: Group, settings: Settings) -> None:
    """Start an interactive Read-Eval-Print Loop (REPL) session.

    Args:
        cli: The main CLI group.
    """
    Console().log("Starting interactive mode. Type 'exit' to quit and 'cd ID' to change active project.")

    prompt = _get_repl_prompt()
    wd = WorkingDir()

    with REPLHistory():
        while True:
            try:
                # TODO navigating the history (up/down keys) breaks the rich's prompt, no colors for now
                # cmd = Console().input(prompt).strip()

                # Get user input
                cmd = input(prompt).strip()

                match cmd:
                    case "exit" | "quit":
                        break
                    case "help" | "h" | "?":
                        cli.main(prog_name="sereto", args="--help", standalone_mode=False)
                    case s if s.startswith("cd "):
                        _change_repl_dir(settings=settings, cmd=cmd, wd=wd)
                        prompt = _get_repl_prompt()
                    case s if len(s) > 0:
                        cli.main(prog_name="sereto", args=cmd.split(), standalone_mode=False)
                    case _:
                        continue
            except (KeyboardInterrupt, EOFError):
                # Allow graceful exit with Ctrl+C or Ctrl+D
                Console().log("Exiting interactive mode.")
                break
            except SystemExit:
                pass  # Click raises SystemExit on success
            except Exception as e:
                Console().log(f"[red]Error:[/red] {escape(str(e))}")
