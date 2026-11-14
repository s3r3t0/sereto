from __future__ import annotations

import copy
import json
import shutil
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import StrEnum
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Literal, cast

import tomlkit
from loguru import logger

from sereto.models.config import ConfigModel
from sereto.models.finding import FindingsConfigModel


# Unique identity keys
@dataclass(frozen=True, order=True)
class TargetKey:
    version: str
    category: str
    name: str


@dataclass(frozen=True, order=True)
class GroupKey:
    target: TargetKey
    name: str


@dataclass(frozen=True, order=True)
class FindingKey:
    target: TargetKey
    name: str


@dataclass(frozen=True, order=True)
class DateKey:
    version: str
    type: str


@dataclass(frozen=True, order=True)
class PersonKey:
    version: str
    type: str
    email: str


@dataclass(frozen=True)
class FileKey:
    path: Path
    target: TargetKey | None = None

    def __post_init__(self) -> None:
        if self.path.is_absolute() or ".." in self.path.parts or not self.path.parts:
            raise ValueError(f"Invalid project file path: {self.path}")


type MergeKey = DateKey | PersonKey | TargetKey | GroupKey | FindingKey | FileKey
type MergeValue = dict[str, Any] | bytes


class MergeSource(StrEnum):
    LOCAL = "local"
    UNPACKED = "unpacked"
    BOTH = "both"


class MergeStatus(StrEnum):
    # Records present in only one project (`MergeSource.LOCAL` or `MergeSource.UNPACKED`)
    INCLUDED = "included"
    EXCLUDED = "excluded"
    # Records present in both projects (`MergeSource.BOTH`)
    IDENTICAL = "identical"
    CONFLICT = "conflict"
    RESOLVED = "resolved"  # Once conflict is resolved by the user


@dataclass(frozen=True)
class MergeRecord[Value: MergeValue]:
    """Record present in the local and/or unpacked project; the type of `key` determines the kind of the record."""

    key: MergeKey
    local: Value | None
    unpacked: Value | None
    # Directory of the target relative to the project root (only relevant for targets)
    path: Path | None = None
    # Group membership (only relevant for findings)
    local_group: GroupKey | None = None
    unpacked_group: GroupKey | None = None

    def __post_init__(self) -> None:
        if self.local is None and self.unpacked is None:
            raise ValueError(f"record {self.key!r} is absent from both projects")
        if isinstance(self.key, TargetKey) != (self.path is not None):
            raise ValueError(f"only target records must have a path: {self.key!r}")
        for value in (self.local, self.unpacked):
            if value is not None:
                self.validate_value(value)
        for value, group in ((self.local, self.local_group), (self.unpacked, self.unpacked_group)):
            if isinstance(self.key, FindingKey):
                if (value is not None) != (group is not None):
                    raise ValueError(f"Every finding must have a group: {self.key!r}")
                if group is not None and group.target != self.key.target:
                    raise ValueError(f"Finding group belongs to another target: {self.key!r}")
            elif group is not None:
                raise ValueError(f"Only findings can have a group: {self.key!r}")

    def validate_value(self, value: MergeValue) -> Value:
        """Check the payload against the entity identity before accepting it."""
        if not isinstance(value, bytes if isinstance(self.key, (FindingKey, FileKey)) else dict):
            raise TypeError(f"Invalid value for {self.key!r}")
        if isinstance(self.key, GroupKey) and isinstance(value, dict) and "findings" in value:
            raise ValueError("Group membership must be resolved on each finding, not in group metadata")
        return cast(Value, value)

    @property
    def parent_key(self) -> TargetKey | None:
        """Key of the record this record depends on, if any (excluding the parent excludes this record too)."""
        return self.key.target if isinstance(self.key, (GroupKey, FindingKey, FileKey)) else None

    @property
    def target_dir(self) -> Path:
        """Directory of the target relative to the project root.

        Raises:
            ValueError: If the record is not a target, or the target has no path set.
        """
        if not isinstance(self.key, TargetKey):
            raise ValueError(f"target_dir is only available for target records: {self.key!r}")
        if self.path is None:
            raise ValueError(f"target record {self.key!r} has no path set")
        return self.path

    @property
    def source(self) -> MergeSource:
        if self.local is not None and self.unpacked is not None:
            return MergeSource.BOTH
        return MergeSource.LOCAL if self.local is not None else MergeSource.UNPACKED

    @property
    def in_local(self) -> bool:
        return self.local is not None

    @property
    def in_unpacked(self) -> bool:
        return self.unpacked is not None

    @property
    def is_identical(self) -> bool:
        return (
            self.in_local
            and self.in_unpacked
            and self.local == self.unpacked
            and self.local_group == self.unpacked_group
        )

    @property
    def available_statuses(self) -> tuple[MergeStatus, ...]:
        if self.source is not MergeSource.BOTH:
            return (MergeStatus.INCLUDED, MergeStatus.EXCLUDED)
        if self.is_identical:
            return (MergeStatus.IDENTICAL,)
        return (MergeStatus.CONFLICT, MergeStatus.RESOLVED)

    @property
    def default_status(self) -> MergeStatus:
        if self.source is not MergeSource.BOTH:
            return MergeStatus.INCLUDED
        return MergeStatus.IDENTICAL if self.is_identical else MergeStatus.CONFLICT

    def value_for_status(self, status: MergeStatus, resolved: MergeValue | None = None) -> Value:
        """Return the value that ends up in the merged project for the given status.

        Args:
            status: Status of the record.
            resolved: Value explicitly chosen by the user for the `RESOLVED` status.

        Raises:
            ValueError: If the status is unavailable for the record or has no value.
        """
        value: Value | None = None
        if status in self.available_statuses:
            match status:
                case MergeStatus.INCLUDED:
                    value = self.local if self.local is not None else self.unpacked
                case MergeStatus.IDENTICAL:
                    value = self.local
                case MergeStatus.RESOLVED:
                    value = self.validate_value(resolved) if resolved is not None else None
                case _:
                    pass
        if value is None:
            raise ValueError(f"status {status.value!r} is unavailable for {self.key!r}")
        return copy.deepcopy(value)


@dataclass
class MergeSelection:
    """User choices, kept separate from immutable comparison records."""

    statuses: dict[MergeKey, MergeStatus] = field(default_factory=dict)
    resolved_values: dict[MergeKey, MergeValue] = field(default_factory=dict)
    finding_groups: dict[FindingKey, GroupKey] = field(default_factory=dict)

    def finding_group(self, record: MergeRecord[MergeValue]) -> GroupKey | None:
        if not isinstance(record.key, FindingKey):
            return None
        if self.status(record) is MergeStatus.RESOLVED:
            return self.finding_groups.get(record.key)
        if record.local_group is None or record.unpacked_group is None or record.local_group == record.unpacked_group:
            return record.local_group or record.unpacked_group
        return None

    def status(self, record: MergeRecord[MergeValue]) -> MergeStatus:
        if record.key in self.statuses:
            return self.statuses[record.key]
        if record.key in self.resolved_values and MergeStatus.RESOLVED in record.available_statuses:
            return MergeStatus.RESOLVED
        return record.default_status

    def parent_excluded(self, record: MergeRecord[MergeValue]) -> bool:
        parent = record.parent_key
        group = self.finding_group(record)
        return (parent is not None and self.statuses.get(parent) is MergeStatus.EXCLUDED) or (
            group is not None and self.statuses.get(group) is MergeStatus.EXCLUDED
        )

    def effective_status(self, record: MergeRecord[MergeValue]) -> MergeStatus:
        return MergeStatus.EXCLUDED if self.parent_excluded(record) else self.status(record)

    def set_status(self, record: MergeRecord[MergeValue], status: MergeStatus) -> None:
        if status not in record.available_statuses:
            raise ValueError(f"status {status.value!r} is unavailable for {record.key!r}")
        if status is MergeStatus.RESOLVED:
            # Validate the resolved value for the record before setting the status
            record.value_for_status(status, self.resolved_values.get(record.key))
        self.statuses[record.key] = status

    def resolve(self, record: MergeRecord[MergeValue], value: MergeValue, *, group: GroupKey | None = None) -> None:
        resolved = record.value_for_status(MergeStatus.RESOLVED, value)
        if isinstance(record.key, FindingKey):
            if group is None and record.local_group == record.unpacked_group:
                group = record.local_group
            if group is None or group not in (record.local_group, record.unpacked_group):
                raise ValueError(f"Choose a local or unpacked group for {record.key!r}")
            self.finding_groups[record.key] = group
        elif group is not None:
            raise ValueError("Only findings can be assigned to groups")
        self.resolved_values[record.key] = resolved
        self.statuses[record.key] = MergeStatus.RESOLVED

    def resolve_all_as(self, records: Sequence[MergeRecord[MergeValue]], source: Literal["local", "unpacked"]) -> None:
        for record in records:
            value = record.local if source == "local" else record.unpacked
            if record.source is MergeSource.BOTH:
                if value is not None and not record.is_identical:
                    # Settle the conflict in favour of the chosen source
                    group = record.local_group if source == "local" else record.unpacked_group
                    self.resolve(record, value, group=group)
            else:
                self.set_status(record, MergeStatus.INCLUDED if value is not None else MergeStatus.EXCLUDED)

    def has_conflicts(self, records: Sequence[MergeRecord[MergeValue]]) -> bool:
        return any(self.effective_status(record) is MergeStatus.CONFLICT for record in records)

    def resolve_selected_values(self, records: Sequence[MergeRecord[MergeValue]]) -> dict[MergeKey, MergeValue]:
        """Validate all choices and resolve included records before any writes."""
        keys = {record.key for record in records}
        if len(keys) != len(records):
            raise ValueError("Duplicate merge record keys")
        selected: dict[MergeKey, MergeValue] = {}
        for record in records:
            if record.parent_key is not None and record.parent_key not in keys:
                raise ValueError(f"Missing parent for {record.key!r}")
            status = self.status(record)
            if status not in record.available_statuses:
                raise ValueError(f"status {status.value!r} is unavailable for {record.key!r}")
            if record.key in self.resolved_values:
                record.validate_value(self.resolved_values[record.key])
            if isinstance(record.key, FindingKey):
                possible_groups = {record.local_group, record.unpacked_group} - {None}
                if not possible_groups <= keys:
                    raise ValueError(f"Missing group record for {record.key!r}")
            if self.effective_status(record) is not MergeStatus.EXCLUDED:
                selected[record.key] = record.value_for_status(status, self.resolved_values.get(record.key))
                if isinstance(record.key, FindingKey):
                    group = self.finding_group(record)
                    if group is None or group not in (record.local_group, record.unpacked_group):
                        raise ValueError(f"Choose a local or unpacked group for {record.key!r}")
        return selected


LOCAL_MARKER = "<<<<<<< local"
SEPARATOR_MARKER = "======="
UNPACKED_MARKER = ">>>>>>> unpacked"


def render_conflict_markers(local: str, unpacked: str) -> str:
    """Render both versions of a text in a single document, marking differing sections as git does.

    Lines common to both versions are kept as they are, every differing section is wrapped in
    `<<<<<<< local`, `=======` and `>>>>>>> unpacked` lines. Nothing is merged automatically.
    """
    local_lines = local.splitlines(keepends=True)
    unpacked_lines = unpacked.splitlines(keepends=True)

    def terminated(lines: list[str]) -> str:
        text = "".join(lines)
        return text if not text or text.endswith("\n") else text + "\n"

    parts: list[str] = []
    matcher = SequenceMatcher(a=local_lines, b=unpacked_lines, autojunk=False)
    for tag, local_start, local_end, unpacked_start, unpacked_end in matcher.get_opcodes():
        if tag == "equal":
            parts.append("".join(local_lines[local_start:local_end]))
            continue
        parts.append(f"{LOCAL_MARKER}\n")
        parts.append(terminated(local_lines[local_start:local_end]))
        parts.append(f"{SEPARATOR_MARKER}\n")
        parts.append(terminated(unpacked_lines[unpacked_start:unpacked_end]))
        parts.append(f"{UNPACKED_MARKER}\n")
    return "".join(parts)


def has_conflict_markers(text: str) -> bool:
    """Check whether the text still contains the opening or closing conflict marker line."""
    return any(line.rstrip("\r\n") in (LOCAL_MARKER, UNPACKED_MARKER) for line in text.splitlines(keepends=True))


def _load_config(project_dir: Path) -> ConfigModel:
    return ConfigModel.load_from(project_dir / "config.json")


def _load_config_data(project_dir: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((project_dir / "config.json").read_text(encoding="utf-8")))


def _target_records(config: ConfigModel) -> dict[TargetKey, tuple[dict[str, Any], Path]]:
    records: dict[TargetKey, tuple[dict[str, Any], Path]] = {}
    for version, version_config in config.version_configs.items():
        version_string = str(version)
        for target in version_config.targets:
            target_data = target.model_dump(mode="json", exclude_unset=True)
            records[TargetKey(version_string, target.category, target.name)] = (
                target_data,
                Path(target.uname + version.path_suffix),
            )
    return records


def _date_records(config: ConfigModel) -> dict[DateKey, dict[str, Any]]:
    records: dict[DateKey, dict[str, Any]] = {}
    for version, version_config in config.version_configs.items():
        for date in version_config.dates:
            records[DateKey(str(version), date.type.value)] = date.model_dump(mode="json", exclude_unset=True)
    return records


def _person_records(config: ConfigModel, source: MergeSource) -> dict[PersonKey, dict[str, Any]]:
    records: dict[PersonKey, dict[str, Any]] = {}
    for version, version_config in config.version_configs.items():
        for index, person in enumerate(version_config.people):
            # Without an email identity, keep each side's person as a separate record.
            identity = str(person.email).casefold() if person.email is not None else f"{source.value}:{index}"
            key = PersonKey(version=str(version), type=person.type.value, email=identity)
            if key in records:
                raise ValueError(
                    f"Duplicate person key in {source.value} project: "
                    f"version={key.version!r}, type={key.type!r}, email={key.email!r}. "
                    "Each person type and email must be unique within a project version; "
                    "resolve the duplicate entries before merging."
                )
            records[key] = person.model_dump(mode="json", exclude_unset=True)
    return records


def _load_findings(target_dir: Path) -> dict[str, Any]:
    path = target_dir / "findings.toml"
    if not path.is_file():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    try:
        FindingsConfigModel.model_validate(data)
    except ValueError as exc:
        raise ValueError(f"Invalid findings configuration in {path}: {exc}") from exc
    return data


def discover_merge_targets(local_dir: Path, unpacked_dir: Path) -> list[MergeRecord[dict[str, Any]]]:
    local = _target_records(_load_config(local_dir))
    unpacked = _target_records(_load_config(unpacked_dir))
    targets: list[MergeRecord[dict[str, Any]]] = []
    for key in sorted(local.keys() | unpacked.keys()):
        _, path = local.get(key) or unpacked[key]
        local_value = local.get(key, (None, path))[0]
        unpacked_value = unpacked.get(key, (None, path))[0]
        targets.append(
            MergeRecord(
                key=key,
                local=copy.deepcopy(local_value),
                unpacked=copy.deepcopy(unpacked_value),
                path=path,
            )
        )
    return targets


def discover_merge_dates(local_dir: Path, unpacked_dir: Path) -> list[MergeRecord[dict[str, Any]]]:
    local = _date_records(_load_config(local_dir))
    unpacked = _date_records(_load_config(unpacked_dir))
    dates: list[MergeRecord[dict[str, Any]]] = []
    for key in sorted(local.keys() | unpacked.keys()):
        local_value = local.get(key)
        unpacked_value = unpacked.get(key)
        dates.append(
            MergeRecord(
                key=key,
                local=copy.deepcopy(local_value),
                unpacked=copy.deepcopy(unpacked_value),
            )
        )
    return dates


def discover_merge_people(local_dir: Path, unpacked_dir: Path) -> list[MergeRecord[dict[str, Any]]]:
    local = _person_records(_load_config(local_dir), MergeSource.LOCAL)
    unpacked = _person_records(_load_config(unpacked_dir), MergeSource.UNPACKED)
    people: list[MergeRecord[dict[str, Any]]] = []
    for key in sorted(local.keys() | unpacked.keys()):
        local_value = local.get(key)
        unpacked_value = unpacked.get(key)
        people.append(
            MergeRecord(
                key=key,
                local=copy.deepcopy(local_value),
                unpacked=copy.deepcopy(unpacked_value),
            )
        )
    return people


def discover_merge_findings(
    local_dir: Path,
    unpacked_dir: Path,
    targets: Sequence[MergeRecord[MergeValue]],
    selected_targets: set[MergeKey],
) -> list[MergeRecord[bytes]]:
    findings: list[MergeRecord[bytes]] = []
    for target in targets:
        if not isinstance(target.key, TargetKey):
            raise ValueError(f"Expected target record, got {target.key!r}")
        if target.key not in selected_targets:
            continue
        local_groups = _finding_memberships(_load_findings(local_dir / target.target_dir)) if target.in_local else {}
        unpacked_groups = (
            _finding_memberships(_load_findings(unpacked_dir / target.target_dir)) if target.in_unpacked else {}
        )
        local_names = set(local_groups)
        unpacked_names = set(unpacked_groups)
        for name in sorted(local_names | unpacked_names):
            local_path = local_dir / target.target_dir / "findings" / f"{name}.md.j2"
            unpacked_path = unpacked_dir / target.target_dir / "findings" / f"{name}.md.j2"
            local_value = (local_path.read_bytes() if local_path.is_file() else b"") if name in local_names else None
            unpacked_value = (
                (unpacked_path.read_bytes() if unpacked_path.is_file() else b"") if name in unpacked_names else None
            )
            for path, value in ((local_path, local_value), (unpacked_path, unpacked_value)):
                if value is not None:
                    try:
                        value.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise ValueError(
                            f"Finding file is not valid UTF-8: {path}. Save it as UTF-8 before merging."
                        ) from exc
            for path, names, other_value in (
                (local_path, local_names, unpacked_value),
                (unpacked_path, unpacked_names, local_value),
            ):
                if name not in names and path.is_file() and path.read_bytes() != other_value:
                    raise ValueError(
                        f"Unreferenced finding file conflicts with the other project: {path}. "
                        "Assign it to a group or rename it before merging."
                    )
            findings.append(
                MergeRecord(
                    FindingKey(target.key, name),
                    local_value,
                    unpacked_value,
                    local_group=GroupKey(target.key, local_groups[name]) if name in local_groups else None,
                    unpacked_group=GroupKey(target.key, unpacked_groups[name]) if name in unpacked_groups else None,
                )
            )
    return findings


def _finding_memberships(config: dict[str, Any]) -> dict[str, str]:
    return {name: group_name for group_name, group in config.items() for name in group["findings"]}


def discover_merge_groups(
    local_dir: Path, unpacked_dir: Path, targets: Sequence[MergeRecord[MergeValue]]
) -> list[MergeRecord[dict[str, Any]]]:
    records: list[MergeRecord[dict[str, Any]]] = []
    for target in targets:
        if not isinstance(target.key, TargetKey):
            raise ValueError(f"Expected target record, got {target.key!r}")
        local = _load_findings(local_dir / target.target_dir) if target.in_local else {}
        unpacked = _load_findings(unpacked_dir / target.target_dir) if target.in_unpacked else {}
        for name in sorted(local.keys() | unpacked.keys()):
            # Gather group's metadata, excluding the "findings" key (memberships are handled separately)
            records.append(
                MergeRecord(
                    GroupKey(target.key, name),
                    {key: value for key, value in local[name].items() if key != "findings"} if name in local else None,
                    {key: value for key, value in unpacked[name].items() if key != "findings"}
                    if name in unpacked
                    else None,
                )
            )
    return records


def discover_merge_files(
    local_dir: Path,
    unpacked_dir: Path,
    targets: Sequence[MergeRecord[MergeValue]],
    findings: Sequence[MergeRecord[MergeValue]],
) -> list[MergeRecord[bytes]]:
    files: dict[FileKey, list[bytes | None]] = {}
    scopes: list[tuple[Path, TargetKey | None]] = [(Path(name), None) for name in ("pictures", "layouts", "includes")]
    scopes.extend((target.target_dir, target.key) for target in targets if isinstance(target.key, TargetKey))
    # Skip finding Markdown files and target configuration files; they are handled separately
    managed = {
        target.target_dir / "findings" / f"{finding.key.name}.md.j2"
        for target in targets
        for finding in findings
        if isinstance(finding.key, FindingKey) and finding.parent_key == target.key
    }
    managed.update(target.target_dir / "findings.toml" for target in targets)

    for index, project_dir in enumerate((local_dir, unpacked_dir)):
        for relative_dir, parent in scopes:
            directory = project_dir / relative_dir
            if not directory.exists():
                continue
            if not directory.is_dir() or directory.is_symlink():
                raise ValueError(f"Expected a project directory: {directory}")
            for path in sorted(directory.rglob("*")):
                if path.is_symlink():
                    raise ValueError(f"Cannot merge symbolic link: {path}")
                relative_path = path.relative_to(project_dir)
                if path.is_file() and relative_path not in managed:
                    files.setdefault(FileKey(relative_path, parent), [None, None])[index] = path.read_bytes()
    return [
        MergeRecord(key, values[0], values[1])
        for key, values in sorted(files.items(), key=lambda item: item[0].path.as_posix())
    ]


def config_from_selected(
    local_config: dict[str, Any],
    unpacked_config: dict[str, Any],
    local_model: ConfigModel,
    unpacked_model: ConfigModel,
    record_keys: set[MergeKey],
    selected: Mapping[MergeKey, MergeValue],
) -> dict[str, Any]:
    result = copy.deepcopy(local_config)
    result_versions = cast(dict[str, Any], result.setdefault("version_configs", {}))
    local_versions = cast(dict[str, Any], local_config.get("version_configs", {}))
    unpacked_versions = cast(dict[str, Any], unpacked_config.get("version_configs", {}))
    local_targets = _target_records(local_model)
    unpacked_targets = _target_records(unpacked_model)
    local_dates = _date_records(local_model)
    unpacked_dates = _date_records(unpacked_model)
    local_people = _person_records(local_model, MergeSource.LOCAL)
    unpacked_people = _person_records(unpacked_model, MergeSource.UNPACKED)

    for version_key in [*local_versions, *(item for item in unpacked_versions if item not in local_versions)]:
        if version_key not in result_versions:
            result_versions[version_key] = copy.deepcopy(unpacked_versions[version_key])
        version_data = cast(dict[str, Any], result_versions[version_key])
        # Clear existing data for this version to prepare for replacing them with the values selected by the user
        version_data["targets"] = []
        version_data["dates"] = []
        version_data["people"] = []

    for field_name, local_keys, unpacked_keys in (
        ("targets", list(local_targets), list(unpacked_targets)),
        ("dates", list(local_dates), list(unpacked_dates)),
        ("people", list(local_people), list(unpacked_people)),
    ):
        ordered_keys = [*local_keys, *(key for key in unpacked_keys if key not in local_keys)]
        # Iterate over all data from unpacked missing in local and apply the selected values
        for key in ordered_keys:
            if key not in record_keys:
                raise ValueError(f"Missing merge record for {key!r}")
            if key in selected:
                version_data = cast(dict[str, Any], result_versions[key.version])
                cast(list[Any], version_data[field_name]).append(selected[key])

    return result


@dataclass(frozen=True)
class _MergeOutput:
    config: bytes
    files: dict[Path, bytes]


def _prepare_merge(
    local_dir: Path,
    unpacked_dir: Path,
    records: Sequence[MergeRecord[MergeValue]],
    selected: Mapping[MergeKey, MergeValue],
    selection: MergeSelection,
) -> _MergeOutput:
    local_model = _load_config(local_dir)
    unpacked_model = _load_config(unpacked_dir)
    local_config = _load_config_data(local_dir)
    unpacked_config = _load_config_data(unpacked_dir)
    selected_config = config_from_selected(
        local_config,
        unpacked_config,
        local_model,
        unpacked_model,
        {record.key for record in records},
        selected,
    )
    ConfigModel.model_validate_json(json.dumps(selected_config))

    findings_by_target: dict[TargetKey, list[FindingKey]] = {}
    for record in records:
        if isinstance(record.key, FindingKey):
            findings_by_target.setdefault(record.key.target, []).append(record.key)

    files: dict[Path, bytes] = {}
    for key, content in selected.items():
        if isinstance(key, FileKey):
            if not isinstance(content, bytes):
                raise TypeError(f"Invalid project file content for {key!r}")
            files[key.path] = content
    for target in records:
        if not isinstance(target.key, TargetKey) or target.key not in selected:
            continue
        all_target_findings = findings_by_target.get(target.key, [])
        target_findings = [key for key in all_target_findings if key in selected]
        memberships: dict[str, GroupKey] = {}
        for record in records:
            if not isinstance(record.key, FindingKey) or record.key not in target_findings:
                continue
            group_key = selection.finding_group(record)
            metadata = selected.get(group_key) if group_key is not None else None
            if group_key is None or not isinstance(metadata, dict):
                raise ValueError(f"Missing selected group for {record.key!r}")
            memberships[record.key.name] = group_key
        local_groups = _load_findings(local_dir / target.target_dir) if target.in_local else {}
        unpacked_groups = _load_findings(unpacked_dir / target.target_dir) if target.in_unpacked else {}
        findings_config: dict[str, Any] = {}
        for name in [*local_groups, *(name for name in unpacked_groups if name not in local_groups)]:
            group_key = GroupKey(target.key, name)
            metadata = selected.get(group_key)
            if not isinstance(metadata, dict):
                continue
            names = [
                *local_groups.get(name, {}).get("findings", []),
                *unpacked_groups.get(name, {}).get("findings", []),
            ]
            chosen = [name for name in dict.fromkeys(names) if memberships.get(name) == group_key]
            if chosen:
                findings_config[name] = {**copy.deepcopy(metadata), "findings": chosen}
        FindingsConfigModel.model_validate(findings_config)
        files[target.target_dir / "findings.toml"] = tomlkit.dumps(findings_config).encode("utf-8")
        for key in target_findings:
            content = selected[key]
            if not isinstance(content, bytes):
                raise TypeError(f"Invalid finding content for {key!r}")
            files[target.target_dir / "findings" / f"{key.name}.md.j2"] = content

    return _MergeOutput((json.dumps(selected_config, indent=2) + "\n").encode("utf-8"), files)


def _write_merge(local_dir: Path, output: _MergeOutput) -> None:
    for relative_path, content in output.files.items():
        destination = local_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    (local_dir / "config.json").write_bytes(output.config)


def _backup_merge(local_dir: Path, output: _MergeOutput) -> Path:
    """Preserve overwritten files and recovery instructions before any project writes."""
    local_dir = local_dir.resolve()
    try:
        backup_dir = Path(mkdtemp(prefix=f".{local_dir.name}-merge-backup-", dir=local_dir.parent))
        files_dir = backup_dir / "files"
        files_dir.mkdir()
        new_files: list[str] = []
        # Iterate over and copy all files that will be written by the merge
        for relative_path in dict.fromkeys([*output.files, Path("config.json")]):
            source = local_dir / relative_path
            if source.exists():
                destination = files_dir / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            else:
                new_files.append(relative_path.as_posix())
        (backup_dir / "RESTORE.txt").write_text(
            f"Restore the project at {local_dir}\n\n"
            "The merge is not transactional. To return to the state before this merge:\n"
            "1. Stop editing the project and cancel the merge UI.\n"
            "2. Remove the following files from the project if they exist "
            "(paths relative to the project root, quoted as JSON):\n"
            + "".join(f"   {json.dumps(path)}\n" for path in new_files)
            + ("   (none)\n" if not new_files else "")
            + "3. Copy the contents of this backup's files directory into the project root, "
            "preserving relative paths and overwriting existing files. Do not replace entire directories, "
            "as the backup only contains files that the merge could overwrite.\n"
            "4. Empty directories created by the merge can optionally be removed.\n\n"
            "This backup is retained even after a successful merge. Restoring it discards later edits "
            "to the affected files, so preserve any edits you want to keep first.\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise OSError(f"Could not back up merge files; the project has not been modified: {exc}") from exc
    logger.info("Merge backup saved to {}", backup_dir)
    return backup_dir


def apply_entity_merge(
    local_dir: Path,
    unpacked_dir: Path,
    records: Sequence[MergeRecord[MergeValue]],
    selection: MergeSelection,
) -> None:
    targets = [record for record in records if isinstance(record.key, TargetKey)]
    findings = [record for record in records if isinstance(record.key, FindingKey)]
    expected_groups = discover_merge_groups(local_dir, unpacked_dir, targets)
    compared_groups = [record for record in records if isinstance(record.key, GroupKey)]
    expected_findings = discover_merge_findings(local_dir, unpacked_dir, targets, {target.key for target in targets})

    if {record.key: record for record in expected_groups} != {record.key: record for record in compared_groups} or {
        record.key: record for record in expected_findings
    } != {record.key: record for record in findings}:
        raise ValueError("Finding groups or findings changed or were not compared. Reopen the merge before applying.")

    expected_files = discover_merge_files(local_dir, unpacked_dir, targets, findings)
    compared_files = [record for record in records if isinstance(record.key, FileKey)]
    if {record.key: record for record in expected_files} != {record.key: record for record in compared_files}:
        raise ValueError("Project files changed or were not compared. Reopen the merge before applying.")

    selected = selection.resolve_selected_values(records)
    output = _prepare_merge(local_dir, unpacked_dir, records, selected, selection)
    # Validate that all files to be written are within the project and have valid destinations before proceeding
    for relative_path in output.files:
        destination = local_dir / relative_path
        if not destination.resolve().is_relative_to(local_dir.resolve()):
            raise ValueError(f"File points outside the project: {relative_path}")
        if destination.exists() and not destination.is_file():
            raise ValueError(f"File destination is not a regular file: {relative_path}")
        for parent in destination.parents:
            if parent == local_dir:
                break
            if parent.exists() and not parent.is_dir():
                raise ValueError(f"File parent is not a directory: {parent}")
    # Create a backup of the current project state before writing the merge output
    backup_dir = _backup_merge(local_dir, output)
    # Attempt to write the merge output to the project directory
    try:
        _write_merge(local_dir, output)
    except OSError as exc:
        raise OSError(
            f"Merge failed; the project may already be partially modified. Backup: {backup_dir}. "
            "To restore, cancel the merge and follow RESTORE.txt in the backup: remove the newly created "
            "files listed there, then copy the contents of its 'files' directory into the project root, "
            f"preserving relative paths and overwriting existing files. Original error: {exc}"
        ) from exc
