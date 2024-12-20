from pathlib import Path
from shutil import copy2

from pydantic import validate_call

from sereto.cli.utils import Console
from sereto.exceptions import SeretoPathError
from sereto.finding import render_finding_group_to_tex, render_finding_to_tex
from sereto.models.finding import Finding, FindingGroup
from sereto.models.project import Project
from sereto.models.target import Target
from sereto.models.version import ProjectVersion
from sereto.project import init_build_dir
from sereto.report import render_report_to_tex
from sereto.sow import render_sow_to_tex
from sereto.target import render_target_to_tex
from sereto.utils import write_if_different


@validate_call
def ensure_finding_group_template(
    project: Project, target: Target, finding_group: FindingGroup, version: ProjectVersion
) -> None:
    """Ensures that a template exists for the specified finding group.

    Does not overwrite existing template.
    """
    # Make sure that "layouts/generated" directory exists
    if not (layouts_generated := project.path / "layouts/generated").is_dir():
        layouts_generated.mkdir(parents=True)

    # Create template in "layouts/generated" directory
    template_dst = layouts_generated / f"{target.uname}_{finding_group.uname}{version.path_suffix}.tex.j2"
    if not template_dst.is_file():  # do not overwrite existing templates
        template_src = project.settings.templates_path / "categories" / target.category / "finding_group.tex.j2"
        copy2(template_src, template_dst, follow_symlinks=False)


@validate_call
def ensure_target_template(project: Project, target: Target, version: ProjectVersion) -> None:
    """Ensures that a template exists for the specified target.

    Does not overwrite existing template.
    """
    # Make sure that "layouts/generated" directory exists
    if not (layouts_generated := project.path / "layouts/generated").is_dir():
        layouts_generated.mkdir(parents=True)

    # Create template in "layouts/generated" directory
    template_dst = layouts_generated / f"{target.uname}{version.path_suffix}.tex.j2"
    if not template_dst.is_file():  # do not overwrite existing templates
        template_src = project.settings.templates_path / "categories" / target.category / "target.tex.j2"
        copy2(template_src, template_dst, follow_symlinks=False)


@validate_call
def build_finding_to_tex(
    project: Project,
    target: Target,
    finding: Finding,
    version: ProjectVersion,
    converter: str | None = None,
) -> None:
    """Process one finding into TeX format and write it to the ".build" directory."""
    # Finding not included in the current version
    if version not in finding.risks:
        Console().log(f"Finding {finding.path_name!r} not found in version {version}. Skipping.")
        return

    # Initialize the build directory
    init_build_dir(project=project, version=version)

    # Process the finding
    content = render_finding_to_tex(
        target,
        finding=finding,
        version=version,
        templates=project.settings.templates_path,
        render=project.settings.render,
        converter=converter,
    )

    # Write the finding to the ".build" directory; do not overwrite the same content (preserve timestamps)
    write_if_different(
        file=project.path / ".build" / target.uname / f"{finding.path_name}{version.path_suffix}.tex",
        content=content,
    )


@validate_call
def build_finding_group_dependencies(
    project: Project,
    target: Target,
    finding_group: FindingGroup,
    version: ProjectVersion,
    converter: str | None = None,
) -> None:
    # Render included findings to TeX format
    for finding in finding_group.findings:
        build_finding_to_tex(project=project, target=target, finding=finding, version=version, converter=converter)

    # Ensure that finding group "inner" template exists
    ensure_finding_group_template(project=project, target=target, finding_group=finding_group, version=version)


@validate_call
def build_finding_group_to_tex(
    project: Project,
    target: Target,
    finding_group: FindingGroup,
    version: ProjectVersion,
) -> Path:
    # Initialize the build directory
    init_build_dir(project=project, version=version)

    # Determine the indexes for correct section numbering
    target_ix = project.config.at_version(version).targets.index(target)
    fg_ix = target.findings_config.finding_groups.index(finding_group)

    # Render the finding group to TeX format
    content = render_finding_group_to_tex(
        project=project,
        target=target,
        target_ix=target_ix,
        finding_group=finding_group,
        finding_group_ix=fg_ix,
        version=version,
    )

    # Write the finding group to the ".build" directory; do not overwrite the same content (preserve timestamps)
    destination = project.path / ".build" / target.uname / f"{finding_group.uname}{version.path_suffix}.tex"
    write_if_different(file=destination, content=content)

    # Return the path to the rendered finding group
    if not destination.is_file():
        raise SeretoPathError(f"something went wrong, the finding group was not written to '{destination}'")
    return destination


@validate_call
def build_target_dependencies(
    project: Project, target: Target, version: ProjectVersion, converter: str | None = None
) -> None:
    # Finding group dependencies
    for finding_group in target.findings_config.finding_groups:
        build_finding_group_dependencies(
            project=project, target=target, finding_group=finding_group, version=version, converter=converter
        )

    # Ensure that target "inner" template exists
    ensure_target_template(project=project, target=target, version=version)


@validate_call
def build_target_to_tex(project: Project, target: Target, version: ProjectVersion) -> Path:
    # Initialize the build directory
    init_build_dir(project=project, version=version)

    # Determine the index for correct section numbering
    target_ix = project.config.at_version(version).targets.index(target)

    # Render the target to TeX format
    content = render_target_to_tex(project=project, target=target, target_ix=target_ix, version=version)

    # Write the target to the ".build" directory; do not overwrite the same content (preserve timestamps)
    destination = project.path / ".build" / target.uname / f"{target.uname}{version.path_suffix}.tex"
    write_if_different(file=destination, content=content)

    # Return the path to the rendered target
    if not destination.is_file():
        raise SeretoPathError(f"something went wrong, the target was not written to '{destination}'")
    return destination


@validate_call
def build_report_to_tex(project: Project, version: ProjectVersion, converter: str | None = None) -> Path:
    # Process all targets and their dependencies
    for target in project.config.at_version(version).targets:
        build_target_dependencies(project=project, target=target, version=version, converter=converter)

    # Initialize the build directory
    init_build_dir(project=project, version=version)

    # Render the report to TeX format
    content = render_report_to_tex(project=project, version=version)

    # Write the report to the ".build" directory; do not overwrite the same content (preserve timestamps)
    destination = project.path / ".build" / f"report{version.path_suffix}.tex"
    write_if_different(file=destination, content=content)

    # Return the path to the rendered report
    if not destination.is_file():
        raise SeretoPathError(f"something went wrong, the report was not written to '{destination}'")
    return destination


@validate_call
def build_sow_to_tex(project: Project, version: ProjectVersion) -> Path:
    # Initialize the build directory
    init_build_dir(project=project, version=version)

    # Render the SoW to TeX format
    content = render_sow_to_tex(project=project, version=version)

    # Write the SoW to the ".build" directory; do not overwrite the same content (preserve timestamps)
    destination = project.path / ".build" / f"sow{version.path_suffix}.tex"
    write_if_different(file=destination, content=content)

    # Return the path to the rendered SoW
    if not destination.is_file():
        raise SeretoPathError(f"something went wrong, the SoW was not written to '{destination}'")
    return destination