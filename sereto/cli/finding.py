from pydantic import validate_call
from rich.table import Table

from sereto.cli.utils import Console
from sereto.config import VersionConfig


@validate_call
def show_findings(version_config: VersionConfig) -> None:
    """Show the findings for a specific version.

    Args:
        version_config: The project configuration for specific version.
    """
    Console().log(f"Showing findings for version {version_config.version}")

    for target in version_config.targets:
        Console().line()
        table = Table("Finding name", "Category", "Risk", title=f"Target {target.data.name}")

        for finding_group in target.findings.groups:
            table.add_row(finding_group.name, target.data.category, finding_group.risk)

        Console().print(table, justify="center")
