import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

import sereto.package_plugins.paths as paths_module
import sereto.package_plugins.registry as registry_module
from sereto.exceptions import SeretoValueError
from sereto.finding import Findings
from sereto.models.target import TargetModel
from sereto.models.version import ProjectVersion
from sereto.package_plugins.compatibility import (
    CompatibilityError,
    CompatibilityTuple,
    check_manifest_compatibility,
)
from sereto.package_plugins.manifest import (
    PluginRecord,
    RegistryRecordError,
    RuntimeRecord,
    SourceProvenance,
    manifest_digest,
    validate_plugin_record,
)
from sereto.package_plugins.paths import PluginPaths
from sereto.package_plugins.protocol_v1 import Manifest, ResourceReference
from sereto.package_plugins.registry import (
    PluginRegistry,
    RegistryConflictError,
    RegistryError,
    RegistryState,
)
from sereto.package_plugins.resources import TargetResources
from sereto.target import Target


def _manifest(**changes: object) -> Manifest:
    values: dict[str, object] = {
        "plugin_id": "acme-testssl",
        "requires_sereto": ">=0.9,<1",
        "capabilities": ["finding.propose"],
        "resource_kinds": ["sereto.target.v1"],
        "operations": [
            {
                "id": "testssl.analyze",
                "capability": "finding.propose",
                "resource_kinds": ["sereto.target.v1"],
            }
        ],
        "commands": [
            {
                "path": ["findings", "testssl"],
                "operation_id": "testssl.analyze",
                "summary": "Analyze testssl output",
            }
        ],
    }
    values.update(changes)
    return Manifest.model_validate(values)


def test_compatibility_selects_supported_protocol_for_matching_host() -> None:
    compatibility = check_manifest_compatibility(_manifest(), sereto_version="0.9.0")

    assert compatibility.selected_protocol_version == 1
    assert compatibility.sdk_api_major == 1
    assert compatibility.supported_operations == ("testssl.analyze",)


def test_compatibility_rejects_incompatible_sereto_version() -> None:
    with pytest.raises(CompatibilityError, match="requires SeReTo >=0.9,<1, but 0.8.3 is running"):
        check_manifest_compatibility(_manifest(), sereto_version="0.8.3")


@pytest.mark.parametrize(
    ("manifest_changes", "sereto_version", "message"),
    [
        pytest.param(
            {"requires_sereto": "not a specifier"},
            "0.9.0",
            "plugin has invalid requires_sereto",
            id="invalid-requirement",
        ),
        pytest.param({}, "not a version", "invalid SeReTo version", id="invalid-host-version"),
    ],
)
def test_compatibility_rejects_malformed_versions(
    manifest_changes: dict[str, object],
    sereto_version: str,
    message: str,
) -> None:
    with pytest.raises(CompatibilityError, match=message):
        check_manifest_compatibility(_manifest(**manifest_changes), sereto_version=sereto_version)


def test_compatibility_rejects_missing_mutual_protocol() -> None:
    with pytest.raises(CompatibilityError, match="no mutually supported protocol version"):
        check_manifest_compatibility(
            _manifest(),
            sereto_version="0.9.0",
            supported_combinations=frozenset(),
        )


def test_compatibility_rejects_unsupported_capability_resource_tuple() -> None:
    incompatible_matrix = frozenset(
        {
            CompatibilityTuple(
                protocol_version=1,
                sdk_api_major=1,
                capability="finding.propose",
                resource_kind="sereto.other.v1",
            )
        }
    )

    with pytest.raises(CompatibilityError, match="testssl.analyze"):
        check_manifest_compatibility(
            _manifest(),
            sereto_version="0.9.0",
            supported_combinations=incompatible_matrix,
        )


def _record(paths: PluginPaths) -> PluginRecord:
    manifest = _manifest()
    generation_id = "generation-1"
    environment_path = paths.generation_dir(manifest.plugin_id, generation_id) / "environment"
    return PluginRecord(
        plugin_id=manifest.plugin_id,
        distribution={"name": "Acme_TestSSL", "version": "2.4.1"},
        entry_point="acme-testssl",
        source=SourceProvenance(
            kind="index",
            requirement="acme-testssl==2.4.1",
            origin="https://pypi.org/simple",
            index_name="pypi",
        ),
        runtime=RuntimeRecord(
            generation_id=generation_id,
            environment_path=environment_path,
            python_path=environment_path / "bin" / "python",
            python_version="3.14.7",
            uv_version="0.9.26",
            lock_digest="a" * 64,
        ),
        sdk_package_version="0.1.0",
        sdk_api_major=1,
        supported_protocol_versions=(1,),
        selected_protocol_version=1,
        manifest=manifest,
        manifest_digest=manifest_digest(manifest),
        health="healthy",
        installed_at=datetime(2026, 9, 1, tzinfo=UTC),
        checked_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def test_plugin_paths_are_inert_and_record_binds_identity_and_runtime(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    record = _record(paths)

    compatibility = validate_plugin_record(
        registry_key="acme-testssl",
        record=record,
        paths=paths,
        sereto_version="0.9.0",
    )

    assert compatibility.selected_protocol_version == 1
    assert record.runtime.environment_path == (
        paths.root / "acme-testssl" / "generations" / "generation-1" / "environment"
    )
    assert not paths.root.exists()


def test_default_plugin_paths_use_user_data_directory_without_creating_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_home = tmp_path / "data" / "sereto"

    def fake_user_data_path(app_name: str) -> Path:
        assert app_name == "sereto"
        return data_home

    monkeypatch.setattr(paths_module, "user_data_path", fake_user_data_path)

    paths = PluginPaths.default()

    assert paths.root == data_home / "plugins"
    assert paths.registry_file == data_home / "plugins" / "registry.json"
    assert not data_home.exists()


@pytest.mark.parametrize("value", ["../escape", "/absolute", "bad/name", "", "."])
def test_plugin_paths_reject_unsafe_segments(tmp_path: Path, value: str) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")

    with pytest.raises(SeretoValueError, match="invalid plugin ID"):
        paths.plugin_dir(value)
    with pytest.raises(SeretoValueError, match="invalid generation ID"):
        paths.generation_dir("acme-testssl", value)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        pytest.param("entry_point", "other-plugin", "entry-point name", id="entry-point"),
        pytest.param("manifest_digest", "b" * 64, "cached manifest digest", id="manifest-digest"),
        pytest.param("plugin_id", "other-plugin", "normalized distribution name", id="plugin-id"),
    ],
)
def test_plugin_record_rejects_spoofed_cached_identity(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    record = _record(PluginPaths(root=tmp_path / "plugins"))
    payload = record.model_dump(mode="python")
    payload[field] = value

    with pytest.raises(ValidationError, match=message):
        PluginRecord.model_validate(payload)


def test_plugin_record_rejects_manifest_plugin_id_spoofing(tmp_path: Path) -> None:
    record = _record(PluginPaths(root=tmp_path / "plugins"))
    spoofed_manifest = _manifest(plugin_id="other-plugin")
    payload = record.model_dump(mode="python")
    payload["manifest"] = spoofed_manifest
    payload["manifest_digest"] = manifest_digest(spoofed_manifest)

    with pytest.raises(ValidationError, match="manifest plugin ID does not match"):
        PluginRecord.model_validate(payload)


def test_plugin_record_rejects_registry_key_and_runtime_path_escape(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    record = _record(paths)

    with pytest.raises(RegistryRecordError, match="registry key does not match"):
        validate_plugin_record("other-plugin", record, paths, sereto_version="0.9.0")

    escaped_runtime = record.runtime.model_copy(update={"environment_path": tmp_path / "outside"})
    escaped_record = record.model_copy(update={"runtime": escaped_runtime})
    with pytest.raises(RegistryRecordError, match="environment path is outside"):
        validate_plugin_record(record.plugin_id, escaped_record, paths, sereto_version="0.9.0")

    escaped_python = record.runtime.model_copy(update={"python_path": tmp_path / "python"})
    escaped_record = record.model_copy(update={"runtime": escaped_python})
    with pytest.raises(RegistryRecordError, match="Python path is outside"):
        validate_plugin_record(record.plugin_id, escaped_record, paths, sereto_version="0.9.0")


def test_plugin_record_rejects_generation_symlink_outside_managed_root(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    outside = tmp_path / "outside"
    outside.mkdir()
    paths.generations_dir("acme-testssl").mkdir(parents=True)
    paths.generation_dir("acme-testssl", "generation-1").symlink_to(outside, target_is_directory=True)
    record = _record(paths)

    with pytest.raises(RegistryRecordError, match="active generation resolves outside the managed plugin root"):
        validate_plugin_record(record.plugin_id, record, paths, sereto_version="0.9.0")


def test_plugin_record_rejects_environment_symlink_outside_generation(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    generation = paths.generation_dir("acme-testssl", "generation-1")
    generation.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (generation / "environment").symlink_to(outside, target_is_directory=True)
    record = _record(paths)

    with pytest.raises(RegistryRecordError, match="environment resolves outside its active generation"):
        validate_plugin_record(record.plugin_id, record, paths, sereto_version="0.9.0")


@pytest.mark.parametrize(
    "origin",
    [
        pytest.param("https://user:password@example.test/simple", id="http-userinfo"),
        pytest.param("https://example.test/simple?token=secret", id="query-token"),
        pytest.param("https://example.test/simple?X-Amz-Signature=secret", id="signed-query"),
    ],
)
def test_source_provenance_rejects_credential_shaped_urls(origin: str) -> None:
    with pytest.raises(ValidationError, match="source provenance must not contain"):
        SourceProvenance(
            kind="index",
            requirement="acme-testssl==2.4.1",
            origin=origin,
            index_name="private",
        )


def test_source_provenance_rejects_fields_from_another_source_kind() -> None:
    with pytest.raises(ValidationError, match="index source provenance must not define artifact or VCS fields"):
        SourceProvenance(
            kind="index",
            requirement="acme-testssl==2.4.1",
            origin="https://pypi.org/simple",
            index_name="pypi",
            artifact_sha256="a" * 64,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        pytest.param(
            {"distribution": {"name": "acme-testssl", "version": "not a version"}},
            "invalid distribution version",
            id="distribution-version",
        ),
        pytest.param(
            {"supported_protocol_versions": (1, 1)},
            "supported protocol versions must be unique",
            id="duplicate-protocol",
        ),
        pytest.param(
            {
                "installed_at": datetime(2026, 9, 2, tzinfo=UTC),
                "checked_at": datetime(2026, 9, 1, tzinfo=UTC),
            },
            "checked_at must not precede installed_at",
            id="timestamp-order",
        ),
    ],
)
def test_plugin_record_rejects_invalid_cached_metadata(
    tmp_path: Path,
    changes: dict[str, object],
    message: str,
) -> None:
    record = _record(PluginPaths(root=tmp_path / "plugins"))
    payload = record.model_dump(mode="python")
    payload.update(changes)

    with pytest.raises(ValidationError, match=message):
        PluginRecord.model_validate(payload)


def test_registry_load_is_inert_and_replace_round_trips_private_state(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    registry = PluginRegistry(paths=paths, sereto_version="0.9.0")

    empty = registry.load()

    assert empty.state.plugins == {}
    assert empty.digest is None
    assert empty.issues == ()
    assert not paths.root.exists()

    state = RegistryState(plugins={"acme-testssl": _record(paths)})
    committed = registry.replace(state, expected_digest=empty.digest)
    loaded = registry.load()

    assert committed.digest == loaded.digest
    assert loaded.state == state
    assert loaded.issues == ()
    assert paths.registry_file.is_file()
    if os.name != "nt":
        assert paths.registry_file.stat().st_mode & 0o777 == 0o600

    plugins = cast(dict[str, PluginRecord], loaded.state.plugins)
    with pytest.raises(TypeError):
        plugins["other-plugin"] = _record(paths)


def test_registry_reads_validated_file_descriptor_without_reopening_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    registry = PluginRegistry(paths=paths, sereto_version="0.9.0")
    expected = registry.replace(
        RegistryState(plugins={"acme-testssl": _record(paths)}),
        expected_digest=None,
    )

    def reject_path_reopen(path: Path) -> bytes:
        raise AssertionError(f"registry path was reopened: {path}")

    monkeypatch.setattr(Path, "read_bytes", reject_path_reopen)

    assert registry.load() == expected


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink check")
def test_registry_rejects_symbolic_link(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    paths.root.mkdir()
    external_registry = tmp_path / "external.json"
    external_registry.write_text('{"schema_version":1,"plugins":{}}', encoding="utf-8")
    paths.registry_file.symlink_to(external_registry)

    with pytest.raises(RegistryError, match="plugin registry must not be a symbolic link"):
        PluginRegistry(paths=paths, sereto_version="0.9.0").load()


@pytest.mark.skipif(os.name == "nt", reason="POSIX ownership and mode check")
def test_registry_rejects_insecure_state_permissions(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    registry = PluginRegistry(paths=paths, sereto_version="0.9.0")
    registry.replace(RegistryState(plugins={"acme-testssl": _record(paths)}), expected_digest=None)
    paths.registry_file.chmod(0o644)

    with pytest.raises(RegistryError, match="plugin registry permissions"):
        registry.load()


def test_registry_issue_redacts_credential_shaped_invalid_input(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    registry = PluginRegistry(paths=paths, sereto_version="0.9.0")
    registry.replace(RegistryState(plugins={"acme-testssl": _record(paths)}), expected_digest=None)
    document = json.loads(paths.registry_file.read_text(encoding="utf-8"))
    document["plugins"]["acme-testssl"]["source"]["origin"] = "https://user:supersecret@example.test/simple"
    paths.registry_file.write_text(json.dumps(document), encoding="utf-8")

    snapshot = registry.load()

    assert snapshot.state.plugins == {}
    assert len(snapshot.issues) == 1
    assert "supersecret" not in snapshot.issues[0].message


def test_registry_replace_rejects_stale_snapshot(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    registry = PluginRegistry(paths=paths, sereto_version="0.9.0")
    state = RegistryState(plugins={"acme-testssl": _record(paths)})
    committed = registry.replace(state, expected_digest=None)

    with pytest.raises(RegistryConflictError, match="changed after it was loaded"):
        registry.replace(state, expected_digest=None)

    assert registry.load() == committed


def test_registry_atomic_replace_failure_preserves_previous_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    registry = PluginRegistry(paths=paths, sereto_version="0.9.0")
    original_state = RegistryState(plugins={"acme-testssl": _record(paths)})
    snapshot = registry.replace(original_state, expected_digest=None)
    original_content = paths.registry_file.read_bytes()
    updated_record = _record(paths).model_copy(update={"health": "unhealthy", "health_message": "test"})
    updated_state = RegistryState(plugins={"acme-testssl": updated_record})

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("injected registry replacement failure")

    monkeypatch.setattr(registry_module.os, "replace", fail_replace)

    with pytest.raises(RegistryError, match="cannot replace plugin registry"):
        registry.replace(updated_state, expected_digest=snapshot.digest)

    assert paths.registry_file.read_bytes() == original_content
    assert list(paths.root.glob(".registry-*.tmp")) == []


@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param(b"not JSON", "invalid plugin registry JSON", id="invalid-json"),
        pytest.param(
            json.dumps({"schema_version": 2, "plugins": {}}).encode(),
            "unsupported plugin registry schema version",
            id="unknown-schema",
        ),
        pytest.param(
            b'{"schema_version":1,"plugins":{},"plugins":{}}',
            "duplicate JSON key 'plugins'",
            id="duplicate-key",
        ),
    ],
)
def test_registry_rejects_corrupt_top_level_document(tmp_path: Path, content: bytes, message: str) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    paths.root.mkdir()
    paths.registry_file.write_bytes(content)
    if os.name != "nt":
        paths.registry_file.chmod(0o600)

    with pytest.raises(RegistryError, match=message):
        PluginRegistry(paths=paths, sereto_version="0.9.0").load()


def test_registry_isolates_invalid_record_from_valid_plugins(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    valid_record = _record(paths)
    invalid_record = valid_record.model_dump(mode="json")
    invalid_record["manifest_digest"] = "b" * 64
    paths.root.mkdir()
    paths.registry_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "plugins": {
                    "acme-testssl": valid_record.model_dump(mode="json"),
                    "broken-plugin": invalid_record,
                },
            }
        ),
        encoding="utf-8",
    )
    if os.name != "nt":
        paths.registry_file.chmod(0o600)

    snapshot = PluginRegistry(paths=paths, sereto_version="0.9.0").load()

    assert list(snapshot.state.plugins) == ["acme-testssl"]
    assert len(snapshot.issues) == 1
    assert snapshot.issues[0].plugin_id == "broken-plugin"
    assert snapshot.issues[0].code == "invalid-record"

    with pytest.raises(RegistryError, match="contains invalid or incompatible records"):
        PluginRegistry(paths=paths, sereto_version="0.9.0").replace(
            snapshot.state,
            expected_digest=snapshot.digest,
        )

    repaired = PluginRegistry(paths=paths, sereto_version="0.9.0").replace(
        snapshot.state,
        expected_digest=snapshot.digest,
        allow_repair=True,
    )
    assert list(repaired.state.plugins) == ["acme-testssl"]


def test_registry_isolates_record_incompatible_with_current_host(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    registry = PluginRegistry(paths=paths, sereto_version="0.9.0")
    snapshot = registry.replace(
        RegistryState(plugins={"acme-testssl": _record(paths)}),
        expected_digest=None,
    )

    incompatible = PluginRegistry(paths=paths, sereto_version="1.0.0").load()

    assert incompatible.state.plugins == {}
    assert incompatible.digest == snapshot.digest
    assert len(incompatible.issues) == 1
    assert incompatible.issues[0].code == "incompatible-record"


def test_registry_doctor_reports_static_runtime_issues_without_mutation(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    registry = PluginRegistry(paths=paths, sereto_version="0.9.0")
    unhealthy = _record(paths).model_copy(update={"health": "unhealthy", "health_message": "check failed"})
    registry.replace(RegistryState(plugins={"acme-testssl": unhealthy}), expected_digest=None)
    content_before = paths.registry_file.read_bytes()

    issues = registry.doctor()

    assert {(issue.code, issue.plugin_id) for issue in issues} == {
        ("unhealthy-record", "acme-testssl"),
        ("missing-environment", "acme-testssl"),
        ("missing-python", "acme-testssl"),
    }
    assert paths.registry_file.read_bytes() == content_before


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode check")
def test_registry_state_files_are_private_with_permissive_umask(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    registry = PluginRegistry(paths=paths, sereto_version="0.9.0")
    previous_umask = os.umask(0)
    try:
        registry.replace(RegistryState(plugins={"acme-testssl": _record(paths)}), expected_digest=None)
    finally:
        os.umask(previous_umask)

    assert paths.root.stat().st_mode & 0o777 == 0o700
    assert paths.registry_file.stat().st_mode & 0o777 == 0o600
    assert paths.registry_lock.stat().st_mode & 0o777 == 0o600


def test_target_v1_resource_exposes_bounded_data_and_resolves_opaque_reference(tmp_path: Path) -> None:
    target_path = tmp_path / "target"
    target_path.mkdir()
    target = Target(
        data=TargetModel.model_validate(
            {
                "category": "infrastructure",
                "name": "External TLS",
                "locators": [{"type": "hostname", "value": "example.test"}],
                "private_extra": "must not cross the boundary",
            },
            context={"categories": ["infrastructure"]},
        ),
        findings=Findings(groups=[], target_dir=target_path, target_locators=[]),
        path=target_path,
        version=ProjectVersion.from_str("v1.0"),
    )
    resources = TargetResources.from_targets([target], id_factory=lambda: "target_1")

    resource = resources.resources[0]

    assert resource.model_dump(mode="json") == {
        "kind": "sereto.target.v1",
        "id": "target_1",
        "attributes": {
            "category": "infrastructure",
            "name": "External TLS",
            "version": "v1.0",
            "locators": [{"type": "hostname", "value": "example.test"}],
        },
    }
    assert "path" not in json.dumps(resource.model_dump(mode="json"))
    assert "private_extra" not in json.dumps(resource.model_dump(mode="json"))
    assert resources.resolve(ResourceReference(kind="sereto.target.v1", id="target_1")) is target


def test_target_resources_reject_duplicate_and_unknown_handles(tmp_path: Path) -> None:
    target_path = tmp_path / "target"
    target_path.mkdir()
    target = Target(
        data=TargetModel.model_validate(
            {"category": "infrastructure", "name": "External TLS"},
            context={"categories": ["infrastructure"]},
        ),
        findings=Findings(groups=[], target_dir=target_path, target_locators=[]),
        path=target_path,
        version=ProjectVersion.from_str("v1.0"),
    )

    with pytest.raises(SeretoValueError, match="duplicate package-plugin resource ID"):
        TargetResources.from_targets([target, target], id_factory=lambda: "target_1")

    resources = TargetResources.from_targets([target], id_factory=lambda: "target_1")
    with pytest.raises(SeretoValueError, match="unknown package-plugin target resource"):
        resources.resolve(ResourceReference(kind="sereto.target.v1", id="target_other"))
