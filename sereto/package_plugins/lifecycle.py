import shutil
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from sereto.exceptions import SeretoRuntimeError
from sereto.package_plugins.compatibility import check_manifest_compatibility
from sereto.package_plugins.manifest import PluginRecord, RuntimeRecord, SourceProvenance, manifest_digest
from sereto.package_plugins.paths import PluginPaths
from sereto.package_plugins.protocol_v1 import DistributionIdentity, Manifest, VersionOne
from sereto.package_plugins.registry import PluginRegistry, RegistryIssue, RegistrySnapshot, RegistryState
from sereto.package_plugins.session import PluginLaunch, PluginSession, SessionLimits

MANIFEST_DISCOVERY_TIMEOUT_SECONDS = 30.0


class PluginLifecycleError(SeretoRuntimeError):
    """A managed package-plugin lifecycle operation failed safely."""


@dataclass(frozen=True)
class PluginIndex:
    name: str
    url: str


@dataclass(frozen=True)
class PluginInstallRequest:
    source: str
    indexes: tuple[PluginIndex, ...] = ()
    default_index: str | None = None
    source_index: str | None = None
    keyring_provider: Literal["disabled", "subprocess"] = "disabled"


@dataclass(frozen=True)
class PreparedPluginEnvironment:
    plugin_id: str
    distribution_name: str
    distribution_version: str
    entry_point: str
    generation_id: str
    generation_path: Path
    environment_path: Path
    python_path: Path
    python_version: str
    uv_version: str
    lock_digest: str
    sdk_package_version: str
    sdk_api_major: Literal[1]
    supported_protocol_versions: tuple[VersionOne, ...]
    source: SourceProvenance


class PackageManager(Protocol):
    def prepare(
        self,
        request: PluginInstallRequest,
        paths: PluginPaths,
    ) -> PreparedPluginEnvironment: ...

    def version(self) -> str: ...


type ManifestDiscoverer = Callable[[PreparedPluginEnvironment], Awaitable[Manifest]]


class PluginLifecycle:
    """Coordinate isolated environments with atomic registry activation."""

    def __init__(
        self,
        registry: PluginRegistry,
        package_manager: PackageManager,
        discover_manifest: ManifestDiscoverer | None = None,
    ) -> None:
        self.registry = registry
        self.package_manager = package_manager
        self._discover_manifest = discover_manifest or self._discover_with_session

    async def install(self, request: PluginInstallRequest) -> PluginRecord:
        """Prepare and activate one new plugin without exposing failed candidates."""
        with self.registry.locked_lifecycle():
            return await self._install_locked(request)

    async def _install_locked(self, request: PluginInstallRequest) -> PluginRecord:
        snapshot = self.registry.load()
        if snapshot.issues:
            raise PluginLifecycleError("plugin registry requires repair before installing plugins")

        prepared = self.package_manager.prepare(request, self.registry.paths)
        activated = False
        try:
            if prepared.plugin_id in snapshot.state.plugins:
                raise PluginLifecycleError(
                    f"plugin {prepared.plugin_id!r} is already installed; use plugin update instead"
                )
            manifest = await self._discover_manifest(prepared)
            compatibility = check_manifest_compatibility(
                manifest,
                sereto_version=self.registry.sereto_version,
            )
            activated_at = datetime.now(UTC)
            record = PluginRecord(
                plugin_id=prepared.plugin_id,
                distribution=DistributionIdentity(
                    name=prepared.distribution_name,
                    version=prepared.distribution_version,
                ),
                entry_point=prepared.entry_point,
                source=prepared.source,
                runtime=RuntimeRecord(
                    generation_id=prepared.generation_id,
                    environment_path=prepared.environment_path,
                    python_path=prepared.python_path,
                    python_version=prepared.python_version,
                    uv_version=prepared.uv_version,
                    lock_digest=prepared.lock_digest,
                ),
                sdk_package_version=prepared.sdk_package_version,
                sdk_api_major=prepared.sdk_api_major,
                supported_protocol_versions=prepared.supported_protocol_versions,
                selected_protocol_version=compatibility.selected_protocol_version,
                manifest=manifest,
                manifest_digest=manifest_digest(manifest),
                health="healthy",
                installed_at=activated_at,
                checked_at=activated_at,
            )
            plugins = dict(snapshot.state.plugins)
            plugins[record.plugin_id] = record
            self.registry.replace(
                RegistryState(plugins=plugins),
                expected_digest=snapshot.digest,
            )
            activated = True
            return record
        finally:
            if not activated and not self._generation_is_active(prepared):
                shutil.rmtree(prepared.generation_path, ignore_errors=True)
                self._remove_empty_parents(prepared.plugin_id)

    def snapshot(self) -> RegistrySnapshot:
        """Return the current validated registry snapshot without mutation."""
        return self.registry.load()

    def list_plugins(self) -> tuple[PluginRecord, ...]:
        """Return valid installed plugins ordered by normalized plugin ID."""
        snapshot = self.registry.load()
        return tuple(snapshot.state.plugins[plugin_id] for plugin_id in sorted(snapshot.state.plugins))

    def show(self, plugin_id: str) -> PluginRecord:
        """Return one valid installed plugin record."""
        self.registry.paths.plugin_dir(plugin_id)
        snapshot = self.registry.load()
        try:
            return snapshot.state.plugins[plugin_id]
        except KeyError:
            if any(issue.plugin_id == plugin_id for issue in snapshot.issues):
                raise PluginLifecycleError(
                    f"package plugin record is invalid or incompatible: {plugin_id!r}; run plugin doctor"
                ) from None
            raise PluginLifecycleError(f"package plugin is not installed: {plugin_id!r}") from None

    def remove(self, plugin_id: str) -> PluginRecord | None:
        """Deactivate one plugin atomically, then remove its managed files."""
        with self.registry.locked_lifecycle():
            return self._remove_locked(plugin_id)

    def _remove_locked(self, plugin_id: str) -> PluginRecord | None:
        plugin_directory = self.registry.paths.plugin_dir(plugin_id)
        snapshot = self.registry.load()
        record = snapshot.state.plugins.get(plugin_id)
        if record is None and not any(issue.plugin_id == plugin_id for issue in snapshot.issues):
            raise PluginLifecycleError(f"package plugin is not installed: {plugin_id!r}")
        if snapshot.digest is None:
            raise PluginLifecycleError(f"package plugin is not installed: {plugin_id!r}")
        if plugin_directory.is_symlink() or plugin_directory.exists() and not plugin_directory.is_dir():
            raise PluginLifecycleError(f"managed package-plugin path is unsafe: {plugin_directory}")

        self.registry.remove(plugin_id, expected_digest=snapshot.digest)
        try:
            shutil.rmtree(plugin_directory)
        except FileNotFoundError:
            pass
        except OSError as error:
            raise PluginLifecycleError(
                f"package plugin {plugin_id!r} was deactivated, but its managed files could not be removed: {error}"
            ) from error
        return record

    def doctor(self) -> tuple[RegistryIssue, ...]:
        """Return static registry and active-environment diagnostics."""
        if not self.registry.paths.root.exists():
            return self.registry.doctor()
        with self.registry.locked_lifecycle():
            issues = list(self.registry.doctor())
            snapshot = self.registry.load()
            known_plugin_ids = set(snapshot.state.plugins) | {issue.plugin_id for issue in snapshot.issues}
            for path in self.registry.paths.root.iterdir():
                if path.name.startswith(".plugin-source-"):
                    issues.append(
                        RegistryIssue(
                            plugin_id=path.name,
                            code="orphaned-candidate",
                            message=f"orphaned plugin source candidate: {path}",
                        )
                    )
                elif path.is_dir() and path.name not in known_plugin_ids:
                    issues.append(
                        RegistryIssue(
                            plugin_id=path.name,
                            code="orphaned-plugin",
                            message=f"orphaned managed plugin directory: {path}",
                        )
                    )

            for plugin_id, record in snapshot.state.plugins.items():
                generations_path = self.registry.paths.generations_dir(plugin_id)
                if not generations_path.is_dir():
                    continue
                for generation_path in generations_path.iterdir():
                    if generation_path.name != record.runtime.generation_id:
                        issues.append(
                            RegistryIssue(
                                plugin_id=plugin_id,
                                code="orphaned-generation",
                                message=f"inactive plugin generation: {generation_path}",
                            )
                        )
            return tuple(issues)

    def package_manager_version(self) -> str:
        """Return the package-manager version used for lifecycle operations."""
        return self.package_manager.version()

    def _remove_empty_parents(self, plugin_id: str) -> None:
        for path in (
            self.registry.paths.generations_dir(plugin_id),
            self.registry.paths.plugin_dir(plugin_id),
        ):
            with suppress(OSError):
                path.rmdir()

    def _generation_is_active(self, prepared: PreparedPluginEnvironment) -> bool:
        try:
            record = self.registry.load().state.plugins.get(prepared.plugin_id)
        except SeretoRuntimeError:
            return False
        return record is not None and record.runtime.generation_id == prepared.generation_id

    async def _discover_with_session(self, prepared: PreparedPluginEnvironment) -> Manifest:
        session = PluginSession(
            launch=PluginLaunch(
                python=prepared.python_path,
                distribution_name=prepared.distribution_name,
                distribution_version=prepared.distribution_version,
                entry_point=prepared.entry_point,
                expected_plugin_id=prepared.plugin_id,
                sdk_api_major=prepared.sdk_api_major,
            ),
            sereto_version=self.registry.sereto_version,
            limits=SessionLimits(invocation_timeout_seconds=MANIFEST_DISCOVERY_TIMEOUT_SECONDS),
        )
        return await session.discover_manifest()
