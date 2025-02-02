from textwrap import dedent

import frontmatter  # type: ignore[import-untyped]
from pydantic import DirectoryPath, ValidationError, validate_call
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.jinja import render_jinja2
from sereto.models.finding import TemplateMetadata
from sereto.models.project import Project
from sereto.models.risks import Risks
from sereto.models.target import Target
from sereto.models.version import ProjectVersion
from sereto.utils import YAML


@validate_call
def create_findings_config(target: Target, project: Project, templates: DirectoryPath) -> None:
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
                "risks": CommentedMap({str(project.config.last_version()): template_metadata.risk}),
                "vars": CommentedMap(),
            }
        )

        for var in template_metadata.variables:
            finding["vars"][var.name] = CommentedSeq() if var.list else ""
            comment = f"{'[required]' if var.required else '[optional]'} {var.description}"
            finding["vars"].yaml_add_eol_comment(comment, var.name)

        findings["findings"].append(finding)

    assert target.path is not None

    with (target.path / "findings.yaml").open(mode="w", encoding="utf-8") as f:
        YAML.dump(findings, f)


@validate_call
def render_target_to_tex(project: Project, target: Target, target_ix: int, version: ProjectVersion) -> str:
    """Render selected target (top-level document) to TeX format."""
    assert target.path is not None

    cfg = project.config.at_version(version=version)

    # Construct path to target template
    template = project.path / "layouts/target.tex.j2"
    if not template.is_file():
        raise SeretoPathError(f"template not found: '{template}'")

    # Make shallow dict - values remain objects on which we can call their methods in Jinja
    cfg_dict = {key: getattr(cfg, key) for key in cfg.model_dump()}

    # Render Jinja2 template
    target_generator = render_jinja2(
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
            "c": cfg,
            "config": project.config,
            "version": version,
            "project_path": project.path,
            **cfg_dict,
        },
    )

    return "".join(target_generator)


@validate_call
def get_risks(target: Target, version: ProjectVersion) -> Risks:
    fg = target.findings_config.finding_groups

    return Risks().set_counts(
        critical=len([f for f in fg if version in f.risks and f.risks[version].name == "critical"]),
        high=len([f for f in fg if version in f.risks and f.risks[version].name == "high"]),
        medium=len([f for f in fg if version in f.risks and f.risks[version].name == "medium"]),
        low=len([f for f in fg if version in f.risks and f.risks[version].name == "low"]),
        info=len([f for f in fg if version in f.risks and f.risks[version].name == "info"]),
    )
