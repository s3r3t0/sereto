import frontmatter  # type: ignore[import-untyped]
from pydantic import ValidationError, validate_call
from rich.prompt import Confirm
from rich.table import Table
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from sereto.cli.console import Console
from sereto.convert import convert_file_to_tex
from sereto.exceptions import SeretoPathError, SeretoRuntimeError, SeretoValueError
from sereto.jinja import render_j2
from sereto.models.config import Config
from sereto.models.finding import Finding, FindingGroup, FindingsConfig, TemplateMetadata
from sereto.models.report import Report
from sereto.models.settings import Settings
from sereto.models.target import Target
from sereto.models.version import ReportVersion
from sereto.utils import YAML


@validate_call
def add_finding(
    report: Report,
    settings: Settings,
    target_selector: str | None,
    format: str,
    name: str,
) -> None:
    target = report.select_target(settings=settings, selector=target_selector)

    # read template
    template_path = settings.templates_path / "categories" / target.category / "findings" / f"{name}.{format}.j2"
    if not template_path.is_file():
        raise SeretoPathError(f"template not found '{template_path}'")

    _, content = frontmatter.parse(template_path.read_text())

    # write template content
    assert target.path is not None
    finding_dir = target.path / "findings" / name
    finding_dir.mkdir(exist_ok=True)
    dst_path = finding_dir / f"{name}{report.config.last_version().path_suffix}.{format}.j2"

    if dst_path.is_file() and not Confirm.ask(
        f'[yellow]Destination "{dst_path}" exists. Overwrite?',
        console=Console(),
        default=False,
    ):
        raise SeretoRuntimeError("cannot proceed")

    dst_path.write_text(content, encoding="utf-8")


@validate_call
def show_findings(config: Config, version: ReportVersion) -> None:
    Console().log(f"showing findings for version {version}")
    cfg = config.at_version(version=version)

    for target in cfg.targets:
        Console().line()
        table = Table("Finding name", "Category", "Risk", title=f"Target {target.name}")
        if target.path is None:
            raise SeretoValueError(f"target path not set for {target.uname!r}")

        fc = FindingsConfig.from_yaml_file(filepath=target.path / "findings.yaml")

        for finding_group in fc.finding_groups:
            table.add_row(finding_group.name, target.category, finding_group.risks[version])

        Console().print(table, justify="center")


@validate_call
def update_findings(report: Report, settings: Settings) -> None:
    for target in report.config.targets:
        if target.path is None:
            raise SeretoValueError(f"target path not set for {target.uname!r}")

        findings_path = target.path / "findings.yaml"
        findings = YAML.load(findings_path)
        fc = FindingsConfig.from_yaml_file(filepath=findings_path)
        category_templates = settings.templates_path / "categories" / target.category / "findings"

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
                    "risks": CommentedMap({str(report.config.last_version()): template_metadata.risk}),
                    "vars": CommentedMap(),
                }
            )

            for var in template_metadata.variables:
                finding["vars"][var.name] = CommentedSeq() if var.list else ""
                comment = f'{"[required]" if var.required else "[optional]"} {var.description}'
                finding["vars"].yaml_add_eol_comment(comment, var.name)

            findings["findings"].append(finding)
            Console().log(f"discovered new finding: '{name}'")

        with findings_path.open(mode="w", encoding="utf-8") as f:
            YAML.dump(findings, f)


@validate_call
def render_finding_j2(
    finding: Finding,
    target: Target,
    version: ReportVersion,
) -> None:
    assert finding.path is not None and target.path is not None

    finding_j2_path = finding.path / f"{finding.path_name}{version.path_suffix}.{finding.format.value}.j2"
    if not finding_j2_path.is_file():
        raise SeretoPathError(f"finding template not found: '{finding_j2_path}'")

    with finding_j2_path.with_suffix("").open("w", encoding="utf-8") as f:
        text_generator = render_j2(
            templates=[finding.path, target.path / "findings"],
            file=finding_j2_path,
            vars={
                "target": target.model_dump(),
                "version": version,
                "f": finding.model_dump(),
            },
        )

        for chunk in text_generator:
            f.write(chunk)

        Console().log(f"rendered Jinja finding: {finding_j2_path.with_suffix('').relative_to(target.path.parent)}")


@validate_call
def render_finding_group_findings_j2(
    finding_group: FindingGroup,
    target: Target,
    settings: Settings,
    version: ReportVersion,
    convert_recipe: str | None = None,
) -> None:
    assert target.path is not None

    for finding in finding_group.findings:
        if version in finding.risks:
            finding.assert_required_vars(templates_path=settings.templates_path, category=target.category)
            render_finding_j2(finding=finding, target=target, version=version)
            convert_file_to_tex(
                finding=finding,
                render=settings.render,
                templates=settings.templates_path,
                version=version,
                recipe=convert_recipe,
            )


@validate_call
def render_finding_group_j2(
    finding_group: FindingGroup,
    target: Target,
    report: Report,
    settings: Settings,
    version: ReportVersion,
    convert_recipe: str | None = None,
) -> None:
    cfg = report.config.at_version(version=version)
    report_path = Report.get_path(dir_subtree=settings.reports_path)

    render_finding_group_findings_j2(
        finding_group=finding_group, target=target, settings=settings, version=version, convert_recipe=convert_recipe
    )

    finding_group_j2_path = report_path / "finding_standalone_wrapper.tex.j2"
    if not finding_group_j2_path.is_file():
        raise SeretoPathError(f"template not found: '{finding_group_j2_path}'")

    # make shallow dict - values remain objects on which we can call their methods in Jinja
    cfg_dict = {key: getattr(cfg, key) for key in cfg.model_dump()}
    finding_group_generator = render_j2(
        templates=report_path,
        file=finding_group_j2_path,
        vars={
            "finding_group": finding_group,
            "target": target,
            "version": version,
            "report_path": report_path,
            **cfg_dict,
        },
    )

    finding_group_tex_path = report_path / f"{target.uname}_{finding_group.uname}.tex"

    with finding_group_tex_path.open("w", encoding="utf-8") as f:
        for chunk in finding_group_generator:
            f.write(chunk)
        Console().log(f"rendered Jinja template: {finding_group_tex_path.relative_to(report_path)}")
