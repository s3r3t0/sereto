from __future__ import annotations

import copy
import json
import shutil
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeGuard, cast

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


class MergeSource(StrEnum):
    LOCAL = "local"
    UNPACKED = "unpacked"
    BOTH = "both"


class MergeStatus(StrEnum):
    LOCAL = "local"
    UNPACKED = "unpacked"
    MERGED = "merged"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class MergeRecord[Key, Value]:
    key: Key
    local: Value | None
    unpacked: Value | None
    merged: Value | None

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
    def is_conflict(self) -> bool:
        return self.in_local and self.in_unpacked and self.merged is None

    @property
    def available_statuses(self) -> tuple[MergeStatus, ...]:
        if self.source is MergeSource.LOCAL:
            return (MergeStatus.LOCAL, MergeStatus.EXCLUDED)
        if self.source is MergeSource.UNPACKED:
            return (MergeStatus.UNPACKED, MergeStatus.EXCLUDED)
        choices = (MergeStatus.LOCAL, MergeStatus.UNPACKED)
        return (*choices, MergeStatus.MERGED) if self.merged is not None else choices

    @property
    def default_status(self) -> MergeStatus:
        if self.merged is not None:
            return MergeStatus.MERGED
        return self.available_statuses[0]

    def value_for(self, status: MergeStatus) -> Value:
        if status not in self.available_statuses or status is MergeStatus.EXCLUDED:
            raise ValueError(f"status {status.value!r} is unavailable for {self.key!r}")
        value = {
            MergeStatus.LOCAL: self.local,
            MergeStatus.UNPACKED: self.unpacked,
            MergeStatus.MERGED: self.merged,
        }[status]
        if value is None or status not in self.available_statuses:
            raise ValueError(f"status {status.value!r} is unavailable for {self.key!r}")
        return copy.deepcopy(value)


@dataclass(frozen=True)
class MergeDate(MergeRecord[DateKey, dict[str, Any]]):
    pass


@dataclass(frozen=True)
class MergePerson(MergeRecord[PersonKey, dict[str, Any]]):
    pass


@dataclass(frozen=True)
class MergeTarget(MergeRecord[TargetKey, dict[str, Any]]):
    path: Path


@dataclass(frozen=True)
class MergeFinding(MergeRecord[FindingKey, bytes]):
    pass


ResolvedMergeValues = dict[DateKey | PersonKey | TargetKey | FindingKey, dict[str, Any] | bytes]


_CONFLICT = object()


def _is_list(value: Any) -> TypeGuard[list[Any]]:
    return isinstance(value, list)


def _merge_sequences[SequenceItem](
    local: Sequence[SequenceItem],
    unpacked: Sequence[SequenceItem],
    key: Callable[[SequenceItem], str],
) -> list[SequenceItem] | None:
    """Combine changes in distinct regions of two sequences.
    Returns the merged sequence if successful, or None if there are conflicts (different content).
    """
    # Collect shared blocks
    matcher = SequenceMatcher(
        None,
        [key(item) for item in local],
        [key(item) for item in unpacked],
        autojunk=False,
    )
    merged: list[SequenceItem] = []
    local_index = 0
    unpacked_index = 0

    for block in matcher.get_matching_blocks():
        # 1. Resolve the unmatched chunks (gaps) between the matched blocks
        # Collect the (potentially conflicting) chunks in between the index of the last matching block and
        # the current matching block in both sequences
        local_chunk = list(local[local_index : block.a])
        unpacked_chunk = list(unpacked[unpacked_index : block.b])
        if local_chunk and unpacked_chunk:
            # Both gap (unmatched) chunks exist, cannot automatically merge
            return None
        else:
            # Only one of the gap chunks exists (has additional content), keep that one
            merged.extend(local_chunk or unpacked_chunk)

        # 2. Add the matching block itself
        merged.extend(local[block.a : block.a + block.size])
        # Move past the matching block
        local_index = block.a + block.size
        unpacked_index = block.b + block.size

    return merged


def _person_identity(value: Any) -> str | None:
    """Return a unique identity (which is assumed to be email) for a person, or None if it cannot be determined."""
    if not isinstance(value, dict):
        return None
    person = cast(dict[str, Any], value)
    email = person.get("email")
    if not isinstance(email, str) or not email:
        return None
    return email.casefold()


def _merge_people(local: list[Any], unpacked: list[Any]) -> list[Any] | object:
    local_identities = [_person_identity(person) for person in local]
    unpacked_identities = [_person_identity(person) for person in unpacked]
    if None in local_identities or None in unpacked_identities:
        # Cannot compare and therefore possibly merge people lists if any person lacks a unique identity
        return _CONFLICT

    # Create a mapping from identity to the corresponding person
    unpacked_by_identity = dict(zip(unpacked_identities, unpacked, strict=True))
    merged: list[Any] = []
    for identity, local_person in zip(local_identities, local, strict=True):
        if identity not in unpacked_by_identity:
            merged.append(local_person)
            continue
        # Same identity exists in both local and unpacked, attempt to merge
        merged_person = _merge_values(local_person, unpacked_by_identity[identity])
        if merged_person is _CONFLICT:
            return _CONFLICT
        merged.append(merged_person)

    # Add any remaining (unmatched and unpacked-only) people in the unpacked list
    local_identity_set = set(local_identities)
    merged.extend(
        person
        for identity, person in zip(unpacked_identities, unpacked, strict=True)
        if identity not in local_identity_set
    )
    return merged


def _merge_values(local: Any, unpacked: Any, field_name: str | None = None) -> Any:
    if local == unpacked:
        return local
    if isinstance(local, dict) and isinstance(unpacked, dict):
        local_dict = cast(dict[str, Any], local)
        unpacked_dict = cast(dict[str, Any], unpacked)
        merged_dict: dict[str, Any] = {}
        # Fetch all unique keys from both local and unpacked dictionaries
        unique_keys = [*local_dict, *(key for key in unpacked_dict if key not in local_dict)]
        for key in unique_keys:
            if key not in local_dict:
                merged_dict[key] = unpacked_dict[key]
            elif key not in unpacked_dict:
                merged_dict[key] = local_dict[key]
            else:
                # Both local and unpacked have this attribute, attempt to merge their values
                value = _merge_values(local_dict[key], unpacked_dict[key], key)
                if value is _CONFLICT:
                    return _CONFLICT
                merged_dict[key] = value
        return merged_dict
    if _is_list(local) and _is_list(unpacked):
        if field_name == "people":
            return _merge_people(local, unpacked)
        merged_list = _merge_sequences(
            local,
            unpacked,
            lambda value: json.dumps(value, sort_keys=True),
        )
        if merged_list is not None:
            return merged_list
    return _CONFLICT


def _try_merge_text(local: bytes, unpacked: bytes) -> bytes | None:
    try:
        local_text = local.decode("utf-8")
        unpacked_text = unpacked.decode("utf-8")
    except UnicodeDecodeError:
        return None

    merged_lines = _merge_sequences(
        local_text.splitlines(keepends=True),
        unpacked_text.splitlines(keepends=True),
        lambda line: line,
    )
    return None if merged_lines is None else "".join(merged_lines).encode()


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


def discover_merge_targets(local_dir: Path, unpacked_dir: Path) -> list[MergeTarget]:
    local = _target_records(_load_config(local_dir))
    unpacked = _target_records(_load_config(unpacked_dir))
    targets: list[MergeTarget] = []
    for key in sorted(local.keys() | unpacked.keys()):
        _, path = local.get(key) or unpacked[key]
        local_value = local.get(key, (None, path))[0]
        unpacked_value = unpacked.get(key, (None, path))[0]
        merged = None
        if local_value is not None and unpacked_value is not None:
            value = _merge_values(local_value, unpacked_value)
            merged = None if value is _CONFLICT else cast(dict[str, Any], value)
        targets.append(
            MergeTarget(
                key=key,
                local=copy.deepcopy(local_value),
                unpacked=copy.deepcopy(unpacked_value),
                merged=copy.deepcopy(merged),
                path=path,
            )
        )
    return targets


def discover_merge_dates(local_dir: Path, unpacked_dir: Path) -> list[MergeDate]:
    local = _date_records(_load_config(local_dir))
    unpacked = _date_records(_load_config(unpacked_dir))
    dates: list[MergeDate] = []
    for key in sorted(local.keys() | unpacked.keys()):
        local_value = local.get(key)
        unpacked_value = unpacked.get(key)
        merged = None
        if local_value is not None and unpacked_value is not None:
            value = _merge_values(local_value, unpacked_value)
            merged = None if value is _CONFLICT else cast(dict[str, Any], value)
        dates.append(
            MergeDate(
                key=key,
                local=copy.deepcopy(local_value),
                unpacked=copy.deepcopy(unpacked_value),
                merged=copy.deepcopy(merged),
            )
        )
    return dates


def discover_merge_people(local_dir: Path, unpacked_dir: Path) -> list[MergePerson]:
    local = _person_records(_load_config(local_dir), MergeSource.LOCAL)
    unpacked = _person_records(_load_config(unpacked_dir), MergeSource.UNPACKED)
    people: list[MergePerson] = []
    for key in sorted(local.keys() | unpacked.keys()):
        local_value = local.get(key)
        unpacked_value = unpacked.get(key)
        merged = None
        if local_value is not None and unpacked_value is not None:
            value = _merge_values(local_value, unpacked_value)
            merged = None if value is _CONFLICT else cast(dict[str, Any], value)
        people.append(
            MergePerson(
                key=key,
                local=copy.deepcopy(local_value),
                unpacked=copy.deepcopy(unpacked_value),
                merged=copy.deepcopy(merged),
            )
        )
    return people


def discover_merge_findings(
    local_dir: Path,
    unpacked_dir: Path,
    targets: list[MergeTarget],
    selected_targets: set[TargetKey],
) -> list[MergeFinding]:
    findings: list[MergeFinding] = []
    for target in targets:
        if target.key not in selected_targets:
            continue
        local_names: set[str] = (
            set(_finding_names(_load_findings(local_dir / target.path))) if target.in_local else set()
        )
        unpacked_names: set[str] = (
            set(_finding_names(_load_findings(unpacked_dir / target.path))) if target.in_unpacked else set()
        )
        for name in sorted(local_names | unpacked_names):
            local_path = local_dir / target.path / "findings" / f"{name}.md.j2"
            unpacked_path = unpacked_dir / target.path / "findings" / f"{name}.md.j2"
            local_value = local_path.read_bytes() if local_path.is_file() else b"" if name in local_names else None
            unpacked_value = (
                unpacked_path.read_bytes() if unpacked_path.is_file() else b"" if name in unpacked_names else None
            )
            merged = (
                _try_merge_text(local_value, unpacked_value)
                if local_value is not None and unpacked_value is not None
                else None
            )
            findings.append(MergeFinding(FindingKey(target.key, name), local_value, unpacked_value, merged))
    return findings


def _merge_target_data(local: dict[str, Any], unpacked: dict[str, Any]) -> dict[str, Any]:
    merged = _merge_values(local, unpacked)
    return copy.deepcopy(local if merged is _CONFLICT else cast(dict[str, Any], merged))


def _selected_config(
    local_config: dict[str, Any],
    unpacked_config: dict[str, Any],
    local_model: ConfigModel,
    unpacked_model: ConfigModel,
    dates: list[MergeDate],
    people: list[MergePerson],
    targets: list[MergeTarget],
    statuses: dict[DateKey | PersonKey | TargetKey | FindingKey, MergeStatus],
    resolved_values: ResolvedMergeValues,
) -> dict[str, Any]:
    merged_value = _merge_values(local_config, unpacked_config)
    result = copy.deepcopy(local_config if merged_value is _CONFLICT else cast(dict[str, Any], merged_value))
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
        version_data["targets"] = []
        version_data["dates"] = []
        version_data["people"] = []

    targets_by_key = {target.key: target for target in targets}
    target_keys = [*local_targets, *(key for key in unpacked_targets if key not in local_targets)]
    for target_key in target_keys:
        target = targets_by_key[target_key]
        if statuses.get(target.key) is MergeStatus.EXCLUDED:
            continue
        value = resolved_values.get(target.key)
        if value is None:
            value = target.value_for(statuses.get(target.key, target.default_status))
        cast(list[Any], cast(dict[str, Any], result_versions[target.key.version])["targets"]).append(value)

    dates_by_key = {date.key: date for date in dates}
    date_keys = [*local_dates, *(key for key in unpacked_dates if key not in local_dates)]
    for date_key in date_keys:
        date = dates_by_key[date_key]
        if statuses.get(date.key) is MergeStatus.EXCLUDED:
            continue
        value = resolved_values.get(date.key)
        if value is None:
            value = date.value_for(statuses.get(date.key, date.default_status))
        cast(list[Any], cast(dict[str, Any], result_versions[date.key.version])["dates"]).append(value)

    people_by_key = {person.key: person for person in people}
    person_keys = [*local_people, *(key for key in unpacked_people if key not in local_people)]
    for person_key in person_keys:
        person = people_by_key[person_key]
        if statuses.get(person.key) is MergeStatus.EXCLUDED:
            continue
        value = resolved_values.get(person.key)
        if value is None:
            value = person.value_for(statuses.get(person.key, person.default_status))
        cast(list[Any], cast(dict[str, Any], result_versions[person.key.version])["people"]).append(value)

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
        if isinstance(local_group, dict) and isinstance(unpacked_group, dict):
            group = _merge_target_data(cast(dict[str, Any], local_group), cast(dict[str, Any], unpacked_group))
        elif isinstance(local_group, dict):
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


def apply_entity_merge(
    local_dir: Path,
    unpacked_dir: Path,
    dates: list[MergeDate],
    people: list[MergePerson],
    targets: list[MergeTarget],
    findings: list[MergeFinding],
    statuses: dict[DateKey | PersonKey | TargetKey | FindingKey, MergeStatus],
    resolved_values: ResolvedMergeValues | None = None,
) -> None:
    selected_values = resolved_values or {}
    records: list[MergeDate | MergePerson | MergeTarget | MergeFinding] = [*dates, *people, *targets, *findings]
    for record in records:
        status = statuses.get(record.key, record.default_status)
        if status not in record.available_statuses:
            raise ValueError(f"status {status.value!r} is unavailable for {record.key!r}")
        if record.key in selected_values:
            value = selected_values[record.key]
            if isinstance(record, MergeFinding) != isinstance(value, bytes):
                raise TypeError(f"Invalid resolved value for {record.key!r}")

    local_model = _load_config(local_dir)
    unpacked_model = _load_config(unpacked_dir)
    local_config = _load_config_data(local_dir)
    unpacked_config = _load_config_data(unpacked_dir)
    selected_config = _selected_config(
        local_config,
        unpacked_config,
        local_model,
        unpacked_model,
        dates,
        people,
        targets,
        statuses,
        selected_values,
    )
    ConfigModel.model_validate_json(json.dumps(selected_config))

    findings_by_target: dict[TargetKey, list[MergeFinding]] = {}
    for finding in findings:
        findings_by_target.setdefault(finding.key.target, []).append(finding)

    for target in targets:
        if statuses.get(target.key) is MergeStatus.EXCLUDED:
            continue
        local_target = local_dir / target.path
        unpacked_target = unpacked_dir / target.path
        all_target_findings = findings_by_target.get(target.key, [])
        target_findings = [
            finding for finding in all_target_findings if statuses.get(finding.key) is not MergeStatus.EXCLUDED
        ]
        if not target.in_local and unpacked_target.is_dir():
            excluded_files = {
                f"{finding.key.name}.md.j2"
                for finding in all_target_findings
                if statuses.get(finding.key) is MergeStatus.EXCLUDED
            }
            shutil.copytree(
                unpacked_target,
                local_target,
                dirs_exist_ok=True,
                ignore=lambda directory, names, excluded=excluded_files, finding_dir=unpacked_target / "findings": (
                    excluded.intersection(names) if Path(directory) == finding_dir else set()
                ),
            )

        local_findings = _load_findings(local_target) if target.in_local else {}
        unpacked_findings = _load_findings(unpacked_target) if target.in_unpacked else {}
        finding_names = {finding.key.name for finding in target_findings}
        findings_config = _selected_findings_config(local_findings, unpacked_findings, finding_names)
        local_target.mkdir(parents=True, exist_ok=True)
        (local_target / "findings.toml").write_text(tomlkit.dumps(findings_config), encoding="utf-8")
        for finding in target_findings:
            content = selected_values.get(finding.key)
            if content is None:
                content = finding.value_for(statuses.get(finding.key, finding.default_status))
            assert isinstance(content, bytes)
            destination = local_target / "findings" / f"{finding.key.name}.md.j2"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)

    (local_dir / "config.json").write_text(json.dumps(selected_config, indent=2) + "\n", encoding="utf-8")
    _merge_shared_asset_directories(local_dir, unpacked_dir)
