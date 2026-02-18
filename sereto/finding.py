import random
import string
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self, cast

import frontmatter  # type: ignore[import-untyped]
import tomlkit
from pydantic import DirectoryPath, FilePath, validate_call
from tomlkit.items import Table

from sereto.enums import FileFormat, Risk
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.date import SeretoDate
from sereto.models.finding import (
    FindingGroupModel,
    FindingsConfigModel,
    FindingTemplateFrontmatterModel,
    SubFindingFrontmatterModel,
)
from sereto.models.locator import LocatorModel, get_locator_types
from sereto.risk import Risks
from sereto.utils import lower_alphanum


def _unique_locators(seq: Iterable[LocatorModel]) -> list[LocatorModel]:
    """Preserve locator order while removing duplicates (ignoring description)."""
    seen: set[tuple[Any, Any]] = set()
    result: list[LocatorModel] = []
    for loc in seq:
        key = (loc.type, loc.value)
        if key not in seen:
            seen.add(key)
            result.append(loc)
    return result


def _filter_locators_by_type(seq: Iterable[LocatorModel], show_types: Iterable[str]) -> list[LocatorModel]:
    allowed = set(show_types)
    if len(allowed) == 0:
        return []
    return [loc for loc in seq if loc.type in allowed]


def _locators_equal(
    first: Iterable[LocatorModel],
    second: Iterable[LocatorModel],
) -> bool:
    """Check if two locator sequences are equal, ignoring order and description."""

    def key_set(seq: Iterable[LocatorModel]) -> set[tuple[Any, Any]]:
        return {(loc.type, loc.value) for loc in seq}

    return key_set(first) == key_set(second)


@dataclass
class SubFinding:
    name: str
    risk: Risk
    vars: dict[str, Any]
    path: FilePath
    template: FilePath | None = None
    locators: list[LocatorModel] = field(default_factory=list)
    format: FileFormat = FileFormat.md
    reported_on: SeretoDate | None = None

    @classmethod
    @validate_call
    def load_from(cls, path: FilePath, templates: DirectoryPath) -> Self:
        """Load a sub-finding from a file.

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
            format=frontmatter.format,
            reported_on=frontmatter.reported_on,
        )

    @property
    def uname(self) -> str:
        """Unique name of the finding."""
        return self.path.name.removesuffix(".md.j2")

    @validate_call
    def filter_locators(self, type: str | Iterable[str]) -> list[LocatorModel]:
        """Filter locators by type.

        Args:
            type: The type of locators to filter by. Can be a single type or an iterable of types.

        Returns:
            A list of locators of the specified type.
        """
        type = [type] if isinstance(type, str) else list(type)
        return [loc for loc in self.locators if loc.type in type]

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
    """Represents a finding group.

    Attributes:
        name: The name of the finding group.
        explicit_risk: Risk to be used for the group. Overrides the calculated risks from sub-findings.
        sub_findings: A list of sub-findings in the group.
        _target_locators: A list of locators used to find the target.
        _finding_group_locators: A list of locators defined on the finding group.
        _show_locator_types: A list of locator types to return from the locators() property.
        extras: A dictionary of extra fields (e.g. from plugins).
    """

    name: str
    explicit_risk: Risk | None
    sub_findings: list[SubFinding]
    _target_locators: list[LocatorModel]
    _finding_group_locators: list[LocatorModel]
    _show_locator_types: list[str]
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    @validate_call
    def load(
        cls,
        name: str,
        group_desc: FindingGroupModel,
        findings_dir: DirectoryPath,
        target_locators: list[LocatorModel],
        templates: DirectoryPath,
    ) -> Self:
        """Load a finding group.

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
            _show_locator_types=group_desc.show_locator_types,
            extras=group_desc.model_extra or {},
        )

    def dumps_toml(self) -> str:
        """Dump the finding group to a TOML string."""
        doc = tomlkit.document()
        table = tomlkit.table()

        if self.explicit_risk is not None:
            table.add("risk", self.explicit_risk.value)

        # show_locator_types (force inline)
        slt_array = tomlkit.array()
        slt_array.extend(self._show_locator_types)
        table.add("show_locator_types", slt_array.multiline(False))

        # findings (preserve order)
        findings_array = tomlkit.array()
        if len(self.sub_findings) > 1:
            findings_array.multiline(True)
        for sf in self.sub_findings:
            findings_array.append(sf.uname)
        table.add("findings", findings_array)

        # extras
        for key, value in self.extras.items():
            table.add(key, value)

        doc.add(self.name, table)
        return tomlkit.dumps(doc).strip()

    @property
    def risk(self) -> Risk:
        """Get the finding group risk.

        Returns:
            The explicit risk if set, otherwise the highest risk from the sub-findings.
        """
        if self.explicit_risk is not None:
            return self.explicit_risk
        return max([sf.risk for sf in self.sub_findings], key=lambda r: r.to_int())

    @property
    def locators(self) -> list[LocatorModel]:
        """Return a de-duplicated list of locators for the finding group.

        Applies filtering from the `show_locator_types` attribute.

        Precedence (first non-empty wins):
        1. Explicit locators defined on the finding group
        2. If every sub-finding has at least one locator, return the unique union of all
           sub-finding locators (permitted types only)
        3. If only some sub-findings define locators, merge their locators with the target
           locators and return the unique union
        4. Locators inherited from the target
        """

        # 1. Explicit locators on the group
        finding_group_locators = _filter_locators_by_type(self._finding_group_locators, self._show_locator_types)
        if len(finding_group_locators) > 0:
            return _unique_locators(finding_group_locators)

        has_sub_findings = len(self.sub_findings) > 0
        all_sub_have_locators = has_sub_findings and all(len(sf.locators) > 0 for sf in self.sub_findings)
        any_sub_has_locators = has_sub_findings and any(len(sf.locators) > 0 for sf in self.sub_findings)

        sub_finding_locators = _filter_locators_by_type(
            (loc for sf in self.sub_findings for loc in sf.locators),
            self._show_locator_types,
        )
        filtered_target_locators = _filter_locators_by_type(self._target_locators, self._show_locator_types)

        # 2. All sub-findings define locators -> report only their union
        if all_sub_have_locators and len(sub_finding_locators) > 0:
            return _unique_locators(sub_finding_locators)

        # 3. Mixed coverage -> append target locators after sub-finding ones
        if any_sub_has_locators and len(sub_finding_locators) > 0:
            return _unique_locators(sub_finding_locators + filtered_target_locators)

        # 4. Fallback to target locators
        return _unique_locators(filtered_target_locators)

    @validate_call
    def subfinding_locators(self, sub_finding: SubFinding) -> list[LocatorModel]:
        """Return locators that add information beyond what the group already surfaces.

        Resolution order:
            1. Sub-finding locators when they introduce new locators.
            2. Explicit group locators if they differ from the effective group view.
            3. Fall back to target locators (already filtered by show_locator_types).

        Returns:
            A list of locators relevant for the given sub-finding, possibly empty.
        """
        sub_locators = _unique_locators(_filter_locators_by_type(sub_finding.locators, self._show_locator_types))
        group_locators = self.locators

        # Group exposes nothing → pass through whatever the sub-finding provides.
        if not group_locators:
            return sub_locators

        # Sub-finding adds no new locators.
        if _locators_equal(sub_locators, group_locators):
            return []

        # Sub-finding introduces additional context → return it.
        if sub_locators:
            return sub_locators

        # Sub-finding empty: check if explicit group locators differ from the derived view.
        explicit_group_locators = _unique_locators(
            _filter_locators_by_type(self._finding_group_locators, self._show_locator_types)
        )
        if _locators_equal(explicit_group_locators, group_locators):
            return []

        if explicit_group_locators:
            return explicit_group_locators

        # Nothing explicit either → fall back to filtered target locators.
        return _filter_locators_by_type(self._target_locators, self._show_locator_types)

    @property
    def reported_on(self) -> SeretoDate | None:
        """Get the reported_on date from sub-findings, if available.

        Returns:
            The reported_on date if any sub-finding has it set, otherwise None.
        """
        reported_dates = [sf.reported_on for sf in self.sub_findings if sf.reported_on is not None]
        return min(reported_dates) if len(reported_dates) > 0 else None

    @validate_call
    def filter_locators(self, type: str | Iterable[str]) -> list[LocatorModel]:
        """Filter locators by type.

        Args:
            type: The type of locators to filter by. Can be a single type or an iterable of types.

        Returns:
            A list of locators of the specified type.
        """
        type = [type] if isinstance(type, str) else list(type)
        return [loc for loc in self.locators if loc.type in type]

    @property
    @validate_call
    def uname(self) -> str:
        """Unique name of the finding group."""
        return lower_alphanum(f"finding_group_{self.name}")


@dataclass
class Findings:
    """Represents a collection of all finding groups inside a target.

    Attributes:
        groups: A list of finding groups.
        target_dir: The path to the target directory containing the findings.
        target_locators: A list of locators used to find the target.
    """

    groups: list[FindingGroup]
    target_dir: FilePath
    target_locators: list[LocatorModel]

    @classmethod
    @validate_call
    def load_from(
        cls, target_dir: DirectoryPath, target_locators: list[LocatorModel], templates: DirectoryPath
    ) -> Self:
        """Load findings belonging to the same target.

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

    def get_path(self, category: str, name: str) -> FilePath:
        """Get the path to a sub-finding by category and name.

        Args:
            category: The category of the sub-finding.
            name: The name of the sub-finding.

        Returns:
            The path to the sub-finding file.
        """
        return self.findings_dir / f"{category.lower()}_{name}.md.j2"

    @validate_call
    def add_from_template(
        self,
        templates: DirectoryPath,
        template_path: FilePath,
        category: str,
        name: str | None = None,
        risk: Risk | None = None,
        variables: dict[str, Any] | None = None,
        overwrite: bool = False,
        group_uname: str | None = None,
    ) -> None:
        """Add a sub-finding from a template, creating a new finding group.

        Args:
            templates: Path to the templates directory.
            template_path: Path to the sub-finding template.
            category: Category of the sub-finding.
            name: Name of the sub-finding group. Defaults to template name.
            risk: Risk of the sub-finding. Defaults to template risk.
            variables: Variables for the sub-finding template.
            overwrite: If True, overwrite existing sub-finding; otherwise, create with random suffix.
        """
        variables = variables or {}

        # Load template metadata and content
        template_metadata = FindingTemplateFrontmatterModel.load_from(template_path)
        template_name = template_path.name.removesuffix(".md.j2")
        _, content = frontmatter.parse(template_path.read_text(encoding="utf-8"), encoding="utf-8")

        # Determine sub-finding path
        sub_finding_path = self.get_path(category=category, name=template_name)
        suffix = None

        if sub_finding_path.is_file():
            if overwrite:
                sub_finding_path.unlink()
            else:
                # Try to generate a unique filename with random suffix
                for _ in range(5):
                    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
                    sub_finding_path = self.get_path(category=category, name=f"{template_name}_{suffix}")
                    if not sub_finding_path.is_file():
                        break
                else:
                    raise SeretoPathError(
                        f"sub-finding already exists and could not generate a unique filename: {sub_finding_path}"
                    )

        # Prepare sub-finding frontmatter
        dynamic_risk = risk or template_metadata.risk
        sub_finding_metadata = SubFindingFrontmatterModel(
            name=template_metadata.name,
            risk=dynamic_risk,
            category=category,
            variables=variables,
            template_path=str(template_path.relative_to(templates)),
        )

        # Write sub-finding file
        sub_finding_path.write_text(f"+++\n{sub_finding_metadata.dumps_toml()}+++\n\n{content}", encoding="utf-8")

        # If overwriting, nothing else to do
        if overwrite:
            return

        # Load the created sub-finding
        sub_finding = SubFinding.load_from(path=sub_finding_path, templates=templates)

        if group_uname is not None:
            group = self.select_group(group_uname)

            doc = tomlkit.parse(self.config_file.read_text(encoding="utf-8"))
            if group.name not in doc:
                raise SeretoValueError(f"finding group {group.name!r} not found in {self.config_file}")

            table = cast(Table, doc[group.name])

            if "findings" in table:
                arr = table.get("findings", tomlkit.array())
                current = [str(x) for x in arr]
                if sub_finding.uname not in current:
                    arr.append(sub_finding.uname)
            else:
                arr = tomlkit.array()
                arr.append(sub_finding.uname)
                table.add("findings", arr)

            self.config_file.write_text(tomlkit.dumps(doc), encoding="utf-8")

            group.sub_findings.append(sub_finding)
            return

        # Determine group name
        group_name = name or sub_finding.name
        if suffix:
            group_name = f"{group_name} {suffix}"

        # Create finding group
        group = FindingGroup(
            name=group_name,
            explicit_risk=risk,
            sub_findings=[sub_finding],
            _target_locators=self.target_locators,
            _finding_group_locators=[],
            _show_locator_types=get_locator_types(),
        )

        # Append to findings.toml
        with self.config_file.open("a", encoding="utf-8") as f:
            f.write(f"\n{group.dumps_toml()}\n")

        # Add to loaded groups
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

    @validate_call
    def update_group_extras(self, selector: int | str, extras: dict[str, Any]) -> None:
        """Update the extras of a finding group and persist to findings.toml.

        This method updates plugin-specific extra fields on a finding group and writes the changes back to the
        findings.toml file while preserving formatting.

        Args:
            selector: The index (1-based) or uname of the finding group to update.
            extras: A dictionary of extra fields to set on the finding group.
                    These will be merged with existing extras (new values override).

        Raises:
            SeretoValueError: If the finding group cannot be found.
        """
        group = self.select_group(selector)

        # Update in-memory extras
        group.extras.update(extras)

        # Read and parse the existing TOML file preserving formatting
        content = self.config_file.read_text(encoding="utf-8")
        doc = tomlkit.parse(content)

        # Update the extras in the TOML document
        if group.name not in doc:
            raise SeretoValueError(f"finding group '{group.name}' not found in findings.toml")

        for key, value in extras.items():
            doc[group.name][key] = value  # type: ignore[index]

        # Write back to file
        self.config_file.write_text(tomlkit.dumps(doc), encoding="utf-8")

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
