import readline
from pathlib import Path

from click import Group, get_app_dir
from pydantic import validate_call
from rich import box
from rich.table import Table

from sereto.cli.console import Console
from sereto.exceptions import SeretoValueError
from sereto.models.report import Report
from sereto.models.settings import Settings
from sereto.report import load_report_function

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


def _get_history_file_path() -> Path:
    return Path(get_app_dir(app_name="sereto")) / ".sereto_history"


def _repl_save_history() -> None:
    readline.write_history_file(_get_history_file_path())


def _repl_load_history() -> None:
    if Path(hf := _get_history_file_path()).is_file():
        readline.read_history_file(hf)


def sereto_repl(cli: Group) -> None:
    Console().log("Starting interactive mode. Type 'exit' to quit.")

    # Enable command history using readline
    readline.parse_and_bind("tab: complete")
    readline.set_auto_history(True)

    # Load command history from previous sessions
    _repl_load_history()

    while True:
        try:
            cmd = input("(sereto) ").strip()
            if cmd in ["exit", "quit"]:
                break
            if cmd:
                cli.main(prog_name="sereto", args=cmd.split(), standalone_mode=False)
        except (KeyboardInterrupt, EOFError):
            # Allow graceful exit with Ctrl+C or Ctrl+D
            Console().log("\nExiting interactive mode.")
            break
        except SystemExit:
            pass  # Click raises SystemExit on success
        except Exception as e:
            Console().log(f"[red]Error:[/red] {e}")
        finally:
            _repl_save_history()
