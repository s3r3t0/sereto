import os
import readline
from pathlib import Path

from click import Group, get_app_dir
from pydantic import Field, TypeAdapter, ValidationError, validate_call
from rich import box
from rich.markup import escape
from rich.table import Table

from sereto.cli.utils import Console
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.base import SeretoBaseModel
from sereto.models.report import Report
from sereto.models.settings import Settings
from sereto.report import load_report_function
from sereto.types import TypeReportId

__all__ = ["sereto_ls", "sereto_repl"]


@validate_call
def sereto_ls(settings: Settings) -> None:
    """List all reports in the user's reports directory.

    Args:
        settings: The Settings object.
    """
    report_paths: list[Path] = [d for d in settings.reports_path.iterdir() if Report.is_report_dir(d)]
    table = Table("ID", "Name", "Location", title="Reports", box=box.MINIMAL)

    for dir in report_paths:
        try:
            report = load_report_function(settings=settings, report_path=dir)
            report_name: str = report.config.name
        except (RuntimeError, SeretoValueError):
            report_name = "n/a"

        table.add_row(dir.name, report_name, f"[link {dir.as_uri()}]{dir}")

    Console().print(table, justify="center")


class WorkingDir(SeretoBaseModel):
    """Helper class for REPL implementing the `cd` command.

    Attributes:
        old_cwd: The previous working directory.
    """

    old_cwd: Path = Field(default=Path.cwd())

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


def _get_history_file_path() -> Path:
    """Get the path to the history file for the REPL."""
    return Path(get_app_dir(app_name="sereto")) / ".sereto_history"


def _save_repl_history() -> None:
    """Save the command history to a file for future sessions."""
    readline.write_history_file(_get_history_file_path())


def _load_repl_history() -> None:
    """Load the command history from the previous sessions."""
    if Path(hf := _get_history_file_path()).is_file():
        readline.read_history_file(hf)


def _get_repl_prompt(settings: Settings) -> str:
    """Get the prompt for the Read-Eval-Print Loop (REPL).

    Args:
        settings: The Settings object.

    Returns:
        The prompt string.
    """
    # Determine if the current working directory is a report directory
    report_id: TypeReportId | None = None
    cwd = Path.cwd()
    if Report.is_report_dir(cwd):
        # Load the report to get the ID (this can be different from the directory name)
        report = load_report_function(settings=settings, report_path=cwd)
        report_id = report.config.at_version(report.config.last_version()).id

    # Define the prompt
    base_prompt = "sereto > "
    return f"({report_id}) {base_prompt}" if report_id else base_prompt


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
        ta: TypeAdapter[TypeReportId] = TypeAdapter(TypeReportId)  # hack for mypy
        report_id = ta.validate_python(user_input)
    except ValidationError as e:
        raise SeretoValueError(f"Invalid report ID. {e.errors()[0]['msg']}") from e

    # Check if the report's location exists
    # TODO: Should we iterate over all reports and read the config to get the correct path?
    report_path = settings.reports_path / report_id
    if not Report.is_report_dir(report_path):
        raise SeretoPathError(f"Report '{report_id}' does not exist. Use 'ls' to list reports.")

    # Change the current working directory to the new location
    wd.change(report_path)


def sereto_repl(cli: Group, settings: Settings) -> None:
    """Start an interactive Read-Eval-Print Loop (REPL) session.

    Args:
        cli: The main CLI group.
    """
    Console().log("Starting interactive mode. Type 'exit' to quit and 'cd ID' to change active project.")

    # Enable command history using readline
    readline.parse_and_bind("tab: complete")
    readline.set_auto_history(True)

    # Load command history from previous sessions
    _load_repl_history()

    prompt = _get_repl_prompt(settings=settings)
    wd = WorkingDir()

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
                    prompt = _get_repl_prompt(settings=settings)
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

    # Save command history for future sessions
    _save_repl_history()
