from dataclasses import dataclass
from textwrap import dedent
from typing import TYPE_CHECKING, Self

from pydantic import DirectoryPath, validate_call
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.jinja import render_jinja2
from sereto.models.finding import FindingGroup, FindingsConfig, FindingTemplateFrontmatterModel
from sereto.models.risks import Risks
from sereto.models.target import TargetModel
from sereto.models.version import ProjectVersion
from sereto.utils import YAML

if TYPE_CHECKING:
    from sereto.config import Config


@dataclass
class Target:
    data: TargetModel
    findings: FindingsConfig
    path: DirectoryPath

    @classmethod
    @validate_call
    def load(cls, data: TargetModel, path: DirectoryPath) -> Self:
        fc = FindingsConfig.from_yaml(file=path / "findings.yaml")

        # TODO remove when we are finished refactoring also the findings
        for finding in fc.findings:
            finding.path = path / "findings" / finding.path_name

        return cls(
            data=data,
            findings=fc,
            path=path,
        )

    @validate_call
    def to_model(self) -> TargetModel:
        return self.data

    @property
    def uname(self) -> str:
        """Unique name for the target instance.

        Returns:
            The unique name of the target.
        """
        return self.data.uname

    @validate_call
    def select_finding_group(self, selector: int | str | None = None) -> FindingGroup:
        """Select a finding group from the target.

        Args:
            selector: The index or name of the finding group to select.

        Returns:
            The selected finding group.
        """
        finding_groups = self.findings.finding_groups

        # only single finding group present
        if selector is None:
            if len(finding_groups) != 1:
                raise SeretoValueError(
                    f"cannot select finding group; no selector provided and there are {len(finding_groups)} finding "
                    "groups present"
                )
            return finding_groups[0]

        # by index
        if isinstance(selector, int) or selector.isnumeric():
            ix = selector - 1 if isinstance(selector, int) else int(selector) - 1
            if not (0 <= ix <= len(finding_groups) - 1):
                raise SeretoValueError("finding group index out of range")
            return finding_groups[ix]

        # by uname
        fg_matches = [fg for fg in finding_groups if fg.uname == selector]
        if len(fg_matches) != 1:
            raise SeretoValueError(f"finding group with uname {selector!r} not found")
        return fg_matches[0]


@validate_call
def create_findings_config(target: TargetModel, templates: DirectoryPath, last_version: ProjectVersion) -> None:
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
        template_metadata = FindingTemplateFrontmatterModel.load_from(file)

        finding = CommentedMap(
            {
                "name": template_metadata.name,
                "path_name": file.with_suffix("").stem,
                "risks": CommentedMap({str(last_version): template_metadata.risk}),
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


def render_target_to_tex(
    target: TargetModel, config: "Config", version: ProjectVersion, target_ix: int, project_path: DirectoryPath
) -> str:
    """Render selected target (top-level document) to TeX format."""
    assert target.path is not None

    cfg = config.at_version(version)

    # Construct path to target template
    template = project_path / "layouts/target.tex.j2"
    if not template.is_file():
        raise SeretoPathError(f"template not found: '{template}'")

    # Make shallow dict - values remain objects on which we can call their methods in Jinja
    cfg_model = cfg.to_model()
    cfg_dict = {key: getattr(cfg_model, key) for key in cfg_model.model_dump()}

    # Render Jinja2 template
    target_generator = render_jinja2(
        templates=[
            project_path / "layouts/generated",
            project_path / "layouts",
            project_path / "includes",
            project_path,
        ],
        file=template,
        vars={
            "target": target,
            "target_index": target_ix,
            "c": cfg,
            "config": config,
            "version": version,
            "project_path": project_path,
            **cfg_dict,
        },
    )

    return "".join(target_generator)


@validate_call
def get_risks(target: TargetModel, version: ProjectVersion) -> Risks:
    fg = target.findings_config.finding_groups

    return Risks().set_counts(
        critical=len([f for f in fg if version in f.risks and f.risks[version].name == "critical"]),
        high=len([f for f in fg if version in f.risks and f.risks[version].name == "high"]),
        medium=len([f for f in fg if version in f.risks and f.risks[version].name == "medium"]),
        low=len([f for f in fg if version in f.risks and f.risks[version].name == "low"]),
        info=len([f for f in fg if version in f.risks and f.risks[version].name == "info"]),
    )
