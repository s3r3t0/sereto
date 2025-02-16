from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from pydantic import DirectoryPath, FilePath, validate_call

from sereto.convert import apply_convertor
from sereto.enums import FileFormat, Risk
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.jinja import render_jinja2
from sereto.models.finding import (
    FindingFrontmatterModel,
    FindingGroupModel,
    FindingsConfigModel,
)
from sereto.models.settings import Render
from sereto.models.target import TargetModel
from sereto.models.version import ProjectVersion
from sereto.risk import Risks
from sereto.utils import lower_alphanum

if TYPE_CHECKING:
    from sereto.config import Config


@dataclass
class SubFinding:
    name: str
    risk: Risk
    # vars: dict[str, Any]
    path: FilePath

    @classmethod
    @validate_call
    def load_from(cls, path: FilePath) -> Self:
        """
        Load a sub-finding from a file.

        Args:
            path: The path to the sub-finding file.

        Returns:
            The loaded sub-finding object.
        """
        frontmatter = FindingFrontmatterModel.load_from(path)

        return cls(
            name=frontmatter.name,
            risk=frontmatter.risk,
            path=path,
        )

    @property
    def uname(self) -> str:
        """Unique name of the finding."""
        return self.path.name.removesuffix(".md.j2")


@dataclass
class FindingGroup:
    """
    Represents a finding group.

    Attributes:
        name: The name of the finding group.
        explicit_risk: Risk to be used for the group. Overrides the calculated risks from sub-findings.
        sub_findings: A list of sub-findings in the group.
    """

    name: str
    explicit_risk: Risk | None
    sub_findings: list[SubFinding]

    @classmethod
    @validate_call
    def load(cls, group_desc: FindingGroupModel, findings_dir: DirectoryPath) -> Self:
        """
        Load a finding group.

        Args:
            group_desc: The description of the finding group.
            findings_dir: The path to the findings directory.

        Returns:
            The loaded finding group object.
        """
        sub_findings = [SubFinding.load_from(findings_dir / f"{name}.md.j2") for name in group_desc.findings]

        return cls(
            name=group_desc.name,
            explicit_risk=group_desc.risk,
            sub_findings=sub_findings,
        )

    @property
    def risk(self) -> Risk:
        """
        Get the finding group risk.

        Returns:
            The explicit risk if set, otherwise the highest risk from the sub-findings.
        """
        if self.explicit_risk is not None:
            return self.explicit_risk
        return max([sf.risk for sf in self.sub_findings], key=lambda r: r.to_int())

    @property
    @validate_call
    def uname(self) -> str:
        """Unique name of the finding group."""
        return lower_alphanum(f"finding_group_{self.name}")


@dataclass
class Findings:
    """
    Represents a collection of findings.

    Attributes:
        groups: A list of finding groups.
        config_path: The path to the findings configuration file.
    """

    groups: list[FindingGroup]
    config_path: FilePath

    @classmethod
    @validate_call
    def load_from(cls, target_dir: DirectoryPath) -> Self:
        """
        Load a collection of findings.

        Args:
            findings_desc: The description of the findings.
            path: The path to the target directory.

        Returns:
            The loaded findings object.
        """
        config = FindingsConfigModel.from_yaml(target_dir / "findings.yaml")

        groups = [
            FindingGroup.load(group_desc=group, findings_dir=target_dir / "findings")
            for group in config.report_include
        ]

        # ensure group names are unique
        unique_names = [g.uname for g in groups]
        if len(unique_names) != len(set(unique_names)):
            raise SeretoValueError("finding group unique names must be unique")

        return cls(groups=groups, config_path=target_dir / "findings.yaml")

    @validate_call
    def select_group(self, selector: int | str | None = None) -> FindingGroup:
        """Select a finding group by index or name.

        Args:
            selector: The index or name of the finding group to select.

        Returns:
            The selected finding group.
        """
        # only single finding group present
        if selector is None:
            if len(self.groups) != 1:
                raise SeretoValueError(
                    f"cannot select finding group; no selector provided and there are {len(self.groups)} finding "
                    "groups present"
                )
            return self.groups[0]

        # by index
        if isinstance(selector, int) or selector.isnumeric():
            ix = selector - 1 if isinstance(selector, int) else int(selector) - 1
            if not (0 <= ix <= len(self.groups) - 1):
                raise SeretoValueError("finding group index out of range")
            return self.groups[ix]

        # by unique name
        matching_groups = [g for g in self.groups if g.uname == selector]
        if len(matching_groups) != 1:
            raise SeretoValueError(f"finding group with uname {selector!r} not found")
        return matching_groups[0]

    @property
    def risks(self) -> Risks:
        """Get the summary of risks for the specified version."""
        return Risks(
            critical=len([g for g in self.groups if g.risk == Risk.critical]),
            high=len([g for g in self.groups if g.risk == Risk.high]),
            medium=len([g for g in self.groups if g.risk == Risk.medium]),
            low=len([g for g in self.groups if g.risk == Risk.low]),
            info=len([g for g in self.groups if g.risk == Risk.info]),
            closed=len([g for g in self.groups if g.risk == Risk.closed]),
        )


@validate_call
def render_subfinding_to_tex(
    sub_finding: SubFinding,
    target: TargetModel,
    version: ProjectVersion,
    templates: DirectoryPath,
    render: Render,
    converter: str | None = None,
) -> str:
    # # TODO: Ensure required variables are present
    # finding.assert_required_vars(templates=templates, category=category)

    # Render Jinja2 template
    finding_generator = render_jinja2(
        templates=[sub_finding.path.parent],
        file=sub_finding.path,
        vars={
            "target": target.model_dump(),
            "version": version,
            "f": sub_finding,
        },
    )

    # Convert to TeX
    content = apply_convertor(
        input="".join(finding_generator),
        input_format=FileFormat.md,
        output_format=FileFormat.tex,
        render=render,
        recipe=converter,
        replacements={
            "%TEMPLATES%": str(templates),
        },
    )

    return content


def render_finding_group_to_tex(
    config: "Config",
    project_path: DirectoryPath,
    target: TargetModel,
    target_ix: int,
    finding_group: FindingGroup,
    finding_group_ix: int,
    version: ProjectVersion,
) -> str:
    """Render selected finding group (top-level document) to TeX format."""
    version_config = config.at_version(version=version)

    # Construct path to finding group template
    template = project_path / "layouts/finding_group.tex.j2"
    if not template.is_file():
        raise SeretoPathError(f"template not found: '{template}'")

    # Make shallow dict - values remain objects on which we can call their methods in Jinja
    cfg_model = version_config.to_model()
    cfg_dict = {key: getattr(cfg_model, key) for key in cfg_model.model_dump()}

    # Render Jinja2 template
    finding_group_generator = render_jinja2(
        templates=[
            project_path / "layouts/generated",
            project_path / "layouts",
            project_path / "includes",
            project_path,
        ],
        file=template,
        vars={
            "finding_group": finding_group,
            "finding_group_index": finding_group_ix,
            "target": target.model_dump(),
            "target_index": target_ix,
            "c": version_config,
            "config": config,
            "version": version,
            "project_path": project_path,
            **cfg_dict,
        },
    )

    return "".join(finding_group_generator)
