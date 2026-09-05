import errno
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, NoReturn, cast

from pydantic import Field, ValidationError, field_serializer, field_validator, model_validator

from sereto.exceptions import SeretoRuntimeError
from sereto.file_transaction import ProjectFileLock
from sereto.package_plugins.compatibility import CompatibilityError
from sereto.package_plugins.manifest import PluginRecord, RegistryModel, RegistryRecordError, validate_plugin_record
from sereto.package_plugins.paths import PluginPaths
from sereto.package_plugins.protocol_v1 import VersionOne

MAX_REGISTRY_BYTES = 16 * 1024 * 1024
LIFECYCLE_LOCK_TIMEOUT_SECONDS = 15 * 60.0


class RegistryError(SeretoRuntimeError):
    """The managed package-plugin registry cannot be read or written safely."""


class RegistryConflictError(RegistryError):
    """The registry changed after the caller loaded its snapshot."""


class RegistryState(RegistryModel):
    schema_version: VersionOne = 1
    plugins: Mapping[str, PluginRecord] = Field(default_factory=dict)

    @field_validator("plugins", mode="after")
    @classmethod
    def freeze_plugins(cls, value: Mapping[str, PluginRecord]) -> Mapping[str, PluginRecord]:
        return MappingProxyType(dict(value))

    @field_serializer("plugins")
    def serialize_plugins(self, value: Mapping[str, PluginRecord]) -> dict[str, PluginRecord]:
        return dict(value)

    @model_validator(mode="after")
    def validate_plugin_keys(self) -> "RegistryState":
        for plugin_id, record in self.plugins.items():
            if plugin_id != record.plugin_id:
                raise ValueError(f"registry key {plugin_id!r} does not match plugin ID {record.plugin_id!r}")
        return self


@dataclass(frozen=True)
class RegistryIssue:
    plugin_id: str
    code: Literal[
        "invalid-record",
        "incompatible-record",
        "unhealthy-record",
        "missing-environment",
        "missing-python",
        "orphaned-candidate",
        "orphaned-plugin",
        "orphaned-generation",
    ]
    message: str


@dataclass(frozen=True)
class RegistrySnapshot:
    state: RegistryState
    digest: str | None
    issues: tuple[RegistryIssue, ...]


class PluginRegistry:
    """Read and atomically replace the host's cached package-plugin registry."""

    def __init__(self, paths: PluginPaths, sereto_version: str) -> None:
        self.paths = paths
        self.sereto_version = sereto_version

    def load(self) -> RegistrySnapshot:
        """Load valid records without creating registry state or running plugin code."""
        content = self._read_registry_bytes()
        if content is None:
            return RegistrySnapshot(state=RegistryState(), digest=None, issues=())
        return self._load_content(content)

    @contextmanager
    def locked_lifecycle(self) -> Generator[None]:
        """Serialize managed environment and registry mutations across processes."""
        self._prepare_root()
        with ProjectFileLock(self.paths.lifecycle_lock, timeout=LIFECYCLE_LOCK_TIMEOUT_SECONDS):
            if os.name != "nt":
                self.paths.lifecycle_lock.chmod(0o600)
            yield

    def _load_content(self, content: bytes) -> RegistrySnapshot:
        digest = hashlib.sha256(content).hexdigest()
        raw_plugins = self._decode_document(content)
        records: dict[str, PluginRecord] = {}
        issues: list[RegistryIssue] = []
        for plugin_id, raw_record in raw_plugins.items():
            try:
                record = PluginRecord.model_validate(raw_record)
                validate_plugin_record(plugin_id, record, self.paths, self.sereto_version)
            except CompatibilityError as error:
                issues.append(
                    RegistryIssue(
                        plugin_id=plugin_id,
                        code="incompatible-record",
                        message=str(error),
                    )
                )
            except ValidationError as error:
                issues.append(
                    RegistryIssue(
                        plugin_id=plugin_id,
                        code="invalid-record",
                        message=self._format_validation_error(error),
                    )
                )
            except (RegistryRecordError, ValueError, TypeError) as error:
                issues.append(
                    RegistryIssue(
                        plugin_id=plugin_id,
                        code="invalid-record",
                        message=str(error),
                    )
                )
            else:
                records[plugin_id] = record
        return RegistrySnapshot(
            state=RegistryState(plugins=records),
            digest=digest,
            issues=tuple(issues),
        )

    def replace(
        self,
        state: RegistryState,
        expected_digest: str | None,
        *,
        allow_repair: bool = False,
    ) -> RegistrySnapshot:
        """Atomically replace registry state when its current digest matches."""
        validated_state = RegistryState.model_validate(state.model_dump(mode="python"))
        for plugin_id, record in validated_state.plugins.items():
            validate_plugin_record(plugin_id, record, self.paths, self.sereto_version)

        content = json.dumps(
            validated_state.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(content) > MAX_REGISTRY_BYTES:
            raise RegistryError(f"plugin registry exceeds {MAX_REGISTRY_BYTES} bytes")

        self._prepare_root()
        with ProjectFileLock(self.paths.registry_lock):
            if os.name != "nt":
                self.paths.registry_lock.chmod(0o600)
            current = self._read_registry_bytes()
            current_digest = hashlib.sha256(current).hexdigest() if current is not None else None
            if current_digest != expected_digest:
                raise RegistryConflictError("plugin registry changed after it was loaded")
            if current is not None and not allow_repair and self._load_content(current).issues:
                raise RegistryError("plugin registry contains invalid or incompatible records; repair is required")
            try:
                self._atomic_write(content)
            except OSError as error:
                raise RegistryError(f"cannot replace plugin registry: {error}") from error

        return RegistrySnapshot(
            state=validated_state,
            digest=hashlib.sha256(content).hexdigest(),
            issues=(),
        )

    def remove(self, plugin_id: str, expected_digest: str) -> RegistrySnapshot:
        """Atomically remove one raw registry record without dropping unrelated invalid records."""
        self._prepare_root()
        with ProjectFileLock(self.paths.registry_lock):
            if os.name != "nt":
                self.paths.registry_lock.chmod(0o600)
            current = self._read_registry_bytes()
            if current is None or hashlib.sha256(current).hexdigest() != expected_digest:
                raise RegistryConflictError("plugin registry changed after it was loaded")
            raw_plugins = self._decode_document(current)
            if plugin_id not in raw_plugins:
                raise RegistryError(f"package plugin is not installed: {plugin_id!r}")
            del raw_plugins[plugin_id]
            content = json.dumps(
                {"schema_version": 1, "plugins": raw_plugins},
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            try:
                self._atomic_write(content)
            except OSError as error:
                raise RegistryError(f"cannot replace plugin registry: {error}") from error
        return self._load_content(content)

    def doctor(self) -> tuple[RegistryIssue, ...]:
        """Return static cached-record and runtime-path diagnostics without mutation."""
        snapshot = self.load()
        issues = list(snapshot.issues)
        for plugin_id, record in snapshot.state.plugins.items():
            if record.health != "healthy":
                issues.append(
                    RegistryIssue(
                        plugin_id=plugin_id,
                        code="unhealthy-record",
                        message=record.health_message or "plugin record is marked unhealthy",
                    )
                )
            if not record.runtime.environment_path.is_dir():
                issues.append(
                    RegistryIssue(
                        plugin_id=plugin_id,
                        code="missing-environment",
                        message=f"plugin environment does not exist: {record.runtime.environment_path}",
                    )
                )
            if not record.runtime.python_path.is_file():
                issues.append(
                    RegistryIssue(
                        plugin_id=plugin_id,
                        code="missing-python",
                        message=f"plugin Python does not exist: {record.runtime.python_path}",
                    )
                )
        return tuple(issues)

    def _read_registry_bytes(self) -> bytes | None:
        path = self.paths.registry_file
        if path.is_symlink():
            raise RegistryError("plugin registry must not be a symbolic link")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_BINARY", 0)
        try:
            opened_descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise RegistryError("plugin registry must not be a symbolic link") from error
            raise RegistryError(f"cannot open plugin registry: {error}") from error

        file_descriptor: int | None = opened_descriptor
        try:
            metadata = os.fstat(opened_descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise RegistryError("plugin registry is not a regular file")
            if os.name != "nt":
                if metadata.st_uid != os.getuid():
                    raise RegistryError("plugin registry must be owned by the current user")
                if stat.S_IMODE(metadata.st_mode) & 0o077:
                    raise RegistryError("plugin registry permissions must not allow group or other access")
            if metadata.st_size > MAX_REGISTRY_BYTES:
                raise RegistryError(f"plugin registry exceeds {MAX_REGISTRY_BYTES} bytes")
            try:
                with os.fdopen(opened_descriptor, "rb") as registry_file:
                    file_descriptor = None
                    content = registry_file.read(MAX_REGISTRY_BYTES + 1)
            except OSError as error:
                raise RegistryError(f"cannot read plugin registry: {error}") from error
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
        if len(content) > MAX_REGISTRY_BYTES:
            raise RegistryError(f"plugin registry exceeds {MAX_REGISTRY_BYTES} bytes")
        return content

    @staticmethod
    def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    @staticmethod
    def _reject_non_finite(value: str) -> NoReturn:
        raise ValueError(f"non-finite JSON number {value!r}")

    def _decode_document(self, content: bytes) -> dict[str, object]:
        try:
            decoded = json.loads(
                content,
                object_pairs_hook=self._reject_duplicate_keys,
                parse_constant=self._reject_non_finite,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise RegistryError(f"invalid plugin registry JSON: {error}") from error
        if not isinstance(decoded, dict) or set(decoded) != {"schema_version", "plugins"}:
            raise RegistryError("plugin registry must contain only schema_version and plugins")
        if type(decoded["schema_version"]) is not int or decoded["schema_version"] != 1:
            raise RegistryError(f"unsupported plugin registry schema version: {decoded['schema_version']!r}")
        raw_plugins = decoded["plugins"]
        if not isinstance(raw_plugins, dict) or not all(isinstance(key, str) for key in raw_plugins):
            raise RegistryError("plugin registry plugins must be a JSON object")
        return cast(dict[str, object], raw_plugins)

    @staticmethod
    def _format_validation_error(error: ValidationError) -> str:
        messages: list[str] = []
        for detail in error.errors(include_url=False, include_context=False, include_input=False):
            location = ".".join(str(part) for part in detail["loc"])
            messages.append(f"{location}: {detail['msg']}" if location else str(detail["msg"]))
        return "; ".join(messages)

    def _prepare_root(self) -> None:
        try:
            self.paths.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not self.paths.root.is_dir():
                raise RegistryError("plugin registry root is not a directory")
            if os.name != "nt":
                self.paths.root.chmod(0o700)
        except OSError as error:
            raise RegistryError(f"cannot prepare plugin registry root: {error}") from error

    def _atomic_write(self, content: bytes) -> None:
        descriptor, raw_path = tempfile.mkstemp(prefix=".registry-", suffix=".tmp", dir=self.paths.root)
        temporary_path = Path(raw_path)
        try:
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as registry_file:
                descriptor = -1
                registry_file.write(content)
                registry_file.flush()
                os.fsync(registry_file.fileno())
            os.replace(temporary_path, self.paths.registry_file)
            self._fsync_directory(self.paths.root)
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            temporary_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
