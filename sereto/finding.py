import frontmatter  # type: ignore[import-untyped]
from prompt_toolkit.shortcuts import yes_no_dialog
from pydantic import DirectoryPath, validate_call
from rich.table import Table
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from sereto.cli.utils import Console
from sereto.config import Config
from sereto.convert import apply_convertor
from sereto.enums import FileFormat
from sereto.exceptions import SeretoPathError, SeretoRuntimeError
from sereto.jinja import render_jinja2
from sereto.models.finding import Finding, FindingGroup, FindingsConfig, FindingTemplateFrontmatterModel
from sereto.models.project import Project
from sereto.models.settings import Render
from sereto.models.target import TargetModel
from sereto.models.version import ProjectVersion
from sereto.utils import YAML


@validate_call
def add_finding(
    project: Project,
    target_selector: str | None,
    format: str,
    name: str,
    interactive: bool = False,
) -> None:
    # select target
    target = project.config_new.last_config.select_target(
        project_path=project.path, categories=project.settings.categories, selector=target_selector
    )

    # load finding info from findings.yaml config
    fc = FindingsConfig.from_yaml(file=target.path / "findings.yaml")
    finding = fc.get_finding(path_name=name)
    category = finding.category if finding.category is not None else target.data.category
    template_path = finding.template_path(templates=project.settings.templates_path, category=category)

    # read finding's template content
    _, content = frontmatter.parse(template_path.read_text())

    # add finding to project
    finding_dir = target.path / "findings" / name
    finding_dir.mkdir(exist_ok=True)
    dst_path = finding_dir / f"{name}{project.config_new.last_version.path_suffix}.{format}.j2"

    # destination file exists and we cannot proceed
    if dst_path.is_file() and (
        not interactive
        or not yes_no_dialog(title="Warning", text=f"Destination '{dst_path}' exists. Overwrite?").run()
    ):
        raise SeretoRuntimeError("cannot proceed")

    dst_path.write_text(content, encoding="utf-8")


# TODO move to cli module
@validate_call
def show_findings(config: Config, version: ProjectVersion | None = None) -> None:
    if version is None:
        version = config.last_version

    Console().log(f"Showing findings for version {version}")

    cfg = config.at_version(version=version)

    for target in cfg.targets:
        Console().line()
        table = Table("Finding name", "Category", "Risk", title=f"Target {target.data.name}")
        fc = FindingsConfig.from_yaml(file=target.path / "findings.yaml")

        for finding_group in fc.finding_groups:
            table.add_row(finding_group.name, target.data.category, finding_group.risks[version])

        Console().print(table, justify="center")


@validate_call
def update_findings(project: Project) -> None:
    for target in project.config_new.last_config.targets:
        findings_path = target.path / "findings.yaml"
        findings = YAML.load(findings_path)
        fc = FindingsConfig.from_yaml(file=findings_path)
        category_templates = project.settings.templates_path / "categories" / target.data.category / "findings"

        for file in category_templates.glob(pattern="*.j2"):
            template_metadata = FindingTemplateFrontmatterModel.load_from(file)
            name = template_metadata.name

            if len([f for f in fc.findings if f.name == name]) > 0:
                continue

            finding = CommentedMap(
                {
                    "name": template_metadata.name,
                    "path_name": file.with_suffix("").stem,
                    "risks": CommentedMap({str(project.config_new.last_version): template_metadata.risk}),
                    "vars": CommentedMap(),
                }
            )

            for var in template_metadata.variables:
                finding["vars"][var.name] = CommentedSeq() if var.list else ""
                comment = f"{'[required]' if var.required else '[optional]'} {var.description}"
                finding["vars"].yaml_add_eol_comment(comment, var.name)

            findings["findings"].append(finding)
            Console().log(f"Discovered new finding: '{name}'")

        with findings_path.open(mode="w", encoding="utf-8") as f:
            YAML.dump(findings, f)


@validate_call
def render_finding_to_tex(
    target: TargetModel,
    finding: Finding,
    version: ProjectVersion,
    templates: DirectoryPath,
    render: Render,
    converter: str | None = None,
) -> str:
    assert finding.path is not None and target.path is not None
    category = finding.category if finding.category is not None else target.category
    finding.assert_required_vars(templates=templates, category=category)

    # Construct path to finding template
    finding_template = finding.path / f"{finding.path_name}{version.path_suffix}.{finding.format.value}.j2"
    if not finding_template.is_file():
        raise SeretoPathError(f"finding template not found: '{finding_template}'")

    # Render Jinja2 template
    finding_generator = render_jinja2(
        templates=[finding.path, target.path / "findings"],
        file=finding_template,
        vars={
            "target": target.model_dump(),
            "version": version,
            "f": finding.model_dump(),
        },
    )

    # Convert to TeX
    content = apply_convertor(
        input="".join(finding_generator),
        input_format=finding.format,
        output_format=FileFormat.tex,
        render=render,
        recipe=converter,
        replacements={
            "%TEMPLATES%": str(templates),
        },
    )

    return content


@validate_call
def render_finding_group_to_tex(
    project: Project,
    target: TargetModel,
    target_ix: int,
    finding_group: FindingGroup,
    finding_group_ix: int,
    version: ProjectVersion,
) -> str:
    """Render selected finding group (top-level document) to TeX format."""
    cfg = project.config_new.at_version(version=version)

    # Construct path to finding group template
    template = project.path / "layouts/finding_group.tex.j2"
    if not template.is_file():
        raise SeretoPathError(f"template not found: '{template}'")

    # Make shallow dict - values remain objects on which we can call their methods in Jinja
    cfg_model = cfg.to_model()
    cfg_dict = {key: getattr(cfg_model, key) for key in cfg_model.model_dump()}

    # Render Jinja2 template
    finding_group_generator = render_jinja2(
        templates=[
            project.path / "layouts/generated",
            project.path / "layouts",
            project.path / "includes",
            project.path,
        ],
        file=template,
        vars={
            "finding_group": finding_group,
            "finding_group_index": finding_group_ix,
            "target": target,
            "target_index": target_ix,
            "c": cfg,
            "config": project.config_new,
            "version": version,
            "project_path": project.path,
            **cfg_dict,
        },
    )

    return "".join(finding_group_generator)
