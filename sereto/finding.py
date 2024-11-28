import frontmatter  # type: ignore[import-untyped]
from prompt_toolkit.shortcuts import yes_no_dialog
from pydantic import ValidationError, validate_call
from rich.table import Table
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from sereto.cli.utils import Console
from sereto.convert import convert_file_to_tex
from sereto.enums import FileFormat
from sereto.exceptions import SeretoPathError, SeretoRuntimeError, SeretoValueError
from sereto.jinja import render_j2
from sereto.models.config import Config
from sereto.models.finding import Finding, FindingGroup, FindingsConfig, TemplateMetadata
from sereto.models.project import Project
from sereto.models.target import Target
from sereto.models.version import ProjectVersion
from sereto.utils import YAML, write_if_different


@validate_call
def add_finding(
    project: Project,
    target_selector: str | None,
    format: str,
    name: str,
    interactive: bool = False,
) -> None:
    target = project.select_target(selector=target_selector)

    # read template
    template_path = (
        project.settings.templates_path / "categories" / target.category / "findings" / f"{name}.{format}.j2"
    )
    if not template_path.is_file():
        raise SeretoPathError(f"template not found '{template_path}'")

    _, content = frontmatter.parse(template_path.read_text())

    # write template content
    assert target.path is not None
    finding_dir = target.path / "findings" / name
    finding_dir.mkdir(exist_ok=True)
    dst_path = finding_dir / f"{name}{project.config.last_version().path_suffix}.{format}.j2"

    # Destination file exists and we cannot proceed
    if dst_path.is_file() and (
        not interactive
        or not yes_no_dialog(title="Warning", text=f"Destination '{dst_path}' exists. Overwrite?").run()
    ):
        raise SeretoRuntimeError("cannot proceed")

    dst_path.write_text(content, encoding="utf-8")


@validate_call
def show_findings(config: Config, version: ProjectVersion | None = None) -> None:
    if version is None:
        version = config.last_version()

    Console().log(f"Showing findings for version {version}")

    cfg = config.at_version(version=version)

    for target in cfg.targets:
        Console().line()
        table = Table("Finding name", "Category", "Risk", title=f"Target {target.name}")
        if target.path is None:
            raise SeretoValueError(f"target path not set for {target.uname!r}")

        fc = FindingsConfig.from_yaml(file=target.path / "findings.yaml")

        for finding_group in fc.finding_groups:
            table.add_row(finding_group.name, target.category, finding_group.risks[version])

        Console().print(table, justify="center")


@validate_call
def update_findings(project: Project) -> None:
    for target in project.config.last_config().targets:
        if target.path is None:
            raise SeretoValueError(f"target path not set for {target.uname!r}")

        findings_path = target.path / "findings.yaml"
        findings = YAML.load(findings_path)
        fc = FindingsConfig.from_yaml(file=findings_path)
        category_templates = project.settings.templates_path / "categories" / target.category / "findings"

        for file in category_templates.glob(pattern="*.j2"):
            metadata, _ = frontmatter.parse(file.read_text())

            try:
                template_metadata = TemplateMetadata.model_validate(metadata)
            except ValidationError as ex:
                raise SeretoValueError(f"invalid template metadata in '{file}'") from ex

            name = template_metadata.name

            if len([f for f in fc.findings if f.name == name]) > 0:
                continue

            finding = CommentedMap(
                {
                    "name": template_metadata.name,
                    "path_name": file.with_suffix("").stem,
                    "risks": CommentedMap({str(project.config.last_version()): template_metadata.risk}),
                    "vars": CommentedMap(),
                }
            )

            for var in template_metadata.variables:
                finding["vars"][var.name] = CommentedSeq() if var.list else ""
                comment = f'{"[required]" if var.required else "[optional]"} {var.description}'
                finding["vars"].yaml_add_eol_comment(comment, var.name)

            findings["findings"].append(finding)
            Console().log(f"Discovered new finding: '{name}'")

        with findings_path.open(mode="w", encoding="utf-8") as f:
            YAML.dump(findings, f)


@validate_call
def render_finding_j2(
    finding: Finding,
    target: Target,
    version: ProjectVersion,
) -> bool:
    """Render a Jinja template for a finding.

    Args:
        finding: The finding to render.
        target: The target for which the finding is rendered.
        version: The version of the project.

    Returns:
        True if changes were made to the destination file, False otherwise.
    """
    assert finding.path is not None and target.path is not None

    finding_j2_path = finding.path / f"{finding.path_name}{version.path_suffix}.{finding.format.value}.j2"
    if not finding_j2_path.is_file():
        raise SeretoPathError(f"finding template not found: '{finding_j2_path}'")

    text_generator = render_j2(
        templates=[finding.path, target.path / "findings"],
        file=finding_j2_path,
        vars={
            "target": target.model_dump(),
            "version": version,
            "f": finding.model_dump(),
        },
    )

    finding_path = finding_j2_path.with_suffix("")
    changed = write_if_different(file=finding_path, content="".join(text_generator))
    Console().log(f"Rendered Jinja finding: {finding_path.relative_to(target.path.parent)}")
    return changed


@validate_call
def render_finding_group_j2(
    project: Project,
    target: Target,
    finding_group: FindingGroup,
    version: ProjectVersion,
    convert_recipe: str | None = None,
) -> None:
    cfg = project.config.at_version(version=version)

    for finding in finding_group.findings:
        if version in finding.risks:
            finding.assert_required_vars(templates=project.settings.templates_path, category=target.category)
            content_changed = render_finding_j2(finding=finding, target=target, version=version)
            if finding.format != FileFormat.tex and content_changed:
                convert_file_to_tex(
                    finding=finding,
                    render=project.settings.render,
                    templates=project.settings.templates_path,
                    version=version,
                    recipe=convert_recipe,
                )

    finding_group_j2_path = project.path / "finding_standalone_wrapper.tex.j2"
    if not finding_group_j2_path.is_file():
        raise SeretoPathError(f"template not found: '{finding_group_j2_path}'")

    # make shallow dict - values remain objects on which we can call their methods in Jinja
    cfg_dict = {key: getattr(cfg, key) for key in cfg.model_dump()}
    finding_group_generator = render_j2(
        templates=project.path,
        file=finding_group_j2_path,
        vars={
            "finding_group": finding_group,
            "target": target,
            "c": cfg,
            "config": project.config,
            "version": version,
            "report_path": project.path,
            **cfg_dict,
        },
    )

    finding_group_tex_path = project.path / f"{target.uname}_{finding_group.uname}.tex"
    write_if_different(file=finding_group_tex_path, content="".join(finding_group_generator))
    Console().log(f"Rendered Jinja template: {finding_group_tex_path.relative_to(project.path)}")
