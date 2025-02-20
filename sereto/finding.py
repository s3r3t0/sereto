from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Self

import frontmatter  # type: ignore[import-untyped]
from pydantic import DirectoryPath, FilePath, validate_call

from sereto.convert import apply_convertor
from sereto.enums import FileFormat, Risk
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.jinja import render_jinja2
from sereto.models.finding import (
    FindingFrontmatterModel,
    FindingGroupModel,
    FindingsConfigModel,
    FindingTemplateFrontmatterModel,
)
from sereto.models.settings import Render
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
    def load(cls, name: str, group_desc: FindingGroupModel, findings_dir: DirectoryPath) -> Self:
        """
        Load a finding group.

        Args:
            name: The name of the finding group.
            group_desc: The description of the finding group.
            findings_dir: The path to the findings directory.

        Returns:
            The loaded finding group object.
        """
        sub_findings = [SubFinding.load_from(findings_dir / f"{name}.md.j2") for name in group_desc.findings]

        return cls(
            name=name,
            explicit_risk=group_desc.risk,
            sub_findings=sub_findings,
        )

    def dumps_toml(self) -> str:
        """Dump the finding group to a TOML string."""
        lines = [f'["{self.name}"]']
        if self.explicit_risk is not None:
            lines.append(f'risk = "{self.explicit_risk.value}"')
        if len(self.sub_findings) == 1:
            lines.append(f'findings = ["{self.sub_findings[0].uname}"]')
        else:
            lines.append("findings = [")
            for sf in self.sub_findings:
                lines.append(f'    "{sf.uname}",')
            lines.append("]")
        return "\n".join(lines)

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
        target_dir: The path to the target directory containing the findings.
    """

    groups: list[FindingGroup]
    target_dir: FilePath

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
        config = FindingsConfigModel.load_from(target_dir / "findings.toml")

        groups = [
            FindingGroup.load(name=name, group_desc=group, findings_dir=target_dir / "findings")
            for name, group in config.items()
        ]

        # ensure group names are unique
        unique_names = [g.uname for g in groups]
        if len(unique_names) != len(set(unique_names)):
            raise SeretoValueError("finding group unique names must be unique")

        return cls(groups=groups, target_dir=target_dir)

    @validate_call
    def add_from_template(
        self, template: FilePath, category: str, name: str | None = None, risk: Risk | None = None
    ) -> None:
        """Add a sub-finding from a template.

        This will create a new finding group with a single sub-finding.

        Args:
            template: The path to the sub-finding template.
            name: The name of the sub-finding. If not provided, the name will use the default value from the template.
            risk: The risk of the sub-finding. If not provided, the risk will use the default value from the template.
        """
        # read template
        template_metadata = FindingTemplateFrontmatterModel.load_from(template)
        _, content = frontmatter.parse(template.read_text(), encoding="utf-8")

        # write sub-finding to findings directory
        if (sub_finding_path := self.findings_dir / f"{category.lower()}_{template.name}").is_file():
            raise SeretoPathError(f"sub-finding already exists: {sub_finding_path}")
        sub_finding_metadata = FindingFrontmatterModel(
            name=template_metadata.name, risk=template_metadata.risk, category=category
        )
        sub_finding_path.write_text(f"+++\n{sub_finding_metadata.dumps_toml()}+++\n\n{content}", encoding="utf-8")

        # load the created sub-finding
        sub_finding = SubFinding.load_from(sub_finding_path)

        # prepare finding group
        group = FindingGroup(
            name=name or sub_finding_metadata.name,
            explicit_risk=risk,
            sub_findings=[sub_finding],
        )

        # write the finding group to findings.toml
        with self.config_file.open("a", encoding="utf-8") as f:
            f.write(f"\n{group.dumps_toml()}\n")

        # add to loaded finding groups
        self.groups.append(group)

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
    def config_file(self) -> Path:
        """Get the path to the findings.toml configuration file"""
        return self.target_dir / "findings.toml"

    @property
    def findings_dir(self) -> Path:
        """Get the path to the directory containing the findings"""
        return self.target_dir / "findings"

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


def render_subfinding_to_tex(
    sub_finding: SubFinding,
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
            "f": sub_finding,
            "version": version,
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
            "target_index": target_ix,
            "c": version_config,
            "config": config,
            "version": version,
            "project_path": project_path,
        },
    )

    return "".join(finding_group_generator)
