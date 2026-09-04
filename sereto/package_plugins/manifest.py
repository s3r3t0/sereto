import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import parse_qsl, urlsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from sereto.exceptions import SeretoRuntimeError
from sereto.package_plugins.compatibility import ManifestCompatibility, check_manifest_compatibility
from sereto.package_plugins.paths import PluginPaths
from sereto.package_plugins.protocol_v1 import (
    DistributionIdentity,
    Identifier,
    Manifest,
    NonEmptyString,
    VersionOne,
)

Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SourceKind = Literal["index", "artifact", "vcs"]
HealthStatus = Literal["healthy", "unhealthy"]
_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s]+")
_SENSITIVE_QUERY_KEYS = {
    "access-token",
    "access_token",
    "api-key",
    "api_key",
    "auth",
    "authorization",
    "credential",
    "key",
    "password",
    "secret",
    "signature",
    "token",
    "x-amz-credential",
    "x-amz-signature",
}


class RegistryRecordError(SeretoRuntimeError):
    """A cached plugin record violates registry identity or path constraints."""


class RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class SourceProvenance(RegistryModel):
    kind: SourceKind
    requirement: NonEmptyString
    origin: NonEmptyString
    index_name: Identifier | None = None
    artifact_sha256: Sha256Digest | None = None
    vcs_commit: NonEmptyString | None = None

    @field_validator("requirement", "origin")
    @classmethod
    def reject_credentials(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("source provenance contains control characters")
        for raw_url in _URL.findall(value):
            parsed = urlsplit(raw_url.rstrip(",);]"))
            has_http_userinfo = parsed.scheme.endswith(("http", "https")) and (
                parsed.username is not None or parsed.password is not None
            )
            if has_http_userinfo:
                raise ValueError("source provenance must not contain HTTP userinfo")
            query_keys = {key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
            if query_keys & _SENSITIVE_QUERY_KEYS:
                raise ValueError("source provenance must not contain credential query parameters")
        return value

    @model_validator(mode="after")
    def validate_kind_fields(self) -> Self:
        if self.kind == "index":
            if self.index_name is None:
                raise ValueError("index source provenance requires index_name")
            if self.artifact_sha256 is not None or self.vcs_commit is not None:
                raise ValueError("index source provenance must not define artifact or VCS fields")
        elif self.kind == "artifact":
            if self.artifact_sha256 is None:
                raise ValueError("artifact source provenance requires artifact_sha256")
            if self.index_name is not None or self.vcs_commit is not None:
                raise ValueError("artifact source provenance must not define index or VCS fields")
        elif self.vcs_commit is None:
            raise ValueError("VCS source provenance requires vcs_commit")
        elif self.index_name is not None or self.artifact_sha256 is not None:
            raise ValueError("VCS source provenance must not define index or artifact fields")
        return self


class RuntimeRecord(RegistryModel):
    generation_id: Identifier
    environment_path: Path
    python_path: Path
    python_version: NonEmptyString
    uv_version: NonEmptyString
    lock_digest: Sha256Digest

    @field_validator("python_version", "uv_version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        try:
            Version(value)
        except InvalidVersion as error:
            raise ValueError(f"invalid runtime version {value!r}") from error
        return value


class PluginRecord(RegistryModel):
    plugin_id: Identifier
    distribution: DistributionIdentity
    entry_point: Identifier
    source: SourceProvenance
    runtime: RuntimeRecord
    sdk_package_version: NonEmptyString
    sdk_api_major: VersionOne
    supported_protocol_versions: tuple[VersionOne, ...] = Field(min_length=1)
    selected_protocol_version: VersionOne
    manifest: Manifest
    manifest_digest: Sha256Digest
    health: HealthStatus
    health_message: str | None = None
    installed_at: datetime
    checked_at: datetime

    @field_validator("sdk_package_version")
    @classmethod
    def validate_sdk_version(cls, value: str) -> str:
        try:
            Version(value)
        except InvalidVersion as error:
            raise ValueError(f"invalid SDK package version {value!r}") from error
        return value

    @field_validator("installed_at", "checked_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("registry timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        normalized_distribution = str(canonicalize_name(self.distribution.name))
        try:
            Version(self.distribution.version)
        except InvalidVersion as error:
            raise ValueError(f"invalid distribution version {self.distribution.version!r}") from error
        if self.plugin_id != normalized_distribution:
            raise ValueError("plugin ID must equal the normalized distribution name")
        if self.entry_point != normalized_distribution:
            raise ValueError("entry-point name must equal the normalized distribution name")
        if self.manifest.plugin_id != self.plugin_id:
            raise ValueError("manifest plugin ID does not match the registry record")
        if self.manifest.sdk_api_major != self.sdk_api_major:
            raise ValueError("manifest SDK API major does not match the registry record")
        if self.selected_protocol_version not in self.supported_protocol_versions:
            raise ValueError("selected protocol is not advertised by the installed SDK")
        if self.selected_protocol_version not in self.manifest.protocol_versions:
            raise ValueError("selected protocol is not advertised by the manifest")
        if len(self.supported_protocol_versions) != len(set(self.supported_protocol_versions)):
            raise ValueError("supported protocol versions must be unique")
        if self.manifest_digest != manifest_digest(self.manifest):
            raise ValueError("cached manifest digest does not match the manifest")
        if self.checked_at < self.installed_at:
            raise ValueError("checked_at must not precede installed_at")
        try:
            requirement = Requirement(self.source.requirement)
        except InvalidRequirement as error:
            raise ValueError("source provenance requirement is invalid") from error
        if str(canonicalize_name(requirement.name)) != self.plugin_id:
            raise ValueError("source requirement name does not match the plugin ID")
        return self


def manifest_digest(manifest: Manifest) -> str:
    """Return a deterministic SHA-256 digest for a validated manifest."""
    content = json.dumps(
        manifest.model_dump(mode="json"),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def validate_plugin_record(
    registry_key: str,
    record: PluginRecord,
    paths: PluginPaths,
    sereto_version: str,
) -> ManifestCompatibility:
    """Validate registry key, managed paths, and host compatibility."""
    if registry_key != record.plugin_id:
        raise RegistryRecordError("registry key does not match the plugin ID")

    expected_generation = paths.generation_dir(record.plugin_id, record.runtime.generation_id).resolve()
    if not expected_generation.is_relative_to(paths.root):
        raise RegistryRecordError("active generation resolves outside the managed plugin root")
    expected_environment = (expected_generation / "environment").resolve()
    if not expected_environment.is_relative_to(expected_generation):
        raise RegistryRecordError("plugin environment resolves outside its active generation")
    environment_path = record.runtime.environment_path.resolve()
    python_path = record.runtime.python_path.resolve()
    if not record.runtime.environment_path.is_absolute() or environment_path != expected_environment:
        raise RegistryRecordError("plugin environment path is outside its active generation")
    if not record.runtime.python_path.is_absolute() or not python_path.is_relative_to(environment_path):
        raise RegistryRecordError("plugin Python path is outside its active environment")

    compatibility = check_manifest_compatibility(record.manifest, sereto_version=sereto_version)
    if compatibility.selected_protocol_version != record.selected_protocol_version:
        raise RegistryRecordError("cached selected protocol does not match host compatibility")
    return compatibility
