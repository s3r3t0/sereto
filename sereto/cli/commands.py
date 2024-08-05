from pathlib import Path

from pydantic import validate_call
from rich import box
from rich.table import Table

from sereto.cli.console import Console
from sereto.exceptions import SeretoValueError
from sereto.models.report import Report
from sereto.models.settings import Settings
from sereto.report import load_report_function


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
