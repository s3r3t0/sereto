from pydantic import validate_call
from rich import box
from rich.table import Table

from sereto.cli.utils import Console
from sereto.config import VersionConfig


@validate_call
def show_findings(version_config: VersionConfig) -> None:
    """Show the findings for a specific version.

    Args:
        version_config: The project configuration for specific version.
    """

    for target in version_config.targets:
        Console().line()
        table = Table(
            "%", "Finding name", "Category", "Risk", title=f"Target {version_config.version}", box=box.MINIMAL
        )

        for ix, finding_group in enumerate(target.findings.groups, start=1):
            table.add_row(str(ix), finding_group.name, target.data.category, finding_group.risk)

        Console().print(table, justify="center")
