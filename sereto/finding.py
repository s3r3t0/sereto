from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

import frontmatter  # type: ignore[import-untyped]
from pydantic import DirectoryPath, FilePath, validate_call

from sereto.convert import apply_convertor
from sereto.enums import FileFormat, Risk
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.jinja import render_jinja2
from sereto.models.finding import (
    FindingGroupModel,
    FindingsConfigModel,
    FindingTemplateFrontmatterModel,
    SubFindingFrontmatterModel,
)
from sereto.models.settings import Render
from sereto.models.version import ProjectVersion
from sereto.risk import Risks
from sereto.utils import lower_alphanum

if TYPE_CHECKING:
    from sereto.config import Config
    from sereto.target import Target


@dataclass
class SubFinding:
    name: str
    risk: Risk
    vars: dict[str, Any]
    path: FilePath
    template: FilePath | None = None
    locators: list[str] = field(default_factory=list)

    @classmethod
    @validate_call
    def load_from(cls, path: FilePath, templates: DirectoryPath) -> Self:
        """
        Load a sub-finding from a file.

        Args:
            path: The path to the sub-finding file.
            templates: The path to the templates directory.

        Returns:
            The loaded sub-finding object.
        """
        frontmatter = SubFindingFrontmatterModel.load_from(path)

        return cls(
            name=frontmatter.name,
            risk=frontmatter.risk,
            vars=frontmatter.variables,
            path=path,
            template=(templates / frontmatter.template_path) if frontmatter.template_path else None,
            locators=frontmatter.locators,
        )

    @property
    def uname(self) -> str:
        """Unique name of the finding."""
        return self.path.name.removesuffix(".md.j2")

    @validate_call
    def validate_vars(self) -> None:
        """Validate the variables of the sub-finding against definition in the template.

        Works only if there is a template path defined, otherwise no validation is done.

        Raises:
            SeretoValueError: If the variables are not valid.
        """
        if self.template is None:
            # no template path, no validation
            return

        # read template frontmatter
        template_frontmatter = FindingTemplateFrontmatterModel.load_from(self.template)

        # report all errors at once
        error = ""

        for var in template_frontmatter.variables:
            # check if variable is defined
            if var.name not in self.vars:
                if var.required:
                    error += f"{var.name}: {var.type_annotation} = {var.description}\n"
                    error += f"  - missing required variable in finding '{self.name}'\n"
                else:
                    # TODO: logger
                    print(
                        f"{var.name}: {var.type_annotation} = {var.description}\n"
                        f"  - optional variable is not defined in finding '{self.name}'\n"
                    )
                continue

            # variable should be a list and is not
            if var.is_list and not isinstance(self.vars[var.name], list):
                error += f"{var.name}: {var.type_annotation} = {var.description}\n"
                error += f"  - variable must be a list in finding '{self.name}'\n"
                continue

            # variable should not be a list and is
            if not var.is_list and isinstance(self.vars[var.name], list):
                error += f"{var.name}: {var.type_annotation} = {var.description}\n"
                error += f"  - variable must not be a list in finding '{self.name}'\n"
                continue

        # report all errors at once
        if len(error) > 0:
            raise SeretoValueError(f"invalid variables in finding '{self.name}'\n{error}")


@dataclass
class FindingGroup:
    """
    Represents a finding group.

    Attributes:
        name: The name of the finding group.
        explicit_risk: Risk to be used for the group. Overrides the calculated risks from sub-findings.
        sub_findings: A list of sub-findings in the group.
        target_locators: A list of locators used to find the target.
    """

    name: str
    explicit_risk: Risk | None
    sub_findings: list[SubFinding]
    _target_locators: list[str]
    _finding_group_locators: list[str]

    @classmethod
    @validate_call
    def load(
        cls,
        name: str,
        group_desc: FindingGroupModel,
        findings_dir: DirectoryPath,
        target_locators: list[str],
        templates: DirectoryPath,
    ) -> Self:
        """
        Load a finding group.

        Args:
            name: The name of the finding group.
            group_desc: The description of the finding group.
            findings_dir: The path to the findings directory.
            target_locators: The locators used to find the target.
            templates: The path to the templates directory.

        Returns:
            The loaded finding group object.
        """
        sub_findings = [
            SubFinding.load_from(path=findings_dir / f"{name}.md.j2", templates=templates)
            for name in group_desc.findings
        ]

        return cls(
            name=name,
            explicit_risk=group_desc.risk,
            sub_findings=sub_findings,
            _target_locators=target_locators,
            _finding_group_locators=group_desc.locators,
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
    def locators(self) -> list[str]:
        """
        Return a de-duplicated list of locators for the finding group.

        Precedence (first non-empty wins):
        1. Explicit locators defined on the finding group
        2. All locators gathered from sub-findings
        3. Locators inherited from the target
        """

        def _unique(seq: list[str]) -> list[str]:
            """Preserve order while removing duplicates."""
            return list(dict.fromkeys(seq))

        # 1. Explicit locators on the group
        if self._finding_group_locators:
            return _unique(self._finding_group_locators)

        # 2. Locators from sub-findings
        sub_locators = _unique([loc for sf in self.sub_findings for loc in sf.locators])
        if sub_locators:
            return sub_locators

        # 3. Fallback to target locators
        return _unique(self._target_locators)

    @property
    @validate_call
    def uname(self) -> str:
        """Unique name of the finding group."""
        return lower_alphanum(f"finding_group_{self.name}")


@dataclass
class Findings:
    """
    Represents a collection of all finding groups inside a target.

    Attributes:
        groups: A list of finding groups.
        target_dir: The path to the target directory containing the findings.
        target_locators: A list of locators used to find the target.
    """

    groups: list[FindingGroup]
    target_dir: FilePath
    target_locators: list[str]

    @classmethod
    @validate_call
    def load_from(cls, target_dir: DirectoryPath, target_locators: list[str], templates: DirectoryPath) -> Self:
        """
        Load findings belonging to the same target.

        Args:
            target_dir: The path to the target directory.
            target_locators: The locators used to find the target.
            templates: The path to the templates directory.

        Returns:
            The loaded findings object.
        """
        config = FindingsConfigModel.load_from(target_dir / "findings.toml")

        groups = [
            FindingGroup.load(
                name=name,
                group_desc=group,
                findings_dir=target_dir / "findings",
                target_locators=target_locators,
                templates=templates,
            )
            for name, group in config.items()
        ]

        # ensure group names are unique
        unique_names = [g.uname for g in groups]
        if len(unique_names) != len(set(unique_names)):
            raise SeretoValueError("finding group unique names must be unique")

        return cls(groups=groups, target_dir=target_dir, target_locators=target_locators)

    @validate_call
    def add_from_template(
        self,
        templates: DirectoryPath,
        template_path: FilePath,
        category: str,
        name: str | None = None,
        risk: Risk | None = None,
        variables: dict[str, Any] | None = None,
    ) -> None:
        """Add a sub-finding from a template.

        This will create a new finding group with a single sub-finding.

        Args:
            templates: The path to the templates directory.
            template_path: The path to the sub-finding template.
            name: The name of the sub-finding. If not provided, the name will use the default value from the template.
            risk: The risk of the sub-finding. If not provided, the risk will use the default value from the template.
        """
        if variables is None:
            variables = {}

        # read template
        template_metadata = FindingTemplateFrontmatterModel.load_from(template_path)
        _, content = frontmatter.parse(template_path.read_text(), encoding="utf-8")

        # write sub-finding to findings directory
        if (sub_finding_path := self.findings_dir / f"{category.lower()}_{template_path.name}").is_file():
            raise SeretoPathError(f"sub-finding already exists: {sub_finding_path}")
        sub_finding_metadata = SubFindingFrontmatterModel(
            name=template_metadata.name,
            risk=template_metadata.risk,
            category=category,
            variables=variables,
            template_path=str(template_path.relative_to(templates)),
        )
        sub_finding_path.write_text(f"+++\n{sub_finding_metadata.dumps_toml()}+++\n\n{content}", encoding="utf-8")

        # load the created sub-finding
        sub_finding = SubFinding.load_from(path=sub_finding_path, templates=templates)

        # prepare finding group
        group = FindingGroup(
            name=name or sub_finding_metadata.name,
            explicit_risk=risk,
            sub_findings=[sub_finding],
            _target_locators=self.target_locators,
            _finding_group_locators=[],
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
    # Validate variables
    sub_finding.validate_vars()

    # Render Jinja2 template
    finding_content = render_jinja2(
        templates=[sub_finding.path.parent],
        file=sub_finding.path,
        vars={
            "f": sub_finding,
            "version": version,
        },
    )

    # Convert to TeX
    content = apply_convertor(
        input=finding_content,
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
    target: "Target",
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
    return render_jinja2(
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
            "target": target,
            "target_index": target_ix,
            "c": version_config,
            "config": config,
            "version": version,
            "project_path": project_path,
        },
    )
