from pathlib import Path

from pydantic import FilePath, validate_call

from sereto.exceptions import SeretoValueError
from sereto.models.finding import FindingGroup
from sereto.models.project import Project
from sereto.models.settings import RenderRecipe, Settings
from sereto.models.target import Target
from sereto.models.version import ReportVersion


@validate_call
def _render_pdf(
    tex_path: FilePath,
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
def render_report_pdf(project: Project, version: ReportVersion, recipe: str | None = None) -> Path:
    """Render the report to PDF format according to the recipe.

    Prerequisite is having the report in TeX format.

    Args:
        project: Report's project representation.
        version: The version of the report.
        recipe: Name which will be used to pick a recipe from Render configuration. If none is provided, the first
            recipe (index 0) is used.

    Returns:
        Path to the rendered PDF file.
    """
    report_tex_path = project.path / f"report{version.path_suffix}.tex"

    # Get the recipe to render the report
    if recipe is None:
        render_recipe = project.settings.render.report_recipes[0]
    else:
        if len(res := [r for r in project.settings.render.report_recipes if r.name == recipe]) != 1:
            raise SeretoValueError(f"no report recipe found with name {recipe!r}")
        render_recipe = res[0]

    # Render the report to PDF
    _render_pdf(tex_path=report_tex_path, render_recipe=render_recipe, settings=project.settings)

    # Return the path to the rendered PDF
    return report_tex_path.with_suffix(".pdf")


@validate_call
def render_sow_pdf(
    project: Project, version: ReportVersion, recipe: str | None = None, keep_original: bool = True
) -> None:
    """Render the SoW to PDF format according to the recipe.

    Prerequisite is having the SoW in TeX format.

    Args:
        project: Report's project representation.
        version: The version of the report.
        recipe: Name which will be used to pick a recipe from Render configuration. If none is provided, the first
            recipe (index 0) is used.
        keep_original: If True, the original TeX file will be kept after rendering. Otherwise, it will be removed.
            Defaults to True.
    """
    sow_tex_path = project.path / f"sow{version.path_suffix}.tex"

    if recipe is None:
        render_recipe = project.settings.render.sow_recipes[0]
    else:
        if len(res := [r for r in project.settings.render.sow_recipes if r.name == recipe]) != 1:
            raise SeretoValueError(f"no SoW recipe found with name {recipe!r}")
        render_recipe = res[0]

    _render_pdf(tex_path=sow_tex_path, render_recipe=render_recipe, settings=project.settings)

    if not keep_original:
        sow_tex_path.unlink()


@validate_call
def render_target_pdf(project: Project, target: Target, version: ReportVersion, recipe: str | None = None) -> None:
    """Render the target to PDF format according to the recipe.

    Prerequisite is having the target in TeX format.

    Args:
        project: Report's project representation.
        target: Target's representation.
        version: The version of the report.
        recipe: Name which will be used to pick a recipe from Render configuration. If none is provided, the first
            recipe (index 0) is used.
    """
    target_tex_path = project.path / f"{target.uname}.tex"
    replacements = {"%TARGET_DIR%": str(project.path / target.uname)}

    if recipe is None:
        render_recipe = project.settings.render.target_recipes[0]
    else:
        if len(res := [r for r in project.settings.render.target_recipes if r.name == recipe]) != 1:
            raise SeretoValueError(f"no target recipe found with name {recipe!r}")
        render_recipe = res[0]

    _render_pdf(
        tex_path=target_tex_path, render_recipe=render_recipe, settings=project.settings, replacements=replacements
    )


@validate_call
def render_finding_group_pdf(
    project: Project,
    finding_group: FindingGroup,
    target: Target,
    version: ReportVersion,
    recipe: str | None = None,
) -> None:
    """Render the finding group to PDF format according to the recipe.

    Prerequisite is having the finding group in TeX format.

    Args:
        project: Report's project representation.
        finding_group: Finding group with all the sub-findings.
        target: Target's representation.
        version: The version of the report.
        recipe: Name which will be used to pick a recipe from Render configuration. If none is provided, the first
            recipe (index 0) is used.
    """
    finding_group_tex_path = project.path / f"{target.uname}_{finding_group.uname}.tex"
    replacements = {"%FINDINGS_DIR%": str(project.path / target.uname / "findings")}

    if recipe is None:
        render_recipe = project.settings.render.finding_recipes[0]
    else:
        if len(res := [r for r in project.settings.render.target_recipes if r.name == recipe]) != 1:
            raise SeretoValueError(f"no finding recipe found with name {recipe!r}")
        render_recipe = res[0]

    _render_pdf(
        tex_path=finding_group_tex_path,
        render_recipe=render_recipe,
        settings=project.settings,
        replacements=replacements,
    )
