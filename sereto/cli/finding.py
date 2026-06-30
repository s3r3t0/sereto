import json
from typing import Any

from pydantic import FilePath, validate_call
from rich import box
from rich.table import Table

from sereto.cli.utils import Console
from sereto.config import VersionConfig
from sereto.enums import Risk
from sereto.exceptions import SeretoValueError
from sereto.project import Project


@validate_call
def add_finding(
    project: Project,
    template_path: FilePath,
    finding_name: str | None = None,
    risk: Risk | None = None,
    target_selector: str | None = None,
    group_uname: str | None = None,
    group_name: str | None = None,
    variables: tuple[str, ...] = (),
    overwrite: bool = False,
) -> None:
    """Add a finding from a template non-interactively.

    Args:
        project: Project's representation.
        template_path: Path to the finding template file.
        finding_name: Name for the sub-finding.
        risk: Risk level override.
        target_selector: Target selector (index or uname).
        group_uname: Uname of existing finding group to append to.
        group_name: Name for the new finding group.
        variables: Template variables as KEY=VALUE strings.
        overwrite: If True, overwrite existing sub-finding instead of generating a unique suffix.
    """
    parsed_vars: dict[str, Any] = {}
    for var_str in variables:
        if "=" not in var_str:
            raise SeretoValueError(f"invalid variable format: {var_str!r}; expected KEY=VALUE")
        key, _, value_str = var_str.partition("=")
        try:
            parsed_vars[key] = json.loads(value_str)
        except json.JSONDecodeError:
            parsed_vars[key] = value_str

    target = project.config.last_config.select_target(categories=project.settings.categories, selector=target_selector)

    if group_uname is not None and not any(g.uname == group_uname for g in target.findings.groups):
        raise SeretoValueError(f"finding group with uname {group_uname!r} not found in target {target.uname!r}")

    target.findings.add_from_template(
        templates=project.settings.templates_path,
        template_path=template_path,
        category=target.data.category,
        sub_finding_name=finding_name,
        risk=risk,
        variables=parsed_vars,
        group_uname=group_uname,
        group_name=group_name,
        overwrite=overwrite,
    )


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
            table.add_row(str(ix), finding_group.suggested_name, target.data.category, finding_group.risk)

        Console().print(table, justify="center")
