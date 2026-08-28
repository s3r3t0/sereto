import hashlib
import random
import string
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Self, cast

import frontmatter
import tomlkit
from pydantic import DirectoryPath, FilePath, validate_call
from tomlkit.items import Table

from sereto.enums import FileFormat, Risk
from sereto.exceptions import SeretoPathError, SeretoRuntimeError, SeretoValueError
from sereto.file_transaction import AtomicFileTransaction, PendingFileWrite, file_digest
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


def _validate_template_variables(
    template: FindingTemplateFrontmatterModel,
    variables: dict[str, Any],
) -> None:
    definitions = {variable.name: variable for variable in template.variables}
    errors: list[str] = []

    for name in sorted(variables.keys() - definitions.keys()):
        errors.append(f"unknown variable {name!r}")

    expected_types: dict[str, type[str] | type[int] | type[bool]] = {
        "string": str,
        "integer": int,
        "boolean": bool,
    }
    for name, definition in definitions.items():
        if name not in variables or variables[name] is None:
            if definition.required:
                errors.append(f"missing required variable {name!r}")
            continue

        value = variables[name]
        value_is_list = isinstance(value, list)
        list_value = cast(list[Any], value) if value_is_list else None
        if definition.required and (value == "" or (list_value is not None and len(list_value) == 0)):
            errors.append(f"required variable {name!r} must not be empty")
            continue
        if definition.is_list != value_is_list:
            expected = f"list[{definition.type}]" if definition.is_list else definition.type
            errors.append(f"variable {name!r} must be {expected}")
            continue

        values = list_value if list_value is not None else [value]
        expected_type = expected_types[definition.type]
        if any(type(item) is not expected_type for item in values):
            expected = f"list[{definition.type}]" if definition.is_list else definition.type
            errors.append(f"variable {name!r} must be {expected}")

    if errors:
        raise SeretoValueError("invalid template variables\n" + "\n".join(f"  - {error}" for error in errors))


def _parse_findings_config(content: str) -> FindingsConfigModel:
    try:
        return FindingsConfigModel.model_validate(tomllib.loads(content))
    except ValueError as error:
        raise SeretoValueError("invalid findings.toml") from error


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

        template_frontmatter = FindingTemplateFrontmatterModel.load_from(self.template)
        _validate_template_variables(template_frontmatter, self.vars)


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
    sub_findings: list[SubFinding]
    _target_locators: list[LocatorModel]
    _finding_group_locators: list[LocatorModel]
    _show_locator_types: list[str]
    explicit_risk: Risk | None = None
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
    def suggested_name(self) -> str:
        """Display name for the finding group.

        When the group contains a single sub-finding whose name differs from the group
        name, returns ``"<group name>: <subfinding name>"``.  If the single sub-finding
        shares the same name as the group, or there are multiple sub-findings, the
        group name is returned as-is.
        """
        if len(self.sub_findings) == 1:
            sf_name = self.sub_findings[0].name
            if sf_name.casefold() != self.name.casefold():
                return f"{self.name}: {sf_name}"
        return self.name

    @property
    @validate_call
    def uname(self) -> str:
        """Unique name of the finding group."""
        return lower_alphanum(f"finding_group_{self.name}")

    def matches_hint(self, hint: str) -> bool:
        """Check if this group matches the given hint.

        The comparison is done by computing the unique name from the hint and comparing it to the group's unique name,
        or by comparing the group name case-insensitively.

        Args:
            hint: The group hint string to match against.

        Returns:
            True if the group matches the hint.
        """
        hint_uname = lower_alphanum(f"finding_group_{hint}")
        return self.uname == hint_uname or self.name.casefold() == hint.casefold()


@dataclass(frozen=True)
class ExistingGroupDestination:
    """Append a finding to the same existing group selected during preparation."""

    uname: str
    expected_name: str


@dataclass(frozen=True)
class NewGroupDestination:
    """Create a group, optionally merging into an exact-name group created concurrently."""

    name: str
    on_conflict: Literal["fail", "merge"] = "merge"


type FindingRegistration = ExistingGroupDestination | NewGroupDestination


@dataclass(frozen=True)
class PreparedFinding:
    """Validated finding content and its semantic registration intent."""

    target_dir: Path
    sub_finding_path: Path
    sub_finding_content: str
    sub_finding_original_digest: str | None
    registration: FindingRegistration | None
    templates_root: Path


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
        transaction = AtomicFileTransaction(project_root=Path(target_dir).resolve().parent)
        with transaction.locked():
            return cls._load_from_unlocked(
                target_dir=Path(target_dir),
                target_locators=target_locators,
                templates=Path(templates),
            )

    @classmethod
    def _load_from_unlocked(
        cls,
        target_dir: Path,
        target_locators: list[LocatorModel],
        templates: Path,
    ) -> Self:
        config = FindingsConfigModel.load_from(target_dir / "findings.toml")

        return cls._from_config_unlocked(
            config=config,
            target_dir=target_dir,
            target_locators=target_locators,
            templates=templates,
        )

    @classmethod
    def _from_config_unlocked(
        cls,
        config: FindingsConfigModel,
        target_dir: Path,
        target_locators: list[LocatorModel],
        templates: Path,
    ) -> Self:
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

    def find_group_by_hint(self, hint: str) -> FindingGroup | None:
        """Find a finding group that matches the given hint.

        Args:
            hint: The group hint string to match against.

        Returns:
            The matching finding group, or None if no match is found.
        """
        for group in self.groups:
            if group.matches_hint(hint):
                return group
        return None

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
    def prepare_from_template(
        self,
        templates: DirectoryPath,
        template_path: FilePath,
        category: str,
        sub_finding_name: str | None = None,
        risk: Risk | None = None,
        variables: dict[str, Any] | None = None,
        locators: list[LocatorModel] | None = None,
        overwrite: bool = False,
        group_uname: str | None = None,
        group_name: str | None = None,
    ) -> PreparedFinding:
        """Validate and render a finding change without writing project files."""
        if group_uname is not None and group_name is not None:
            raise SeretoValueError("group_uname and group_name are mutually exclusive")

        templates_root = Path(templates).resolve()
        resolved_template_path = Path(template_path).resolve()
        try:
            relative_template_path = resolved_template_path.relative_to(templates_root)
        except ValueError:
            raise SeretoValueError("template is outside the templates directory") from None

        variables = variables or {}
        locators = locators or []

        template_metadata = FindingTemplateFrontmatterModel.load_from(resolved_template_path)
        _validate_template_variables(template_metadata, variables)
        finding_file_name = lower_alphanum(sub_finding_name or template_metadata.name)
        _, content = frontmatter.parse(resolved_template_path.read_text(encoding="utf-8"), encoding="utf-8")

        sub_finding_path = self.get_path(category=category, name=finding_file_name)
        sub_finding_original_digest = file_digest(sub_finding_path)
        replacing_existing = sub_finding_original_digest is not None and overwrite
        if sub_finding_original_digest is not None and not overwrite:
            for _ in range(5):
                suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
                candidate = self.get_path(category=category, name=f"{finding_file_name}_{suffix}")
                candidate_digest = file_digest(candidate)
                if candidate_digest is None:
                    sub_finding_path = candidate
                    sub_finding_original_digest = candidate_digest
                    break
            else:
                raise SeretoPathError(
                    f"sub-finding already exists and could not generate a unique filename: {sub_finding_path}"
                )

        dynamic_risk = risk or template_metadata.risk
        sub_finding_metadata = SubFindingFrontmatterModel(
            name=sub_finding_name or template_metadata.name,
            risk=dynamic_risk,
            category=category,
            variables=variables,
            template_path=str(relative_template_path),
            locators=locators,
        )
        sub_finding_content = f"+++\n{sub_finding_metadata.dumps_toml()}+++\n\n{content}"

        if replacing_existing:
            registration: FindingRegistration | None = None
        elif group_uname is not None:
            group = self.select_group(group_uname)
            registration = ExistingGroupDestination(
                uname=group.uname,
                expected_name=group.name,
            )
        else:
            resolved_group_name = group_name or sub_finding_metadata.name
            existing_group = next((group for group in self.groups if group.name == resolved_group_name), None)
            if existing_group is not None:
                registration = ExistingGroupDestination(
                    uname=existing_group.uname,
                    expected_name=existing_group.name,
                )
            else:
                registration = NewGroupDestination(name=resolved_group_name)

        return PreparedFinding(
            target_dir=Path(self.target_dir).resolve(),
            sub_finding_path=sub_finding_path,
            sub_finding_content=sub_finding_content,
            sub_finding_original_digest=sub_finding_original_digest,
            registration=registration,
            templates_root=templates_root,
        )

    def commit_prepared(self, prepared: PreparedFinding) -> None:
        """Atomically persist a prepared finding and refresh loaded groups."""
        target_dir = Path(self.target_dir).resolve()
        if (
            prepared.target_dir != target_dir
            or prepared.sub_finding_path.parent.resolve() != self.findings_dir.resolve()
        ):
            raise SeretoValueError("prepared finding belongs to another target")

        def plan_writes() -> tuple[PendingFileWrite, ...]:
            writes = [
                PendingFileWrite(
                    path=prepared.sub_finding_path,
                    content=prepared.sub_finding_content.encode("utf-8"),
                    expected_digest=prepared.sub_finding_original_digest,
                )
            ]
            if prepared.registration is not None:
                writes.append(self._plan_registration(prepared))
            return tuple(writes)

        reloaded: Findings | None = None

        def validate_generated_state() -> None:
            nonlocal reloaded
            reloaded = type(self)._load_from_unlocked(
                target_dir=Path(self.target_dir),
                target_locators=self.target_locators,
                templates=prepared.templates_root,
            )

        AtomicFileTransaction(project_root=self.target_dir.parent).commit_planned(
            planner=plan_writes,
            validator=validate_generated_state,
        )
        if reloaded is None:
            raise SeretoRuntimeError("finding transaction completed without validation")
        self.groups[:] = reloaded.groups

    def _plan_registration(self, prepared: PreparedFinding) -> PendingFileWrite:
        current_config_bytes = self.config_file.read_bytes()
        current_config_digest = hashlib.sha256(current_config_bytes).hexdigest()
        try:
            current_config_content = current_config_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SeretoValueError("invalid findings.toml encoding") from error

        current_config = _parse_findings_config(current_config_content)
        current_findings = type(self)._from_config_unlocked(
            config=current_config,
            target_dir=Path(self.target_dir),
            target_locators=self.target_locators,
            templates=prepared.templates_root,
        )
        doc = tomlkit.parse(current_config_content)
        registration = prepared.registration
        if registration is None:
            raise SeretoRuntimeError("missing finding registration intent")
        finding_uname = prepared.sub_finding_path.name.removesuffix(".md.j2")
        destination_group_name = (
            registration.expected_name if isinstance(registration, ExistingGroupDestination) else registration.name
        )
        registered_group_name = next(
            (group_name for group_name, group in current_config.items() if finding_uname in group.findings),
            None,
        )
        if registered_group_name is not None and registered_group_name != destination_group_name:
            raise SeretoValueError(
                f"finding {finding_uname!r} was registered in group {registered_group_name!r} after preparation"
            )

        if isinstance(registration, ExistingGroupDestination):
            matching_groups = [group for group in current_findings.groups if group.uname == registration.uname]
            if len(matching_groups) != 1 or matching_groups[0].name != registration.expected_name:
                raise SeretoValueError(f"finding group {registration.expected_name!r} changed after preparation")
            group = matching_groups[0]
            self._append_finding_to_group(doc, group.name, finding_uname)
        else:
            exact_group = next(
                (group for group in current_findings.groups if group.name == registration.name),
                None,
            )
            if exact_group is not None:
                if registration.on_conflict == "fail":
                    raise SeretoValueError(f"finding group {registration.name!r} was created after preparation")
                self._append_finding_to_group(
                    doc,
                    exact_group.name,
                    finding_uname,
                )
            else:
                expected_uname = lower_alphanum(f"finding_group_{registration.name}")
                if any(group.uname == expected_uname for group in current_findings.groups):
                    raise SeretoValueError(
                        f"finding group name {registration.name!r} conflicts with an existing group"
                    )
                sub_finding = SubFinding(
                    name=registration.name,
                    risk=Risk.info,
                    vars={},
                    path=prepared.sub_finding_path,
                )
                group = FindingGroup(
                    name=registration.name,
                    sub_findings=[sub_finding],
                    _target_locators=self.target_locators,
                    _finding_group_locators=[],
                    _show_locator_types=get_locator_types(),
                )
                group_doc = tomlkit.parse(group.dumps_toml())
                doc.add(group.name, group_doc[group.name])

        merged_config_content = tomlkit.dumps(doc)
        _parse_findings_config(merged_config_content)
        return PendingFileWrite(
            path=self.config_file,
            content=merged_config_content.encode("utf-8"),
            expected_digest=current_config_digest,
        )

    @staticmethod
    def _append_finding_to_group(doc: tomlkit.TOMLDocument, group_name: str, finding_uname: str) -> None:
        if group_name not in doc:
            raise SeretoValueError(f"finding group {group_name!r} not found in findings.toml")
        table = cast(Table, doc[group_name])
        findings = cast(Any, table).get("findings", tomlkit.array())
        if finding_uname not in [str(item) for item in findings]:
            findings.append(finding_uname)
        if "findings" not in table:
            table.add("findings", findings)

    @validate_call
    def add_from_template(
        self,
        templates: DirectoryPath,
        template_path: FilePath,
        category: str,
        sub_finding_name: str | None = None,
        risk: Risk | None = None,
        variables: dict[str, Any] | None = None,
        overwrite: bool = False,
        group_uname: str | None = None,
        group_name: str | None = None,
    ) -> None:
        """Add a sub-finding from a template.

        When `group_uname` is provided, the sub-finding is appended to that existing finding group.
        Otherwise a new finding group is created with the name `group_name` (defaults to the
        sub-finding name from the template).

        Args:
            templates: Path to the templates directory.
            template_path: Path to the sub-finding template.
            category: Category of the sub-finding.
            sub_finding_name: Name for the sub-finding written into its TOML frontmatter. Defaults to the template
                name.
            risk: Risk of the sub-finding. Defaults to template risk.
            variables: Variables for the sub-finding template.
            overwrite: If True, overwrite existing sub-finding; otherwise, create with random suffix.
            group_uname: Unique name of an existing finding group to add the sub-finding to.
            group_name: Name for the new finding group. Only used when `group_uname` is None.
                Defaults to the sub-finding name from the template.
        """
        prepared = self.prepare_from_template(
            templates=templates,
            template_path=template_path,
            category=category,
            sub_finding_name=sub_finding_name,
            risk=risk,
            variables=variables,
            overwrite=overwrite,
            group_uname=group_uname,
            group_name=group_name,
        )
        self.commit_prepared(prepared)

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
            doc[group.name][key] = value

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
