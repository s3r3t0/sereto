from pathlib import Path

from pydantic import validate_call

from sereto.exceptions import SeretoValueError
from sereto.models.finding import FindingGroup
from sereto.models.report import Report
from sereto.models.settings import RenderRecipe, Settings
from sereto.models.target import Target
from sereto.models.version import ReportVersion


@validate_call
def _render_pdf(
    tex_path: Path,
    render_recipe: RenderRecipe,
    settings: Settings,
    replacements: dict[str, str] | None = None,
) -> None:
    if replacements is None:
        replacements = {}

    for tool_name in render_recipe.tools:
        tool = [t for t in settings.render.tools if t.name == tool_name][0]
        tool.run(
            cwd=tex_path.parent,
            replacements={
                "%DOC%": str(tex_path.with_suffix("")),
                "%DOC_EXT%": str(tex_path),
                "%DOCFILE%": tex_path.stem,
                "%DOCFILE_EXT%": tex_path.name,
                "%DIR%": str(tex_path.parent),
                "%TEMPLATES%": str(settings.templates_path),
            }
            | replacements,
        )


@validate_call
def render_report_pdf(report: Report, settings: Settings, version: ReportVersion, recipe: str | None = None) -> None:
    """Render the report to PDF format according to the recipe.

    Prerequisite is having the report in TeX format.

    Args:
        report: Report's representation.
        settings: Global settings.
        version: The version of the report.
        recipe: Name which will be used to pick a recipe from Render configuration. If none is provided, the first
            recipe (index 0) is used.
    """
    report_path = Report.get_path(dir_subtree=settings.reports_path)
    report_tex_path = report_path / f"report{version.path_suffix}.tex"

    if recipe is None:
        render_recipe = settings.render.report_recipes[0]
    else:
        if len(res := [r for r in settings.render.report_recipes if r.name == recipe]) != 1:
            raise SeretoValueError(f"no report recipe found with name {recipe!r}")
        render_recipe = res[0]

    _render_pdf(tex_path=report_tex_path, render_recipe=render_recipe, settings=settings)


@validate_call
def render_sow_pdf(report: Report, settings: Settings, version: ReportVersion, recipe: str | None = None) -> None:
    """Render the SoW to PDF format according to the recipe.

    Prerequisite is having the SoW in TeX format.

    Args:
        report: Report's representation.
        settings: Global settings.
        version: The version of the report.
        recipe: Name which will be used to pick a recipe from Render configuration. If none is provided, the first
            recipe (index 0) is used.
    """
    report_path = Report.get_path(dir_subtree=settings.reports_path)
    sow_tex_path = report_path / f"sow{version.path_suffix}.tex"

    if recipe is None:
        render_recipe = settings.render.sow_recipes[0]
    else:
        if len(res := [r for r in settings.render.sow_recipes if r.name == recipe]) != 1:
            raise SeretoValueError(f"no SoW recipe found with name {recipe!r}")
        render_recipe = res[0]

    _render_pdf(tex_path=sow_tex_path, render_recipe=render_recipe, settings=settings)


@validate_call
def render_target_pdf(
    target: Target, report: Report, settings: Settings, version: ReportVersion, recipe: str | None = None
) -> None:
    """Render the target to PDF format according to the recipe.

    Prerequisite is having the target in TeX format.

    Args:
        target: Target's representation.
        report: Report's representation.
        settings: Global settings.
        version: The version of the report.
        recipe: Name which will be used to pick a recipe from Render configuration. If none is provided, the first
            recipe (index 0) is used.
    """
    report_path = Report.get_path(dir_subtree=settings.reports_path)
    target_tex_path = report_path / f"{target.uname}.tex"
    replacements = {"%TARGET_DIR%": str(report_path / target.uname)}

    if recipe is None:
        render_recipe = settings.render.target_recipes[0]
    else:
        if len(res := [r for r in settings.render.target_recipes if r.name == recipe]) != 1:
            raise SeretoValueError(f"no target recipe found with name {recipe!r}")
        render_recipe = res[0]

    _render_pdf(tex_path=target_tex_path, render_recipe=render_recipe, settings=settings, replacements=replacements)


@validate_call
def render_finding_group_pdf(
    finding_group: FindingGroup,
    target: Target,
    report: Report,
    settings: Settings,
    version: ReportVersion,
    recipe: str | None = None,
) -> None:
    """Render the finding group to PDF format according to the recipe.

    Prerequisite is having the finding group in TeX format.

    Args:
        finding_group: Finding group with all the sub-findings.
        target: Target's representation.
        report: Report's representation.
        settings: Global settings.
        version: The version of the report.
        recipe: Name which will be used to pick a recipe from Render configuration. If none is provided, the first
            recipe (index 0) is used.
    """
    report_path = Report.get_path(dir_subtree=settings.reports_path)
    finding_group_tex_path = report_path / f"{target.uname}_{finding_group.uname}.tex"
    replacements = {"%FINDINGS_DIR%": str(report_path / target.uname / "findings")}

    if recipe is None:
        render_recipe = settings.render.finding_recipes[0]
    else:
        if len(res := [r for r in settings.render.target_recipes if r.name == recipe]) != 1:
            raise SeretoValueError(f"no finding recipe found with name {recipe!r}")
        render_recipe = res[0]

    _render_pdf(
        tex_path=finding_group_tex_path, render_recipe=render_recipe, settings=settings, replacements=replacements
    )
