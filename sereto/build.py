from pathlib import Path
from shutil import copy2

from pydantic import DirectoryPath, validate_call

from sereto.exceptions import SeretoPathError
from sereto.finding import FindingGroup, SubFinding, render_finding_group_to_tex, render_subfinding_to_tex
from sereto.models.version import ProjectVersion
from sereto.project import Project, init_build_dir
from sereto.report import render_report_to_tex
from sereto.sow import render_sow_to_tex
from sereto.target import Target, render_target_to_tex
from sereto.utils import write_if_different


@validate_call
def ensure_finding_group_layout(
    project_path: DirectoryPath,
    templates: DirectoryPath,
    target: Target,
    finding_group: FindingGroup,
    version: ProjectVersion,
) -> None:
    """Ensures that a template exists for the specified finding group.

    Does not overwrite existing template.
    """
    # Make sure that "layouts/generated" directory exists
    if not (layouts_generated := project_path / "layouts/generated").is_dir():
        layouts_generated.mkdir(parents=True)

    # Create template in "layouts/generated" directory
    template_dst = layouts_generated / f"{target.uname}_{finding_group.uname}.tex.j2"
    if not template_dst.is_file():  # do not overwrite existing templates
        template_src = templates / "categories" / target.data.category / "finding_group.tex.j2"
        copy2(template_src, template_dst, follow_symlinks=False)


@validate_call
def ensure_target_layout(
    project_path: DirectoryPath, templates: DirectoryPath, target: Target, version: ProjectVersion
) -> None:
    """Ensures that a template exists for the specified target.

    Does not overwrite existing template.
    """
    # Make sure that "layouts/generated" directory exists
    if not (layouts_generated := project_path / "layouts/generated").is_dir():
        layouts_generated.mkdir(parents=True)

    # Create template in "layouts/generated" directory
    template_dst = layouts_generated / f"{target.uname}.tex.j2"
    if not template_dst.is_file():  # do not overwrite existing templates
        template_src = templates / "categories" / target.data.category / "target.tex.j2"
        copy2(template_src, template_dst, follow_symlinks=False)


@validate_call
def build_subfinding_to_tex(
    project: Project,
    target: Target,
    sub_finding: SubFinding,
    version: ProjectVersion,
    converter: str | None = None,
) -> None:
    """Process one finding into TeX format and write it to the ".build" directory."""
    # Initialize the build directory
    init_build_dir(project_path=project.path, target=target)

    # Process the finding
    content = render_subfinding_to_tex(
        sub_finding=sub_finding,
        version=version,
        templates=project.settings.templates_path,
        render=project.settings.render,
        converter=converter,
    )

    # Write the finding to the ".build" directory; do not overwrite the same content (preserve timestamps)
    write_if_different(
        file=project.path / ".build" / target.uname / f"{sub_finding.path.name.removesuffix('.md.j2')}.tex",
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
    for sub_finding in finding_group.sub_findings:
        build_subfinding_to_tex(
            project=project, target=target, sub_finding=sub_finding, version=version, converter=converter
        )

    # Ensure that finding group "inner" template exists
    ensure_finding_group_layout(
        project_path=project.path,
        templates=project.settings.templates_path,
        target=target,
        finding_group=finding_group,
        version=version,
    )


@validate_call
def build_finding_group_to_tex(
    project: Project,
    target: Target,
    finding_group: FindingGroup,
    version: ProjectVersion,
) -> Path:
    # Initialize the build directory
    init_build_dir(project_path=project.path, target=target)

    # Determine the indexes for correct section numbering
    target_ix = project.config.at_version(version).targets.index(target)
    fg_ix = target.findings.groups.index(finding_group)

    # Render the finding group to TeX format
    content = render_finding_group_to_tex(
        config=project.config,
        project_path=project.path,
        target=target,
        target_ix=target_ix,
        finding_group=finding_group,
        finding_group_ix=fg_ix,
        version=version,
    )

    # Write the finding group to the ".build" directory; do not overwrite the same content (preserve timestamps)
    destination = project.path / ".build" / target.uname / f"{finding_group.uname}.tex"
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
    for finding_group in target.findings.groups:
        build_finding_group_dependencies(
            project=project, target=target, finding_group=finding_group, version=version, converter=converter
        )

    # Ensure that target "inner" template exists
    ensure_target_layout(
        project_path=project.path, templates=project.settings.templates_path, target=target, version=version
    )


@validate_call
def build_target_to_tex(project: Project, target: Target, version: ProjectVersion) -> Path:
    # Initialize the build directory
    init_build_dir(project_path=project.path, target=target)

    # Determine the index for correct section numbering
    target_ix = project.config.at_version(version).targets.index(target)

    # Render the target to TeX format
    content = render_target_to_tex(
        target=target, config=project.config, version=version, target_ix=target_ix, project_path=project.path
    )

    # Write the target to the ".build" directory; do not overwrite the same content (preserve timestamps)
    destination = project.path / ".build" / target.uname / f"{target.uname}.tex"
    write_if_different(file=destination, content=content)

    # Return the path to the rendered target
    if not destination.is_file():
        raise SeretoPathError(f"something went wrong, the target was not written to '{destination}'")
    return destination


@validate_call
def build_report_to_tex(
    project: Project, template: str, version: ProjectVersion, converter: str | None = None
) -> Path:
    # Process all targets and their dependencies
    for target in project.config.at_version(version).targets:
        build_target_dependencies(project=project, target=target, version=version, converter=converter)

    # Initialize the build directory
    init_build_dir(project_path=project.path, version_config=project.config.at_version(version))

    # Render the report to TeX format
    content = render_report_to_tex(
        project_path=project.path, template=template, config=project.config, version=version
    )

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
    init_build_dir(project_path=project.path, version_config=project.config.at_version(version))

    # Render the SoW to TeX format
    content = render_sow_to_tex(project_path=project.path, config=project.config, version=version)

    # Write the SoW to the ".build" directory; do not overwrite the same content (preserve timestamps)
    destination = project.path / ".build" / f"sow{version.path_suffix}.tex"
    write_if_different(file=destination, content=content)

    # Return the path to the rendered SoW
    if not destination.is_file():
        raise SeretoPathError(f"something went wrong, the SoW was not written to '{destination}'")
    return destination
