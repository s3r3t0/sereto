from pathlib import Path
from shutil import copy2

from pydantic import validate_call

from sereto.convert import apply_convertor
from sereto.enums import FileFormat
from sereto.exceptions import SeretoPathError
from sereto.finding import FindingGroup, SubFinding
from sereto.jinja import render_jinja2
from sereto.models.version import ProjectVersion
from sereto.project import Project, init_build_dir
from sereto.target import Target
from sereto.utils import write_if_different


@validate_call
def build_subfinding(
    project: Project,
    target: Target,
    sub_finding: SubFinding,
    version: ProjectVersion,
    intermediate_format: FileFormat,
    converter: str | None = None,
) -> None:
    """Process a sub-finding into the specified format and write it to the ".build" directory.

    The sub-finding is first rendered as a Jinja2 template, then converted to the desired format.
    If the output file already exists and has the same content, it is not overwritten (to preserve timestamps).

    Args:
        project: Project's representation.
        target: The target containing the sub-finding.
        sub_finding: The sub-finding to process.
        version: The project version to use for rendering.
        intermediate_format: The desired output format (e.g., FileFormat.tex).
        converter: The convert recipe used for file format transformations. If None, the first recipe is used.
    """
    # Initialize the build directory
    init_build_dir(project=project, target=target)

    version_config = project.config.at_version(version=version)

    # Render Jinja2 template
    finding_content = render_jinja2(
        templates=[sub_finding.path.parent],
        file=sub_finding.path,
        vars={
            "f": sub_finding,
            "c": version_config,
            "config": project.config,
            "version": version,
        },
    )

    # Convert to desired format
    content = apply_convertor(
        input=finding_content,
        input_format=sub_finding.format,
        output_format=intermediate_format,
        render=project.settings.render,
        recipe=converter,
        replacements={
            "%TEMPLATES%": str(project.settings.templates_path),
        },
    )

    # Write the finding to the ".build" directory; do not overwrite the same content (preserve timestamps)
    write_if_different(
        file=project.path
        / ".build"
        / target.uname
        / f"{sub_finding.path.name.removesuffix(f'.{sub_finding.format.value}.j2')}.{intermediate_format.value}",
        content=content,
    )


@validate_call
def build_finding_group_dependencies(
    project: Project,
    target: Target,
    finding_group: FindingGroup,
    version: ProjectVersion,
    intermediate_format: FileFormat,
    converter: str | None = None,
) -> None:
    # Render included findings to the desired format
    for sub_finding in finding_group.sub_findings:
        build_subfinding(
            project=project,
            target=target,
            sub_finding=sub_finding,
            version=version,
            intermediate_format=intermediate_format,
            converter=converter,
        )

    layouts_generated = project.ensure_dir("layouts/generated")

    # Create template in "layouts/generated" directory
    template_dst = layouts_generated / f"{target.uname}_{finding_group.uname}.{intermediate_format.value}.j2"
    if not template_dst.is_file():  # do not overwrite existing templates
        template_src = (
            project.settings.templates_path
            / "categories"
            / target.data.category
            / f"finding_group.{intermediate_format.value}.j2"
        )
        copy2(template_src, template_dst, follow_symlinks=False)


@validate_call
def build_finding_group_to_format(
    project: Project,
    target: Target,
    finding_group: FindingGroup,
    format: FileFormat,
    version: ProjectVersion,
) -> Path:
    # Initialize the build directory
    init_build_dir(project=project, target=target)

    # Determine the indexes for correct section numbering
    target_ix = project.config.at_version(version).targets.index(target)
    fg_ix = target.findings.groups.index(finding_group)

    # Construct path to finding group template
    if not (template := project.path / f"layouts/finding_group.{format.value}.j2").is_file():
        raise SeretoPathError(f"template not found: '{template}'")

    content = render_jinja2(
        templates=[
            project.path / "layouts/generated",
            project.path / "layouts",
            project.path / "includes",
            project.path,
        ],
        file=template,
        vars={
            "finding_group": finding_group,
            "finding_group_index": fg_ix,
            "target": target,
            "target_index": target_ix,
            "c": project.config.at_version(version),
            "config": project.config,
            "version": version,
            "project_path": project.path,
        },
    )

    # Write the finding group to the ".build" directory; do not overwrite the same content (preserve timestamps)
    destination = project.path / ".build" / target.uname / f"{finding_group.uname}.{format.value}"
    write_if_different(file=destination, content=content)

    # Return the path to the rendered finding group
    if not destination.is_file():
        raise SeretoPathError(f"something went wrong, the finding group was not written to '{destination}'")
    return destination


@validate_call
def build_target_dependencies(
    project: Project,
    target: Target,
    version: ProjectVersion,
    intermediate_format: FileFormat,
    converter: str | None = None,
) -> None:
    # Finding group dependencies
    for finding_group in target.findings.groups:
        build_finding_group_dependencies(
            project=project,
            target=target,
            finding_group=finding_group,
            version=version,
            intermediate_format=intermediate_format,
            converter=converter,
        )

    # Create template in "layouts/generated" directory
    template_dst = project.ensure_dir("layouts/generated") / f"{target.uname}.{intermediate_format.value}.j2"
    if not template_dst.is_file():  # do not overwrite existing templates
        template_src = (
            project.settings.templates_path
            / "categories"
            / target.data.category
            / f"target.{intermediate_format.value}.j2"
        )
        copy2(template_src, template_dst, follow_symlinks=False)


@validate_call
def build_target_to_format(project: Project, target: Target, format: FileFormat, version: ProjectVersion) -> Path:
    # Initialize the build directory
    init_build_dir(project=project, target=target)

    # Determine the index for correct section numbering
    target_ix = project.config.at_version(version).targets.index(target)

    # Construct path to target template
    if not (template := project.path / f"layouts/target.{format.value}.j2").is_file():
        raise SeretoPathError(f"template not found: '{template}'")

    # Render Jinja2 template
    content = render_jinja2(
        templates=[
            project.path / "layouts/generated",
            project.path / "layouts",
            project.path / "includes",
            project.path,
        ],
        file=template,
        vars={
            "target": target,
            "target_index": target_ix,
            "c": project.config.at_version(version),
            "config": project.config,
            "version": version,
            "project_path": project.path,
        },
    )

    # Write the target to the ".build" directory; do not overwrite the same content (preserve timestamps)
    destination = project.path / ".build" / target.uname / f"{target.uname}.{format.value}"
    write_if_different(file=destination, content=content)

    # Return the path to the rendered target
    if not destination.is_file():
        raise SeretoPathError(f"something went wrong, the target was not written to '{destination}'")
    return destination


@validate_call
def build_report_to_format(
    project: Project, template: str, version: ProjectVersion, format: FileFormat, converter: str | None = None
) -> Path:
    # Process all targets and their dependencies
    for target in project.config.at_version(version).targets:
        build_target_dependencies(
            project=project, target=target, version=version, intermediate_format=format, converter=converter
        )

    # Initialize the build directory
    init_build_dir(project=project, version_config=project.config.at_version(version))

    # Construct path to report template
    if not (template_path := project.path / f"layouts/{template}.{format.value}.j2").is_file():
        raise SeretoPathError(f"template not found: '{template_path}'")

    # Render Jinja2 template
    content = render_jinja2(
        templates=[
            project.path / "layouts/generated",
            project.path / "layouts",
            project.path / "includes",
            project.path,
        ],
        file=template_path,
        vars={
            "c": project.config.at_version(version=version),
            "config": project.config,
            "version": version,
            "project_path": project.path,
        },
    )

    # Write the report to the ".build" directory; do not overwrite the same content (preserve timestamps)
    destination = project.path / ".build" / f"report{version.path_suffix}.{format.value}"
    write_if_different(file=destination, content=content)

    # Return the path to the rendered report
    if not destination.is_file():
        raise SeretoPathError(f"something went wrong, the report was not written to '{destination}'")
    return destination


@validate_call
def build_sow_to_format(project: Project, version: ProjectVersion, format: FileFormat) -> Path:
    # Initialize the build directory
    init_build_dir(project=project, version_config=project.config.at_version(version))

    # Construct path to SoW template
    if not (template := project.path / f"layouts/sow.{format.value}.j2").is_file():
        raise SeretoPathError(f"template not found: '{template}'")

    # Render the Jinja template
    content = render_jinja2(
        templates=[
            project.path / "layouts/generated",
            project.path / "layouts",
            project.path / "includes",
            project.path,
        ],
        file=template,
        vars={
            "c": project.config.at_version(version),
            "config": project.config,
            "version": version,
            "project_path": project.path,
        },
    )

    # Write the SoW to the ".build" directory; do not overwrite the same content (preserve timestamps)
    destination = project.path / ".build" / f"sow{version.path_suffix}.{format.value}"
    write_if_different(file=destination, content=content)

    # Return the path to the rendered SoW
    if not destination.is_file():
        raise SeretoPathError(f"something went wrong, the SoW was not written to '{destination}'")
    return destination
