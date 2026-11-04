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
from typing import Any, Literal, TypeGuard, cast

import tomlkit

from sereto.models.config import ConfigModel


# Unique identity keys
@dataclass(frozen=True, order=True)
class TargetKey:
    version: str
    category: str
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
    email: str


type MergeKey = DateKey | PersonKey | TargetKey | FindingKey
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
    # Directory of the target relative to the project root (only for targets)
    path: Path | None = None

    def __post_init__(self) -> None:
        if self.local is None and self.unpacked is None:
            raise ValueError(f"record {self.key!r} is absent from both projects")
        if isinstance(self.key, TargetKey) != (self.path is not None):
            raise ValueError(f"only target records must have a path: {self.key!r}")
        for value in (self.local, self.unpacked):
            if value is not None:
                self.validate_value(value)

    def validate_value(self, value: MergeValue) -> Value:
        """Check the payload against the entity identity before accepting it."""
        if not isinstance(value, bytes if isinstance(self.key, FindingKey) else dict):
            raise TypeError(f"Invalid value for {self.key!r}")
        return cast(Value, value)

    @property
    def parent_key(self) -> TargetKey | None:
        """Key of the record this record depends on, if any (excluding the parent excludes this record too)."""
        return self.key.target if isinstance(self.key, FindingKey) else None

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
        return self.in_local and self.in_unpacked and self.local == self.unpacked

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

    def status(self, record: MergeRecord[MergeValue]) -> MergeStatus:
        if record.key in self.statuses:
            return self.statuses[record.key]
        if record.key in self.resolved_values and MergeStatus.RESOLVED in record.available_statuses:
            return MergeStatus.RESOLVED
        return record.default_status

    def parent_excluded(self, record: MergeRecord[MergeValue]) -> bool:
        parent = record.parent_key
        return parent is not None and self.statuses.get(parent) is MergeStatus.EXCLUDED

    def effective_status(self, record: MergeRecord[MergeValue]) -> MergeStatus:
        return MergeStatus.EXCLUDED if self.parent_excluded(record) else self.status(record)

    def set_status(self, record: MergeRecord[MergeValue], status: MergeStatus) -> None:
        if status not in record.available_statuses:
            raise ValueError(f"status {status.value!r} is unavailable for {record.key!r}")
        if status is MergeStatus.RESOLVED:
            # Validate the resolved value for the record before setting the status
            record.value_for_status(status, self.resolved_values.get(record.key))
        self.statuses[record.key] = status

    def resolve(self, record: MergeRecord[MergeValue], value: MergeValue) -> None:
        resolved = record.value_for_status(MergeStatus.RESOLVED, value)
        self.resolved_values[record.key] = resolved
        self.statuses[record.key] = MergeStatus.RESOLVED

    def resolve_all_as(self, records: Sequence[MergeRecord[MergeValue]], source: Literal["local", "unpacked"]) -> None:
        for record in records:
            value = record.local if source == "local" else record.unpacked
            if record.source is MergeSource.BOTH:
                if value is not None and not record.is_identical:
                    # Settle the conflict in favour of the chosen source
                    self.resolve(record, value)
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
            if self.effective_status(record) is not MergeStatus.EXCLUDED:
                selected[record.key] = record.value_for_status(status, self.resolved_values.get(record.key))
        return selected


def _is_list(value: Any) -> TypeGuard[list[Any]]:
    return isinstance(value, list)


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
            records[PersonKey(str(version), identity)] = person.model_dump(mode="json", exclude_unset=True)
    return records


def _load_findings(target_dir: Path) -> dict[str, Any]:
    path = target_dir / "findings.toml"
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _finding_names(config: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for group in config.values():
        if not isinstance(group, dict):
            continue
        findings = cast(dict[str, Any], group).get("findings")
        if _is_list(findings):
            names.extend(finding for finding in findings if isinstance(finding, str))
    return names


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
    targets: Sequence[MergeRecord[dict[str, Any]]],
    selected_targets: set[MergeKey],
) -> list[MergeRecord[bytes]]:
    findings: list[MergeRecord[bytes]] = []
    for target in targets:
        if not isinstance(target.key, TargetKey):
            raise ValueError(f"Expected target record, got {target.key!r}")
        if target.key not in selected_targets:
            continue
        local_names: set[str] = (
            set(_finding_names(_load_findings(local_dir / target.target_dir))) if target.in_local else set()
        )
        unpacked_names: set[str] = (
            set(_finding_names(_load_findings(unpacked_dir / target.target_dir))) if target.in_unpacked else set()
        )
        for name in sorted(local_names | unpacked_names):
            local_path = local_dir / target.target_dir / "findings" / f"{name}.md.j2"
            unpacked_path = unpacked_dir / target.target_dir / "findings" / f"{name}.md.j2"
            local_value = local_path.read_bytes() if local_path.is_file() else b"" if name in local_names else None
            unpacked_value = (
                unpacked_path.read_bytes() if unpacked_path.is_file() else b"" if name in unpacked_names else None
            )
            findings.append(MergeRecord(FindingKey(target.key, name), local_value, unpacked_value))
    return findings


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


def _selected_findings_config(
    local: dict[str, Any],
    unpacked: dict[str, Any],
    selected_names: set[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    assigned: set[str] = set()
    for group_name in [*local, *(name for name in unpacked if name not in local)]:
        local_group = local.get(group_name)
        unpacked_group = unpacked.get(group_name)
        if isinstance(local_group, dict):
            group = copy.deepcopy(cast(dict[str, Any], local_group))
        elif isinstance(unpacked_group, dict):
            group = copy.deepcopy(cast(dict[str, Any], unpacked_group))
        else:
            continue
        available = [
            *(_finding_names({group_name: local_group}) if isinstance(local_group, dict) else []),
            *(name for name in _finding_names({group_name: unpacked_group}) if isinstance(unpacked_group, dict)),
        ]
        chosen = [name for name in dict.fromkeys(available) if name in selected_names and name not in assigned]
        if chosen:
            group["findings"] = chosen
            result[group_name] = group
            assigned.update(chosen)
    return result


def _merge_shared_asset_directories(local_dir: Path, unpacked_dir: Path) -> None:
    for relative_path in (Path("pictures"), Path("layouts/generated")):
        source = unpacked_dir / relative_path
        if source.is_dir():
            shutil.copytree(source, local_dir / relative_path, dirs_exist_ok=True)


@dataclass(frozen=True)
class _MergeOutput:
    config: bytes
    files: dict[Path, bytes]
    target_copies: dict[Path, set[str]]


def _prepare_merge(
    local_dir: Path,
    unpacked_dir: Path,
    records: Sequence[MergeRecord[MergeValue]],
    selected: Mapping[MergeKey, MergeValue],
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
    target_copies: dict[Path, set[str]] = {}
    for target in records:
        if not isinstance(target.key, TargetKey) or target.key not in selected:
            continue
        local_target = local_dir / target.target_dir
        unpacked_target = unpacked_dir / target.target_dir
        all_target_findings = findings_by_target.get(target.key, [])
        target_findings = [key for key in all_target_findings if key in selected]
        if not target.in_local and unpacked_target.is_dir():
            target_copies[target.target_dir] = {
                f"{key.name}.md.j2" for key in all_target_findings if key not in selected
            }
        local_findings = _load_findings(local_target) if target.in_local else {}
        unpacked_findings = _load_findings(unpacked_target) if target.in_unpacked else {}
        finding_names = {key.name for key in target_findings}
        findings_config = _selected_findings_config(local_findings, unpacked_findings, finding_names)
        files[target.target_dir / "findings.toml"] = tomlkit.dumps(findings_config).encode("utf-8")
        for key in target_findings:
            content = selected[key]
            if not isinstance(content, bytes):
                raise TypeError(f"Invalid finding content for {key!r}")
            files[target.target_dir / "findings" / f"{key.name}.md.j2"] = content

    return _MergeOutput((json.dumps(selected_config, indent=2) + "\n").encode("utf-8"), files, target_copies)


def _write_merge(local_dir: Path, unpacked_dir: Path, output: _MergeOutput) -> None:
    for relative_path, excluded in output.target_copies.items():
        source = unpacked_dir / relative_path
        shutil.copytree(
            source,
            local_dir / relative_path,
            dirs_exist_ok=True,
            ignore=lambda directory, names, excluded=excluded, finding_dir=source / "findings": (
                excluded.intersection(names) if Path(directory) == finding_dir else set()
            ),
        )
    for relative_path, content in output.files.items():
        destination = local_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    (local_dir / "config.json").write_bytes(output.config)
    _merge_shared_asset_directories(local_dir, unpacked_dir)


def apply_entity_merge(
    local_dir: Path,
    unpacked_dir: Path,
    records: Sequence[MergeRecord[MergeValue]],
    selection: MergeSelection,
) -> None:
    selected = selection.resolve_selected_values(records)
    output = _prepare_merge(local_dir, unpacked_dir, records, selected)
    _write_merge(local_dir, unpacked_dir, output)
