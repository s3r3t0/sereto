from dataclasses import dataclass

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from sereto.exceptions import SeretoRuntimeError
from sereto.package_plugins.protocol_v1 import Manifest


class CompatibilityError(SeretoRuntimeError):
    """A package plugin manifest isn't compatible with this SeReTo host."""


@dataclass(frozen=True)
class CompatibilityTuple:
    protocol_version: int
    sdk_api_major: int
    capability: str
    resource_kind: str


@dataclass(frozen=True)
class ManifestCompatibility:
    selected_protocol_version: int
    sdk_api_major: int
    supported_operations: tuple[str, ...]


SUPPORTED_COMBINATIONS = frozenset(
    {
        CompatibilityTuple(
            protocol_version=1,
            sdk_api_major=1,
            capability="finding.propose",
            resource_kind="sereto.target.v1",
        )
    }
)


def check_manifest_compatibility(
    manifest: Manifest,
    sereto_version: str,
    supported_combinations: frozenset[CompatibilityTuple] = SUPPORTED_COMBINATIONS,
) -> ManifestCompatibility:
    """Validate a manifest against host version and finite capability support."""
    try:
        host_version = Version(sereto_version)
    except InvalidVersion as error:
        raise CompatibilityError(f"invalid SeReTo version {sereto_version!r}") from error
    try:
        required_versions = SpecifierSet(manifest.requires_sereto)
    except InvalidSpecifier as error:
        raise CompatibilityError(f"plugin has invalid requires_sereto {manifest.requires_sereto!r}") from error
    if host_version not in required_versions:
        raise CompatibilityError(f"plugin requires SeReTo {manifest.requires_sereto}, but {sereto_version} is running")

    supported_protocols = sorted(
        {
            combination.protocol_version
            for combination in supported_combinations
            if combination.sdk_api_major == manifest.sdk_api_major
        }
        & set(manifest.protocol_versions),
        reverse=True,
    )
    if not supported_protocols:
        raise CompatibilityError(f"plugin SDK API {manifest.sdk_api_major} has no mutually supported protocol version")

    selected_protocol = supported_protocols[0]
    unsupported_operations = [
        operation.id
        for operation in manifest.operations
        if not any(
            CompatibilityTuple(
                protocol_version=selected_protocol,
                sdk_api_major=manifest.sdk_api_major,
                capability=operation.capability,
                resource_kind=resource_kind,
            )
            in supported_combinations
            for resource_kind in operation.resource_kinds
        )
    ]
    if unsupported_operations:
        raise CompatibilityError(
            "plugin operations have no supported capability/resource combination: " + ", ".join(unsupported_operations)
        )

    return ManifestCompatibility(
        selected_protocol_version=selected_protocol,
        sdk_api_major=manifest.sdk_api_major,
        supported_operations=tuple(operation.id for operation in manifest.operations),
    )
