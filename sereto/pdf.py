from pathlib import Path

from pydantic import DirectoryPath, FilePath, validate_call

from sereto.build import (
    build_finding_group_dependencies,
    build_finding_group_to_tex,
    build_report_to_tex,
    build_sow_to_tex,
    build_target_dependencies,
    build_target_to_tex,
)
from sereto.cli.utils import Console
from sereto.exceptions import SeretoPathError
from sereto.models.settings import Render, RenderRecipe
from sereto.models.version import ProjectVersion
from sereto.project import Project, project_create_missing


@validate_call
def render_tex_to_pdf(
    file: FilePath,
    templates: DirectoryPath,
    render: Render,
    recipe: RenderRecipe,
    replacements: dict[str, str] | None = None,
) -> Path:
    if replacements is None:
        replacements = {}

    # Run the tools defined in the recipe
    for tool_name in recipe.tools:
        tool = [t for t in render.tools if t.name == tool_name][0]
        tool.run(
            cwd=file.parent,
            replacements={
                "%DOC%": str(file.with_suffix("")),
                "%DOC_EXT%": str(file),
                "%DOCFILE%": file.stem,
                "%DOCFILE_EXT%": file.name,
                "%DIR%": str(file.parent),
                "%TEMPLATES%": str(templates),
            }
            | replacements,
        )

    # Return the path to the rendered PDF
    destination = file.with_suffix(".pdf")
    if not destination.is_file():
        raise SeretoPathError(f"something went wrong, the finding group was not written to '{destination}'")
    return destination


@validate_call
def generate_pdf_finding_group(
    project: Project,
    target_selector: int | str | None,
    finding_group_selector: int | str | None,
    converter: str | None,
    renderer: str | None,
    version: ProjectVersion | None,
) -> Path:
    """Generate a finding group PDF.

    Args:
        project: Project's representation.
        target_selector: The target selector (1-based index or unique name). If None, the only target is selected.
        finding_group_selector: The finding group selector (1-based index or unique name). If None, the only finding
            group is selected.
        converter: The convert recipe used for file format transformations. If None, the first recipe is used.
        renderer: The recipe used for generating the finding group. If None, the first recipe is used.
        version: The version of the project to use. If None, the last version

    Returns:
        Path to the generated finding group PDF.
    """
    if version is None:
        version = project.config.last_version

    # Select target and finding group
    target = project.config.at_version(version).select_target(
        categories=project.settings.categories, selector=target_selector
    )

    fg = target.findings.select_group(selector=finding_group_selector)

    Console().log(f"Rendering partial report for finding group {fg.uname!r}")

    project_create_missing(project_path=project.path, version_config=project.config.at_version(version))

    # Build finding group to TeX
    build_finding_group_dependencies(
        project=project, target=target, finding_group=fg, version=version, converter=converter
    )
    finding_group_tex = build_finding_group_to_tex(project=project, target=target, finding_group=fg, version=version)

    # Render PDF
    recipe = project.settings.render.get_finding_group_recipe(name=renderer)
    finding_group_pdf = render_tex_to_pdf(
        file=finding_group_tex,
        templates=project.settings.templates_path,
        render=project.settings.render,
        recipe=recipe,
    )

    # Create directory for the PDF results if it does not exist
    if not (pdf_dir := project.path / "pdf").is_dir():
        pdf_dir.mkdir()

    # Move the finding group PDF to the "pdf" directory
    finding_group_pdf = finding_group_pdf.rename(pdf_dir / f"{target.uname}_{finding_group_pdf.name}")

    return finding_group_pdf


@validate_call
def generate_pdf_report(
    project: Project,
    template: str,
    report_recipe: str | None = None,
    convert_recipe: str | None = None,
    version: ProjectVersion | None = None,
) -> Path:
    """Generate a report PDF.

    Args:
        project: Project's representation.
        template: The template used for generating the report.
        report_recipe: The recipe used for generating the report. If None, the first recipe is used.
        convert_recipe: The convert recipe used for file format transformations. If None, the first recipe is used.
        version: The version of the project to use. If None, the last version

    Returns:
        Path to the generated report PDF.
    """
    if version is None:
        version = project.config.last_version

    Console().log(f"Rendering report version: '{version}'")

    project_create_missing(project_path=project.path, version_config=project.config.at_version(version))

    # Build report to TeX
    report_tex = build_report_to_tex(project=project, template=template, version=version, converter=convert_recipe)

    # Render PDF
    recipe = project.settings.render.get_report_recipe(name=report_recipe)
    report_pdf = render_tex_to_pdf(
        file=report_tex, templates=project.settings.templates_path, render=project.settings.render, recipe=recipe
    )

    # Create directory for the PDF results if it does not exist
    if not (pdf_dir := project.path / "pdf").is_dir():
        pdf_dir.mkdir()

    # Move the report PDF to the "pdf" directory
    report_pdf = report_pdf.rename(project.path / "pdf" / report_pdf.name)

    return report_pdf


@validate_call
def generate_pdf_sow(project: Project, sow_recipe: str | None, version: ProjectVersion | None) -> Path:
    """Generate a Statement of Work (SoW) PDF.

    Args:
        project: Project's representation.
        sow_recipe: The recipe used for generating the SoW. If None, the first recipe is used.
        version: The version of the project to use. If None, the last version

    Returns:
        Path to the generated Statement of Work (SoW) PDF.
    """
    if version is None:
        version = project.config.last_version

    Console().log(f"Rendering SoW version: '{version}'")

    project_create_missing(project_path=project.path, version_config=project.config.at_version(version))

    # Build SoW to TeX
    sow_tex = build_sow_to_tex(project=project, version=version)

    # Render PDF
    recipe = project.settings.render.get_sow_recipe(name=sow_recipe)
    sow_pdf = render_tex_to_pdf(
        file=sow_tex, templates=project.settings.templates_path, render=project.settings.render, recipe=recipe
    )

    # Create directory for the PDF results if it does not exist
    if not (pdf_dir := project.path / "pdf").is_dir():
        pdf_dir.mkdir()

    # Move the SoW PDF to the "pdf" directory
    sow_pdf = sow_pdf.rename(project.path / "pdf" / sow_pdf.name)

    return sow_pdf


@validate_call
def generate_pdf_target(
    project: Project,
    target_selector: int | str | None,
    target_recipe: str | None,
    convert_recipe: str | None,
    version: ProjectVersion | None,
) -> Path:
    """Generate a target PDF.

    Args:
        project: Project's representation.
        target_selector: The target selector (1-based index or unique name). If None, the only target is selected.
        target_recipe: The recipe used for generating the target. If None, the first recipe is used.
        convert_recipe: The convert recipe used for file format transformations. If None, the first recipe is used.
        version: The version of the project to use. If None, the last version

    Returns:
        Path to the generated target PDF.
    """
    if version is None:
        version = project.config.last_version

    # Select target
    target = project.config.last_config.select_target(categories=project.settings.categories, selector=target_selector)

    Console().log(f"Rendering partial report for target '{target.uname}'")

    project_create_missing(project_path=project.path, version_config=project.config.at_version(version))

    # Build target to TeX
    build_target_dependencies(project=project, target=target, version=version, converter=convert_recipe)
    target_tex = build_target_to_tex(project=project, target=target, version=version)

    # Render PDF
    recipe = project.settings.render.get_target_recipe(name=target_recipe)
    target_pdf = render_tex_to_pdf(
        file=target_tex, templates=project.settings.templates_path, render=project.settings.render, recipe=recipe
    )

    # Create directory for the PDF results if it does not exist
    if not (pdf_dir := project.path / "pdf").is_dir():
        pdf_dir.mkdir()

    # Move the target PDF to the "pdf" directory
    target_pdf = target_pdf.rename(project.path / "pdf" / target_pdf.name)

    return target_pdf
