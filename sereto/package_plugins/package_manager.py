import configparser
import errno
import hashlib
import ipaddress
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import uuid
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default as default_email_policy
from pathlib import Path
from typing import Literal, cast
from urllib.parse import parse_qsl, urlsplit

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name, parse_sdist_filename, parse_wheel_filename
from packaging.version import InvalidVersion, Version

from sereto.exceptions import SeretoRuntimeError
from sereto.package_plugins.lifecycle import PluginInstallRequest, PreparedPluginEnvironment
from sereto.package_plugins.manifest import SourceProvenance
from sereto.package_plugins.paths import PluginPaths

_INDEX_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_ARCHIVE_SUFFIXES = (".whl", ".tar.gz", ".zip", ".tar.bz2", ".tar.xz", ".tar.zst", ".tgz")
_MAX_METADATA_BYTES = 1024 * 1024
_MAX_DISTRIBUTIONS = 4096
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


class PluginPackageManagerError(SeretoRuntimeError):
    """uv could not prepare a trustworthy managed plugin environment."""


class _EntryPointConfigParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


@dataclass(frozen=True)
class _SourcePlan:
    distribution_name: str
    install_requirement: str
    provenance_requirement: str
    kind: Literal["index", "artifact", "vcs"]
    origin: str | None = None
    artifact_sha256: str | None = None


class UvPackageManager:
    """Create reproducible per-plugin environments with uv."""

    def __init__(
        self,
        uv_executable: str = "uv",
        python_executable: Path | None = None,
        command_timeout_seconds: float = 10 * 60.0,
    ) -> None:
        self.uv_executable = uv_executable
        self.python_executable = (python_executable or Path(sys.executable)).resolve()
        self.command_timeout_seconds = command_timeout_seconds

    def prepare(
        self,
        request: PluginInstallRequest,
        paths: PluginPaths,
    ) -> PreparedPluginEnvironment:
        self._validate_request(request)
        self._prepare_private_directory(paths.root)
        uv_version = self._uv_version()

        generation_path: Path | None = None
        plugin_id: str | None = None
        with tempfile.TemporaryDirectory(prefix=".plugin-source-", dir=paths.root) as raw_build_directory:
            build_directory = Path(raw_build_directory)
            try:
                source_plan = self._plan_source(request.source, build_directory, request=request)
                plugin_id = str(canonicalize_name(source_plan.distribution_name))
                if request.source_index is not None and source_plan.kind != "index":
                    raise PluginPackageManagerError("plugin source index can only pin a registry requirement")
                plugin_directory = paths.plugin_dir(plugin_id)
                self._prepare_private_directory(plugin_directory)
                self._prepare_private_directory(paths.generations_dir(plugin_id))

                generation_id = f"generation-{uuid.uuid4().hex}"
                generation_path = paths.generation_dir(plugin_id, generation_id)
                generation_path.mkdir(mode=0o700)
                self._make_private(generation_path, directory=True)

                source_plan = self._retain_local_artifact(source_plan, generation_path)
                self._write_project(generation_path, plugin_id, source_plan.install_requirement, request)
                uv_config_path = generation_path / "uv.toml"
                environment_path = generation_path / "environment"
                resolver_environment = self._command_environment(
                    environment_path,
                    credential_index_names=(
                        *(index.name for index in request.indexes),
                        *(("sereto-default",) if request.default_index is not None else ()),
                    ),
                )
                self._run_uv(
                    [
                        "lock",
                        "--project",
                        str(generation_path),
                        "--python",
                        str(self.python_executable),
                        "--no-python-downloads",
                        "--config-file",
                        str(uv_config_path),
                        "--index-strategy",
                        "first-index",
                        "--keyring-provider",
                        request.keyring_provider,
                    ],
                    environment=resolver_environment,
                    phase="resolve plugin dependencies",
                )
                lock_path = generation_path / "uv.lock"
                lock_content = lock_path.read_bytes()
                self._make_private(lock_path)
                locked_package = self._locked_package(lock_content, plugin_id)
                source = self._source_provenance(source_plan, locked_package, request)

                self._run_uv(
                    [
                        "sync",
                        "--project",
                        str(generation_path),
                        "--python",
                        str(self.python_executable),
                        "--no-python-downloads",
                        "--config-file",
                        str(uv_config_path),
                        "--locked",
                        "--no-editable",
                        "--link-mode",
                        "copy",
                        "--index-strategy",
                        "first-index",
                        "--keyring-provider",
                        request.keyring_provider,
                    ],
                    environment=resolver_environment,
                    phase="install plugin environment",
                )
                python_path = self._environment_python(environment_path)
                self._run_uv(
                    ["pip", "check", "--python", str(python_path), "--no-config"],
                    environment=self._command_environment(environment_path),
                    phase="check plugin dependencies",
                )
                metadata = self._inspect_environment(environment_path, source_plan.distribution_name)
                entry_point = self._validate_metadata(metadata, plugin_id)
                return PreparedPluginEnvironment(
                    plugin_id=plugin_id,
                    distribution_name=cast(str, metadata["distribution_name"]),
                    distribution_version=cast(str, metadata["distribution_version"]),
                    entry_point=entry_point,
                    generation_id=generation_id,
                    generation_path=generation_path,
                    environment_path=environment_path,
                    python_path=python_path,
                    python_version=cast(str, metadata["python_version"]),
                    uv_version=uv_version,
                    lock_digest=hashlib.sha256(lock_content).hexdigest(),
                    sdk_package_version=cast(str, metadata["sdk_package_version"]),
                    sdk_api_major=1,
                    supported_protocol_versions=(1,),
                    source=source,
                )
            except BaseException:
                if generation_path is not None:
                    shutil.rmtree(generation_path, ignore_errors=True)
                if plugin_id is not None:
                    self._remove_empty_parents(paths, plugin_id)
                raise

    def version(self) -> str:
        """Return the available uv version or raise a lifecycle-safe error."""
        return self._uv_version()

    def _plan_source(
        self,
        source: str,
        build_directory: Path,
        request: PluginInstallRequest | None = None,
    ) -> _SourcePlan:
        if not source or any(ord(character) < 32 or ord(character) == 127 for character in source):
            raise PluginPackageManagerError("plugin source must be non-empty and contain no control characters")

        local_path = Path(source).expanduser()
        if local_path.exists():
            resolved_path = local_path.resolve()
            if resolved_path.is_dir():
                if request is not None and request.source_index is not None:
                    raise PluginPackageManagerError(
                        "plugin source index cannot be used with a local package directory"
                    )
                artifacts = build_directory / "artifacts"
                artifacts.mkdir()
                build_arguments = [
                    "build",
                    "--wheel",
                    "--out-dir",
                    str(artifacts),
                    "--python",
                    str(self.python_executable),
                    "--no-python-downloads",
                    "--no-config",
                    "--index-strategy",
                    "first-index",
                ]
                credential_index_names: tuple[str, ...] = ()
                if request is not None:
                    for index in request.indexes:
                        build_arguments.extend(("--index", f"{index.name}={index.url}"))
                    if request.default_index is not None:
                        build_arguments.extend(("--default-index", f"sereto-default={request.default_index}"))
                    build_arguments.extend(("--keyring-provider", request.keyring_provider))
                    credential_index_names = (
                        *(index.name for index in request.indexes),
                        *(("sereto-default",) if request.default_index is not None else ()),
                    )
                build_arguments.append(str(resolved_path))
                self._run_uv(
                    build_arguments,
                    environment=self._command_environment(credential_index_names=credential_index_names),
                    phase="build local plugin source",
                )
                wheels = tuple(artifacts.glob("*.whl"))
                if len(wheels) != 1:
                    raise PluginPackageManagerError("local plugin source must build exactly one wheel")
                artifact_path = wheels[0]
            elif resolved_path.is_file() and resolved_path.name.endswith(_ARCHIVE_SUFFIXES):
                artifact_path = resolved_path
            else:
                raise PluginPackageManagerError("local plugin source must be a package directory, wheel, or sdist")
            distribution_name = self._archive_distribution_name(artifact_path)
            return _SourcePlan(
                distribution_name=distribution_name,
                install_requirement=str(artifact_path),
                provenance_requirement=f"{distribution_name} @ {resolved_path.as_uri()}",
                kind="artifact",
                origin=resolved_path.as_uri(),
                artifact_sha256=self._file_digest(artifact_path),
            )

        try:
            requirement = Requirement(source)
        except InvalidRequirement as error:
            if self._looks_like_path(source) and "://" not in source:
                raise PluginPackageManagerError("local plugin source does not exist") from error
            raise PluginPackageManagerError(
                "plugin source must be a PEP 508 requirement or local package path"
            ) from error
        if requirement.marker is not None:
            raise PluginPackageManagerError("plugin source requirement must not contain an environment marker")
        normalized_requirement = str(requirement)
        if requirement.url is None:
            return _SourcePlan(
                distribution_name=requirement.name,
                install_requirement=normalized_requirement,
                provenance_requirement=normalized_requirement,
                kind="index",
            )

        self._validate_source_url(requirement.url, "plugin source")
        kind: Literal["artifact", "vcs"] = "vcs" if requirement.url.startswith("git+") else "artifact"
        return _SourcePlan(
            distribution_name=requirement.name,
            install_requirement=normalized_requirement,
            provenance_requirement=normalized_requirement,
            kind=kind,
            origin=requirement.url,
        )

    def _retain_local_artifact(self, plan: _SourcePlan, generation_path: Path) -> _SourcePlan:
        source_path = Path(plan.install_requirement)
        if plan.kind != "artifact" or not source_path.is_file():
            return plan
        artifacts = generation_path / "artifacts"
        artifacts.mkdir(mode=0o700)
        self._make_private(artifacts, directory=True)
        destination = artifacts / source_path.name
        shutil.copyfile(source_path, destination)
        self._make_private(destination)
        retained_digest = self._file_digest(destination)
        return _SourcePlan(
            distribution_name=plan.distribution_name,
            install_requirement=f"{plan.distribution_name} @ {destination.as_uri()}",
            provenance_requirement=plan.provenance_requirement,
            kind=plan.kind,
            origin=plan.origin,
            artifact_sha256=retained_digest,
        )

    def _write_project(
        self,
        generation_path: Path,
        plugin_id: str,
        requirement: str,
        request: PluginInstallRequest,
    ) -> None:
        document = tomlkit.document()
        project = tomlkit.table()
        project["name"] = "sereto-managed-plugin-environment"
        project["version"] = "0"
        project["requires-python"] = f"=={sys.version_info.major}.{sys.version_info.minor}.*"
        project["dependencies"] = [requirement]
        document["project"] = project

        tool = tomlkit.table()
        uv = tomlkit.table()
        uv["package"] = False
        if request.source_index is not None:
            sources = tomlkit.table()
            source = tomlkit.inline_table()
            source["index"] = request.source_index
            sources[plugin_id] = source
            uv["sources"] = sources

        indexes = tomlkit.aot()
        for configured_index in request.indexes:
            index = tomlkit.table()
            index["name"] = configured_index.name
            index["url"] = configured_index.url
            if configured_index.name == request.source_index:
                index["explicit"] = True
            indexes.append(index)
        if request.default_index is not None:
            index = tomlkit.table()
            index["name"] = "sereto-default"
            index["url"] = request.default_index
            index["default"] = True
            indexes.append(index)
        if indexes:
            uv["index"] = indexes
        tool["uv"] = uv
        document["tool"] = tool
        project_path = generation_path / "pyproject.toml"
        project_path.write_text(tomlkit.dumps(document), encoding="utf-8")
        self._make_private(project_path)

        config_path = generation_path / "uv.toml"
        config_path.write_text("", encoding="utf-8")
        self._make_private(config_path)

    def _source_provenance(
        self,
        plan: _SourcePlan,
        locked_package: Mapping[str, object],
        request: PluginInstallRequest,
    ) -> SourceProvenance:
        source = locked_package.get("source")
        if not isinstance(source, dict):
            raise PluginPackageManagerError("uv lock does not identify the plugin package source")
        if plan.kind == "index":
            registry_url = source.get("registry")
            if not isinstance(registry_url, str):
                raise PluginPackageManagerError("uv lock does not identify the plugin package index")
            return SourceProvenance(
                kind="index",
                requirement=plan.provenance_requirement,
                origin=registry_url,
                index_name=self._index_name(registry_url, request),
            )
        if plan.kind == "vcs":
            locked_git = source.get("git")
            if not isinstance(locked_git, str) or "#" not in locked_git:
                raise PluginPackageManagerError("uv lock does not contain a resolved plugin VCS commit")
            commit = locked_git.rsplit("#", 1)[1]
            if not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
                raise PluginPackageManagerError("uv lock contains an invalid resolved plugin VCS commit")
            return SourceProvenance(
                kind="vcs",
                requirement=plan.provenance_requirement,
                origin=cast(str, plan.origin),
                vcs_commit=commit.lower(),
            )

        artifact_digest = plan.artifact_sha256 or self._locked_artifact_digest(locked_package)
        if artifact_digest is None:
            raise PluginPackageManagerError("uv lock does not contain a SHA-256 plugin artifact hash")
        return SourceProvenance(
            kind="artifact",
            requirement=plan.provenance_requirement,
            origin=cast(str, plan.origin),
            artifact_sha256=artifact_digest,
        )

    def _inspect_environment(self, environment_path: Path, distribution_name: str) -> dict[str, object]:
        site_packages = self._site_packages(environment_path)
        distributions = tuple(site_packages.glob("*.dist-info"))
        if len(distributions) > _MAX_DISTRIBUTIONS:
            raise PluginPackageManagerError("plugin environment contains too many distributions")

        plugin_metadata = self._find_distribution(distributions, distribution_name)
        sdk_metadata = self._find_distribution(distributions, "sereto-sdk")
        entry_points = self._read_entry_points(plugin_metadata["path"])
        environment_config = self._read_key_value_file(environment_path / "pyvenv.cfg")
        python_version = environment_config.get("version_info")
        if environment_config.get("implementation") != "CPython" or python_version is None:
            raise PluginPackageManagerError("plugin environment has invalid Python metadata")
        return {
            "distribution_name": plugin_metadata["name"],
            "distribution_version": plugin_metadata["version"],
            "entry_points": entry_points,
            "python_version": python_version,
            "sdk_package_version": sdk_metadata["version"],
        }

    @classmethod
    def _find_distribution(
        cls,
        distributions: Sequence[Path],
        distribution_name: str,
    ) -> dict[str, str | Path]:
        normalized_name = str(canonicalize_name(distribution_name))
        matches: list[dict[str, str | Path]] = []
        for metadata_path in distributions:
            metadata_escapes = not metadata_path.resolve().is_relative_to(metadata_path.parent.resolve())
            if metadata_path.is_symlink() or metadata_escapes:
                raise PluginPackageManagerError("installed distribution metadata escapes site-packages")
            content = cls._read_bounded_file(metadata_path / "METADATA")
            metadata = BytesParser(policy=default_email_policy).parsebytes(content)
            name = metadata.get("Name")
            version = metadata.get("Version")
            if not isinstance(name, str) or not isinstance(version, str):
                raise PluginPackageManagerError("installed distribution metadata is incomplete")
            if str(canonicalize_name(name)) == normalized_name:
                matches.append({"name": name, "version": version, "path": metadata_path})
        if len(matches) != 1:
            raise PluginPackageManagerError(
                f"plugin environment must contain exactly one {normalized_name!r} distribution"
            )
        return matches[0]

    @classmethod
    def _read_entry_points(cls, metadata_path: str | Path) -> list[dict[str, str]]:
        path = Path(metadata_path) / "entry_points.txt"
        if not path.exists():
            return []
        try:
            content = cls._read_bounded_file(path).decode("utf-8")
            parser = _EntryPointConfigParser(interpolation=None, strict=True)
            parser.read_string(content)
        except (UnicodeDecodeError, configparser.Error) as error:
            raise PluginPackageManagerError("installed plugin entry-point metadata is invalid") from error
        return [
            {"group": group, "name": name}
            for group in parser.sections()
            if group.startswith("sereto.plugins.")
            for name, _ in parser.items(group)
        ]

    @classmethod
    def _read_key_value_file(cls, path: Path) -> dict[str, str]:
        try:
            content = cls._read_bounded_file(path).decode("utf-8")
        except UnicodeDecodeError as error:
            raise PluginPackageManagerError("plugin environment metadata is not UTF-8") from error
        values: dict[str, str] = {}
        for line in content.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key.strip()] = value.strip()
        return values

    @staticmethod
    def _site_packages(environment_path: Path) -> Path:
        candidates: tuple[Path, ...]
        if os.name == "nt":
            candidates = (environment_path / "Lib" / "site-packages",)
        else:
            candidates = tuple(
                candidate
                for library_directory in (environment_path / "lib", environment_path / "lib64")
                for candidate in library_directory.glob("python*/site-packages")
            )
        resolved_environment = environment_path.resolve()
        resolved_candidates = {
            candidate.resolve()
            for candidate in candidates
            if candidate.is_dir() and candidate.resolve().is_relative_to(resolved_environment)
        }
        if len(resolved_candidates) != 1:
            raise PluginPackageManagerError("plugin environment has an invalid site-packages layout")
        return resolved_candidates.pop()

    @staticmethod
    def _read_bounded_file(path: Path) -> bytes:
        if path.is_symlink():
            raise PluginPackageManagerError(f"installed metadata must not be a symbolic link: {path.name}")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise PluginPackageManagerError(
                    f"installed metadata must not be a symbolic link: {path.name}"
                ) from error
            raise PluginPackageManagerError(f"cannot read installed metadata: {path.name}") from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_METADATA_BYTES:
                raise PluginPackageManagerError(f"installed metadata file is invalid: {path.name}")
            with os.fdopen(descriptor, "rb") as metadata_file:
                descriptor = -1
                content = metadata_file.read(_MAX_METADATA_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if len(content) > _MAX_METADATA_BYTES:
            raise PluginPackageManagerError(f"installed metadata file is invalid: {path.name}")
        return content

    @staticmethod
    def _validate_metadata(metadata: Mapping[str, object], plugin_id: str) -> str:
        required_strings = (
            "distribution_name",
            "distribution_version",
            "python_version",
            "sdk_package_version",
        )
        if any(not isinstance(metadata.get(field), str) or not metadata[field] for field in required_strings):
            raise PluginPackageManagerError("installed plugin metadata is incomplete")
        if str(canonicalize_name(cast(str, metadata["distribution_name"]))) != plugin_id:
            raise PluginPackageManagerError("installed distribution identity does not match the requested plugin")
        for field in ("distribution_version", "python_version", "sdk_package_version"):
            try:
                Version(cast(str, metadata[field]))
            except InvalidVersion as error:
                message = f"installed plugin reports an invalid {field.replace('_', ' ')}"
                raise PluginPackageManagerError(message) from error
        python_version = Version(cast(str, metadata["python_version"]))
        if python_version.release[:2] != sys.version_info[:2]:
            raise PluginPackageManagerError("plugin environment Python does not match the host major and minor")
        entry_points = metadata.get("entry_points")
        if not isinstance(entry_points, list):
            raise PluginPackageManagerError("installed plugin entry-point metadata is invalid")
        matching = [
            entry_point
            for entry_point in entry_points
            if isinstance(entry_point, dict)
            and entry_point.get("group") == "sereto.plugins.v1"
            and entry_point.get("name") == plugin_id
        ]
        if len(matching) != 1 or len(entry_points) != 1:
            raise PluginPackageManagerError(
                f"plugin distribution must provide exactly one 'sereto.plugins.v1' entry point named {plugin_id!r}"
            )
        return plugin_id

    def _uv_version(self) -> str:
        completed = self._run(
            [self.uv_executable, "--version"],
            environment=self._command_environment(),
            phase="locate uv",
            timeout_seconds=10.0,
        )
        match = re.fullmatch(r"uv\s+([^\s]+)(?:\s+.*)?", completed.stdout.strip())
        if match is None:
            raise PluginPackageManagerError("uv returned an invalid version response")
        try:
            Version(match.group(1))
        except InvalidVersion as error:
            raise PluginPackageManagerError("uv returned an invalid version response") from error
        return match.group(1)

    def _run_uv(
        self,
        arguments: Sequence[str],
        *,
        environment: Mapping[str, str],
        phase: str,
    ) -> subprocess.CompletedProcess[str]:
        return self._run(
            [self.uv_executable, *arguments],
            environment=environment,
            phase=phase,
            timeout_seconds=self.command_timeout_seconds,
        )

    @staticmethod
    def _command_environment(
        environment_path: Path | None = None,
        *,
        credential_index_names: Sequence[str] = (),
    ) -> dict[str, str]:
        allowed_credentials = {
            f"UV_INDEX_{re.sub(r'[^A-Za-z0-9]', '_', name).upper()}_{field}"
            for name in credential_index_names
            for field in ("USERNAME", "PASSWORD")
        }
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("UV_") or key in allowed_credentials
        }
        environment.pop("VIRTUAL_ENV", None)
        environment["NO_COLOR"] = "1"
        environment["UV_NO_PROGRESS"] = "1"
        environment["UV_NO_WRAP"] = "1"
        if environment_path is not None:
            environment["UV_PROJECT_ENVIRONMENT"] = str(environment_path)
        return environment

    @staticmethod
    def _run(
        command: Sequence[str],
        *,
        environment: Mapping[str, str],
        phase: str,
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except FileNotFoundError:
            raise PluginPackageManagerError(f"cannot {phase}: executable {command[0]!r} was not found") from None
        except subprocess.TimeoutExpired:
            raise PluginPackageManagerError(f"timed out while attempting to {phase}") from None
        except subprocess.CalledProcessError as error:
            raise PluginPackageManagerError(f"cannot {phase}") from error

    @staticmethod
    def _locked_package(content: bytes, plugin_id: str) -> dict[str, object]:
        try:
            document = tomllib.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise PluginPackageManagerError("uv produced an invalid lockfile") from error
        packages = document.get("package")
        if not isinstance(packages, list):
            raise PluginPackageManagerError("uv lock does not contain package records")
        matching = [
            package
            for package in packages
            if isinstance(package, dict)
            and isinstance(package.get("name"), str)
            and str(canonicalize_name(package["name"])) == plugin_id
        ]
        if len(matching) != 1:
            raise PluginPackageManagerError("uv lock must contain exactly one plugin distribution record")
        return cast(dict[str, object], matching[0])

    @staticmethod
    def _locked_artifact_digest(package: Mapping[str, object]) -> str | None:
        artifacts: list[object] = []
        if "sdist" in package:
            artifacts.append(package["sdist"])
        wheels = package.get("wheels")
        if isinstance(wheels, list):
            artifacts.extend(wheels)
        hashes = {
            artifact["hash"].removeprefix("sha256:")
            for artifact in artifacts
            if isinstance(artifact, dict)
            and isinstance(artifact.get("hash"), str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["hash"])
        }
        return next(iter(hashes)) if len(hashes) == 1 else None

    @staticmethod
    def _archive_distribution_name(path: Path) -> str:
        try:
            if path.suffix == ".whl":
                name, _, _, _ = parse_wheel_filename(path.name)
            else:
                name, _ = parse_sdist_filename(path.name)
        except (InvalidVersion, ValueError) as error:
            raise PluginPackageManagerError(f"cannot determine distribution name from {path.name!r}") from error
        return str(name)

    @staticmethod
    def _file_digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source_file:
            for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _environment_python(environment_path: Path) -> Path:
        if os.name == "nt":
            return environment_path / "Scripts" / "python.exe"
        return environment_path / "bin" / "python"

    @staticmethod
    def _looks_like_path(source: str) -> bool:
        return (
            source.startswith((".", "~", os.sep))
            or os.altsep is not None
            and source.startswith(os.altsep)
            or any(separator in source for separator in (os.sep, os.altsep) if separator is not None)
            or source.endswith(_ARCHIVE_SUFFIXES)
        )

    @classmethod
    def _validate_request(cls, request: PluginInstallRequest) -> None:
        if request.keyring_provider not in ("disabled", "subprocess"):
            raise PluginPackageManagerError("unsupported uv keyring provider")
        names: set[str] = set()
        credential_names: set[str] = set()
        for index in request.indexes:
            if not _INDEX_NAME.fullmatch(index.name):
                raise PluginPackageManagerError(f"invalid plugin index name: {index.name!r}")
            if index.name == "sereto-default" or index.name in names:
                raise PluginPackageManagerError(f"duplicate or reserved plugin index name: {index.name!r}")
            credential_name = re.sub(r"[^A-Za-z0-9]", "_", index.name).upper()
            if credential_name == "SERETO_DEFAULT" or credential_name in credential_names:
                raise PluginPackageManagerError("plugin index names have ambiguous credential environment variables")
            cls._validate_index_url(index.url)
            names.add(index.name)
            credential_names.add(credential_name)
        if request.default_index is not None:
            cls._validate_index_url(request.default_index)
        if request.source_index is not None and request.source_index not in names:
            raise PluginPackageManagerError("plugin source index must name one of the configured indexes")

    @classmethod
    def _validate_index_url(cls, value: str) -> None:
        cls._validate_source_url(value, "plugin index")
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise PluginPackageManagerError("plugin index must be an HTTP or HTTPS URL")
        if parsed.fragment:
            raise PluginPackageManagerError("plugin index URL must not contain a fragment")
        if parsed.scheme == "http" and not cls._is_loopback(parsed.hostname):
            raise PluginPackageManagerError("plugin index must use HTTPS unless it is on loopback")

    @classmethod
    def _validate_source_url(cls, value: str, label: str) -> None:
        parsed_value = value.removeprefix("git+")
        parsed = urlsplit(parsed_value)
        allowed_schemes = {"https"}
        if value.startswith("git+"):
            allowed_schemes.add("ssh")
        if parsed.scheme == "http" and parsed.hostname is not None and cls._is_loopback(parsed.hostname):
            allowed_schemes.add("http")
        if parsed.scheme not in allowed_schemes:
            raise PluginPackageManagerError(f"{label} uses an unsupported or insecure URL scheme")
        if parsed.hostname is None:
            raise PluginPackageManagerError(f"{label} URL must include a host")
        if parsed.password is not None or parsed.scheme in ("http", "https") and parsed.username is not None:
            raise PluginPackageManagerError(f"{label} must not contain HTTP credentials")
        query_keys = {key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
        fragment_keys = {key.casefold() for key, _ in parse_qsl(parsed.fragment, keep_blank_values=True)}
        if (query_keys | fragment_keys) & _SENSITIVE_QUERY_KEYS:
            raise PluginPackageManagerError(f"{label} must not contain credential query parameters")

    @staticmethod
    def _is_loopback(hostname: str) -> bool:
        if hostname.casefold() == "localhost":
            return True
        try:
            return ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            return False

    @staticmethod
    def _index_name(registry_url: str, request: PluginInstallRequest) -> str:
        normalized_url = registry_url.rstrip("/")
        if request.source_index is not None:
            source_index = next(index for index in request.indexes if index.name == request.source_index)
            if source_index.url.rstrip("/") != normalized_url:
                raise PluginPackageManagerError("uv lock plugin index does not match the pinned source index")
            return request.source_index
        for index in request.indexes:
            if index.url.rstrip("/") == normalized_url:
                return index.name
        if request.default_index is not None and request.default_index.rstrip("/") == normalized_url:
            return "sereto-default"
        if normalized_url == "https://pypi.org/simple":
            return "pypi"
        return "unknown"

    @staticmethod
    def _prepare_private_directory(path: Path) -> None:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = path.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise PluginPackageManagerError(f"managed plugin path is not a directory: {path}")
        if path.resolve() != path:
            raise PluginPackageManagerError(f"managed plugin path must not be a symbolic link: {path}")
        if os.name != "nt" and metadata.st_uid != os.getuid():
            raise PluginPackageManagerError(f"managed plugin path must be owned by the current user: {path}")
        UvPackageManager._make_private(path, directory=True)

    @staticmethod
    def _make_private(path: Path, *, directory: bool = False) -> None:
        if os.name != "nt":
            path.chmod(0o700 if directory else 0o600)

    @staticmethod
    def _remove_empty_parents(paths: PluginPaths, plugin_id: str) -> None:
        for path in (paths.generations_dir(plugin_id), paths.plugin_dir(plugin_id)):
            with suppress(OSError):
                path.rmdir()
