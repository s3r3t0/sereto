from pathlib import Path
from textwrap import dedent

import frontmatter  # type: ignore[import-untyped]
from pydantic import ValidationError, validate_call
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from sereto.cli.console import Console
from sereto.convert import convert_file_to_tex
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.finding import render_finding_j2
from sereto.jinja import render_j2
from sereto.models.finding import TemplateMetadata
from sereto.models.report import Report
from sereto.models.settings import Settings
from sereto.models.target import Target
from sereto.models.version import ReportVersion
from sereto.risks import Risks
from sereto.utils import YAML


@validate_call
def render_target_findings_j2(
    target: Target,
    settings: Settings,
    version: ReportVersion,
    convert_recipe: str | None = None,
) -> None:
    assert target.path is not None

    for finding in target.findings_config.included_findings():
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


def create_findings_config(target: Target, report: Report, templates: Path) -> None:
    findings = YAML.load(
        dedent(
            """
            ############################################################
            #    Select findings you want to include in the report     #
            #----------------------------------------------------------#
            #  report_include:                                         #
            #  - name: "Group Finding"                                 #
            #    findings:                                             #
            #    - "finding_one"                                       #
            #    - "finding_two"                                       #
            #                                                          #
            #  - name: "Standalone Finding"                            #
            #    findings:                                             #
            #    - "standalone_finding"                                #
            ############################################################

            report_include: []


            ############################################################
            #    All discovered findings from the templates            #
            ############################################################

            findings:
            """
        )
    )

    findings["findings"] = CommentedSeq()

    for file in templates.glob(pattern="*.j2"):
        metadata, _ = frontmatter.parse(file.read_text())

        try:
            template_metadata = TemplateMetadata.model_validate(metadata)
        except ValidationError as ex:
            raise SeretoValueError(f"invalid template metadata in '{file}'") from ex

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

    assert target.path is not None

    with (target.path / "findings.yaml").open(mode="w", encoding="utf-8") as f:
        YAML.dump(findings, f)


@validate_call
def render_target_j2(
    target: Target,
    report: Report,
    settings: Settings,
    version: ReportVersion,
    convert_recipe: str | None = None,
) -> None:
    cfg = report.config.at_version(version=version)
    report_path = Report.get_path(dir_subtree=settings.reports_path)

    render_target_findings_j2(target=target, settings=settings, version=version, convert_recipe=convert_recipe)

    target_j2_path = report_path / "target_standalone_wrapper.tex.j2"
    if not target_j2_path.is_file():
        raise SeretoPathError(f"template not found: '{target_j2_path}'")

    # make shallow dict - values remain objects on which we can call their methods in Jinja
    cfg_dict = {key: getattr(cfg, key) for key in cfg.model_dump()}
    target_generator = render_j2(
        templates=report_path,
        file=target_j2_path,
        vars={"target": target, "version": version, "report_path": report_path, **cfg_dict},
    )

    target_tex_path = report_path / f"{target.uname}.tex"

    with target_tex_path.open("w", encoding="utf-8") as f:
        for chunk in target_generator:
            f.write(chunk)
        Console().log(f"rendered Jinja template: {target_tex_path.relative_to(report_path)}")


@validate_call
def get_risks(target: Target, version: ReportVersion) -> Risks:
    fg = target.findings_config.finding_groups

    return Risks().set_counts(
        critical=len([f for f in fg if version in f.risks and f.risks[version].name == "critical"]),
        high=len([f for f in fg if version in f.risks and f.risks[version].name == "high"]),
        medium=len([f for f in fg if version in f.risks and f.risks[version].name == "medium"]),
        low=len([f for f in fg if version in f.risks and f.risks[version].name == "low"]),
        info=len([f for f in fg if version in f.risks and f.risks[version].name == "informational"]),
    )
