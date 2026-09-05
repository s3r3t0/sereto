import asyncio
import hashlib
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from sereto.package_plugins.lifecycle import (
    PluginIndex,
    PluginInstallRequest,
    PluginLifecycle,
    PluginLifecycleError,
    PreparedPluginEnvironment,
)
from sereto.package_plugins.manifest import SourceProvenance
from sereto.package_plugins.package_manager import PluginPackageManagerError, UvPackageManager
from sereto.package_plugins.paths import PluginPaths
from sereto.package_plugins.protocol_v1 import Manifest
from sereto.package_plugins.registry import PluginRegistry, RegistryConflictError, RegistryError, RegistryState


class FakePackageManager:
    def prepare(
        self,
        request: PluginInstallRequest,
        paths: PluginPaths,
    ) -> PreparedPluginEnvironment:
        generation_id = "generation-1"
        generation_path = paths.generation_dir("acme-testssl", generation_id)
        environment_path = generation_path / "environment"
        python_path = environment_path / "bin" / "python"
        python_path.parent.mkdir(parents=True)
        python_path.touch()
        lock_content = b"version = 1\n"
        (generation_path / "uv.lock").write_bytes(lock_content)
        return PreparedPluginEnvironment(
            plugin_id="acme-testssl",
            distribution_name="Acme_TestSSL",
            distribution_version="2.4.1",
            entry_point="acme-testssl",
            generation_id=generation_id,
            generation_path=generation_path,
            environment_path=environment_path,
            python_path=python_path,
            python_version="3.14.7",
            uv_version="0.12.3",
            lock_digest=hashlib.sha256(lock_content).hexdigest(),
            sdk_package_version="0.1.0",
            sdk_api_major=1,
            supported_protocol_versions=(1,),
            source=SourceProvenance(
                kind="index",
                requirement=request.source,
                origin="https://pypi.org/simple",
                index_name="pypi",
            ),
        )

    def version(self) -> str:
        return "0.12.3"


def _manifest() -> Manifest:
    return Manifest.model_validate(
        {
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
    )


def test_install_discards_candidate_when_manifest_discovery_fails(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    registry = PluginRegistry(paths=paths, sereto_version="0.9.0")

    async def fail_discovery(prepared: PreparedPluginEnvironment) -> Manifest:
        raise RuntimeError("manifest probe failed")

    lifecycle = PluginLifecycle(
        registry=registry,
        package_manager=FakePackageManager(),
        discover_manifest=fail_discovery,
    )

    with pytest.raises(RuntimeError, match="manifest probe failed"):
        asyncio.run(lifecycle.install(PluginInstallRequest(source="acme-testssl==2.4.1")))

    assert not paths.registry_file.exists()
    assert not paths.generation_dir("acme-testssl", "generation-1").exists()


def test_install_activates_valid_manifest_and_remove_deletes_managed_state(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    registry = PluginRegistry(paths=paths, sereto_version="0.9.0")

    async def discover_manifest(prepared: PreparedPluginEnvironment) -> Manifest:
        assert prepared.python_path.is_file()
        return _manifest()

    lifecycle = PluginLifecycle(
        registry=registry,
        package_manager=FakePackageManager(),
        discover_manifest=discover_manifest,
    )

    installed = asyncio.run(lifecycle.install(PluginInstallRequest(source="acme-testssl==2.4.1")))

    assert installed.plugin_id == "acme-testssl"
    assert lifecycle.list_plugins() == (installed,)
    assert lifecycle.show("acme-testssl") == installed
    assert lifecycle.package_manager_version() == "0.12.3"
    assert paths.generation_dir("acme-testssl", "generation-1").is_dir()
    if os.name != "nt":
        assert paths.lifecycle_lock.stat().st_mode & 0o777 == 0o600

    assert lifecycle.remove("acme-testssl") == installed
    assert lifecycle.list_plugins() == ()
    assert not paths.plugin_dir("acme-testssl").exists()


def test_install_discards_candidate_when_registry_changes_during_preparation(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    registry = PluginRegistry(paths=paths, sereto_version="0.9.0")

    async def discover_after_concurrent_write(prepared: PreparedPluginEnvironment) -> Manifest:
        registry.replace(RegistryState(), expected_digest=None)
        return _manifest()

    lifecycle = PluginLifecycle(
        registry=registry,
        package_manager=FakePackageManager(),
        discover_manifest=discover_after_concurrent_write,
    )

    with pytest.raises(RegistryConflictError, match="changed after it was loaded"):
        asyncio.run(lifecycle.install(PluginInstallRequest(source="acme-testssl==2.4.1")))

    assert registry.load().state.plugins == {}
    assert not paths.generation_dir("acme-testssl", "generation-1").exists()


def test_install_preserves_generation_after_post_replace_durability_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    registry = PluginRegistry(paths=paths, sereto_version="0.9.0")

    async def discover_manifest(prepared: PreparedPluginEnvironment) -> Manifest:
        return _manifest()

    def fail_directory_fsync(path: Path) -> None:
        raise OSError("injected directory fsync failure")

    monkeypatch.setattr(registry, "_fsync_directory", fail_directory_fsync)
    lifecycle = PluginLifecycle(
        registry=registry,
        package_manager=FakePackageManager(),
        discover_manifest=discover_manifest,
    )

    with pytest.raises(RegistryError, match="cannot replace plugin registry"):
        asyncio.run(lifecycle.install(PluginInstallRequest(source="acme-testssl==2.4.1")))

    active = registry.load().state.plugins["acme-testssl"]
    assert active.runtime.generation_id == "generation-1"
    assert paths.generation_dir("acme-testssl", "generation-1").is_dir()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symbolic link check")
def test_remove_rejects_symlinked_plugin_directory_before_deactivation(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    registry = PluginRegistry(paths=paths, sereto_version="0.9.0")

    async def discover_manifest(prepared: PreparedPluginEnvironment) -> Manifest:
        return _manifest()

    lifecycle = PluginLifecycle(
        registry=registry,
        package_manager=FakePackageManager(),
        discover_manifest=discover_manifest,
    )
    record = asyncio.run(lifecycle.install(PluginInstallRequest(source="acme-testssl==2.4.1")))
    registry_digest = registry.load().digest
    plugin_directory = paths.plugin_dir(record.plugin_id)
    moved_directory = tmp_path / "moved-plugin"
    plugin_directory.rename(moved_directory)
    plugin_directory.symlink_to(moved_directory, target_is_directory=True)

    with pytest.raises(PluginLifecycleError, match="managed package-plugin path is unsafe"):
        lifecycle.remove(record.plugin_id)

    unchanged = registry.load()
    assert unchanged.digest == registry_digest
    assert [issue.plugin_id for issue in unchanged.issues] == [record.plugin_id]


def test_doctor_reports_orphaned_lifecycle_state_without_mutation(tmp_path: Path) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    registry = PluginRegistry(paths=paths, sereto_version="0.9.0")

    async def discover_manifest(prepared: PreparedPluginEnvironment) -> Manifest:
        return _manifest()

    lifecycle = PluginLifecycle(
        registry=registry,
        package_manager=FakePackageManager(),
        discover_manifest=discover_manifest,
    )
    asyncio.run(lifecycle.install(PluginInstallRequest(source="acme-testssl==2.4.1")))
    orphaned_generation = paths.generation_dir("acme-testssl", "generation-old")
    orphaned_generation.mkdir()
    orphaned_plugin = paths.plugin_dir("orphaned-plugin")
    orphaned_plugin.mkdir()
    orphaned_candidate = paths.root / ".plugin-source-interrupted"
    orphaned_candidate.mkdir()

    issues = lifecycle.doctor()

    assert {(issue.code, issue.plugin_id) for issue in issues} == {
        ("orphaned-generation", "acme-testssl"),
        ("orphaned-plugin", "orphaned-plugin"),
        ("orphaned-candidate", ".plugin-source-interrupted"),
    }
    assert orphaned_generation.is_dir()
    assert orphaned_plugin.is_dir()
    assert orphaned_candidate.is_dir()


def test_uv_package_manager_retains_artifact_and_prepares_locked_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel = tmp_path / "acme_testssl-2.4.1-py3-none-any.whl"
    wheel.write_bytes(b"wheel-content")
    paths = PluginPaths(root=tmp_path / "plugins")
    commands: list[tuple[str, ...]] = []
    command_environments: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(tuple(command))
        environment = dict(kwargs["env"])
        command_environments.append((tuple(command), environment))
        if command == ["uv", "--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="uv 0.12.3\n", stderr="")
        if command[:2] == ["uv", "lock"]:
            project = Path(command[command.index("--project") + 1])
            (project / "uv.lock").write_text(
                'version = 1\n\n[[package]]\nname = "acme-testssl"\nversion = "2.4.1"\n'
                'source = { path = "artifacts/acme_testssl-2.4.1-py3-none-any.whl" }\n',
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["uv", "sync"]:
            environment_path = Path(environment["UV_PROJECT_ENVIRONMENT"])
            python_path = environment_path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            python_path.parent.mkdir(parents=True)
            python_path.touch()
            if os.name == "nt":
                site_packages = environment_path / "Lib" / "site-packages"
            else:
                site_packages = environment_path / "lib" / "python3.14" / "site-packages"
            plugin_metadata = site_packages / "acme_testssl-2.4.1.dist-info"
            sdk_metadata = site_packages / "sereto_sdk-0.1.0.dist-info"
            plugin_metadata.mkdir(parents=True)
            sdk_metadata.mkdir()
            plugin_metadata.joinpath("METADATA").write_text(
                "Metadata-Version: 2.4\nName: Acme_TestSSL\nVersion: 2.4.1\n",
                encoding="utf-8",
            )
            plugin_metadata.joinpath("entry_points.txt").write_text(
                "[sereto.plugins.v1]\nacme-testssl = acme_testssl:plugin\n",
                encoding="utf-8",
            )
            sdk_metadata.joinpath("METADATA").write_text(
                "Metadata-Version: 2.4\nName: sereto-sdk\nVersion: 0.1.0\n",
                encoding="utf-8",
            )
            python_version = f"{sys.version_info.major}.{sys.version_info.minor}.7"
            environment_path.joinpath("pyvenv.cfg").write_text(
                f"implementation = CPython\nversion_info = {python_version}\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["uv", "pip", "check"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess: {command}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("UV_INDEX", "https://must-not-be-inherited.example/simple")
    monkeypatch.setenv("UV_INDEX_PRIVATE_USERNAME", "test-user")
    monkeypatch.setenv("UV_INDEX_PRIVATE_PASSWORD", "test-password")
    monkeypatch.setenv("UV_INDEX_UNRELATED_PASSWORD", "must-not-be-inherited")
    manager = UvPackageManager(uv_executable="uv", python_executable=tmp_path / "host-python")
    install_request = PluginInstallRequest(
        source=str(wheel),
        indexes=(PluginIndex(name="private", url="https://packages.example.test/simple"),),
    )

    prepared = manager.prepare(install_request, paths)

    retained_wheel = prepared.generation_path / "artifacts" / wheel.name
    project = tomllib.loads((prepared.generation_path / "pyproject.toml").read_text(encoding="utf-8"))
    assert retained_wheel.read_bytes() == b"wheel-content"
    assert project["project"]["dependencies"] == [f"acme-testssl @ {retained_wheel.as_uri()}"]
    assert project["tool"]["uv"] == {
        "package": False,
        "index": [{"name": "private", "url": "https://packages.example.test/simple"}],
    }
    assert (prepared.generation_path / "uv.toml").read_text(encoding="utf-8") == ""
    assert prepared.plugin_id == "acme-testssl"
    assert prepared.source.kind == "artifact"
    assert prepared.source.artifact_sha256 == hashlib.sha256(b"wheel-content").hexdigest()
    assert prepared.lock_digest == hashlib.sha256((prepared.generation_path / "uv.lock").read_bytes()).hexdigest()
    assert any(command[:2] == ("uv", "lock") for command in commands)
    assert any(command[:3] == ("uv", "pip", "check") for command in commands)
    sync_command = next(command for command in commands if command[:2] == ("uv", "sync"))
    assert sync_command[sync_command.index("--link-mode") + 1] == "copy"
    assert all("UV_INDEX" not in environment for _, environment in command_environments)
    resolver_environments = [
        environment for command, environment in command_environments if command[:2] in (("uv", "lock"), ("uv", "sync"))
    ]
    other_environments = [
        environment
        for command, environment in command_environments
        if command[:2] not in (("uv", "lock"), ("uv", "sync"))
    ]
    assert all(environment["UV_INDEX_PRIVATE_USERNAME"] == "test-user" for environment in resolver_environments)
    assert all(environment["UV_INDEX_PRIVATE_PASSWORD"] == "test-password" for environment in resolver_environments)
    assert all("UV_INDEX_UNRELATED_PASSWORD" not in environment for environment in resolver_environments)
    assert all("UV_INDEX_PRIVATE_USERNAME" not in environment for environment in other_environments)
    assert all("UV_INDEX_PRIVATE_PASSWORD" not in environment for environment in other_environments)


def test_uv_package_manager_marks_source_index_explicit(tmp_path: Path) -> None:
    generation_path = tmp_path / "generation"
    generation_path.mkdir()
    request = PluginInstallRequest(
        source="acme-testssl==2.4.1",
        indexes=(PluginIndex(name="private", url="https://packages.example.test/simple"),),
        source_index="private",
    )

    UvPackageManager()._write_project(
        generation_path,
        "acme-testssl",
        request.source,
        request,
    )

    project = tomllib.loads((generation_path / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["uv"]["sources"] == {"acme-testssl": {"index": "private"}}
    assert project["tool"]["uv"]["index"] == [
        {
            "name": "private",
            "url": "https://packages.example.test/simple",
            "explicit": True,
        }
    ]


def test_uv_package_manager_builds_local_source_with_request_indexes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_directory = tmp_path / "source"
    source_directory.mkdir()
    build_directory = tmp_path / "build"
    build_directory.mkdir()
    captured: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        environment = dict(kwargs["env"])
        captured.append((command, environment))
        output_directory = Path(command[command.index("--out-dir") + 1])
        (output_directory / "acme_testssl-2.4.1-py3-none-any.whl").write_bytes(b"wheel")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("UV_INDEX_PRIVATE_PASSWORD", "private-password")
    monkeypatch.setenv("UV_INDEX_SERETO_DEFAULT_PASSWORD", "default-password")
    request = PluginInstallRequest(
        source=str(source_directory),
        indexes=(PluginIndex(name="private", url="https://packages.example.test/simple"),),
        default_index="https://default.example.test/simple",
        keyring_provider="subprocess",
    )

    plan = UvPackageManager(python_executable=tmp_path / "host-python")._plan_source(
        request.source,
        build_directory,
        request=request,
    )

    command, environment = captured[0]
    assert command[command.index("--index") + 1] == "private=https://packages.example.test/simple"
    assert command[command.index("--default-index") + 1] == ("sereto-default=https://default.example.test/simple")
    assert command[command.index("--keyring-provider") + 1] == "subprocess"
    assert environment["UV_INDEX_PRIVATE_PASSWORD"] == "private-password"
    assert environment["UV_INDEX_SERETO_DEFAULT_PASSWORD"] == "default-password"
    assert plan.distribution_name == "acme-testssl"
    assert plan.artifact_sha256 == hashlib.sha256(b"wheel").hexdigest()


def test_uv_package_manager_records_index_and_vcs_provenance(tmp_path: Path) -> None:
    manager = UvPackageManager()
    index_request = PluginInstallRequest(
        source="acme-testssl>=2",
        indexes=(PluginIndex(name="private", url="https://packages.example.test/simple"),),
        source_index="private",
    )
    index_plan = manager._plan_source(index_request.source, tmp_path)

    index_source = manager._source_provenance(
        index_plan,
        {"source": {"registry": "https://packages.example.test/simple"}},
        index_request,
    )

    assert index_source == SourceProvenance(
        kind="index",
        requirement="acme-testssl>=2",
        origin="https://packages.example.test/simple",
        index_name="private",
    )

    vcs_request = PluginInstallRequest(source="acme-testssl @ git+https://git.example.test/acme-testssl.git@main")
    vcs_plan = manager._plan_source(vcs_request.source, tmp_path)
    vcs_source = manager._source_provenance(
        vcs_plan,
        {"source": {"git": f"https://git.example.test/acme-testssl.git#{'a' * 40}"}},
        vcs_request,
    )

    assert vcs_source.kind == "vcs"
    assert vcs_source.vcs_commit == "a" * 40

    with pytest.raises(PluginPackageManagerError, match="does not match the pinned source index"):
        manager._source_provenance(
            index_plan,
            {"source": {"registry": "https://other.example.test/simple"}},
            index_request,
        )


def test_uv_package_manager_records_direct_artifact_hash(tmp_path: Path) -> None:
    manager = UvPackageManager()
    request = PluginInstallRequest(source="acme-testssl @ https://packages.example.test/acme-testssl.whl")
    plan = manager._plan_source(request.source, tmp_path)

    source = manager._source_provenance(
        plan,
        {
            "source": {"url": "https://packages.example.test/acme-testssl.whl"},
            "wheels": [{"hash": f"sha256:{'b' * 64}"}],
        },
        request,
    )

    assert source.kind == "artifact"
    assert source.artifact_sha256 == "b" * 64


def test_uv_package_manager_cleans_candidate_after_resolver_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel = tmp_path / "acme_testssl-2.4.1-py3-none-any.whl"
    wheel.write_bytes(b"wheel-content")
    paths = PluginPaths(root=tmp_path / "plugins")

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command == ["uv", "--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="uv 0.12.3\n", stderr="")
        raise subprocess.CalledProcessError(1, command, stderr="resolver failed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(PluginPackageManagerError, match="cannot resolve plugin dependencies"):
        UvPackageManager().prepare(PluginInstallRequest(source=str(wheel)), paths)

    assert not paths.plugin_dir("acme-testssl").exists()
    assert list(paths.root.glob(".plugin-source-*")) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "acme-testssl @ https://user:secret@example.test/acme.whl",
            id="http-userinfo",
        ),
        pytest.param(
            "acme-testssl @ https://example.test/acme.whl?token=secret",
            id="query-credential",
        ),
        pytest.param(
            "acme-testssl @ http://packages.example.test/acme.whl",
            id="insecure-http",
        ),
        pytest.param(
            "acme-testssl @ git+git://git.example.test/acme-testssl.git@main",
            id="insecure-git",
        ),
        pytest.param(
            "acme-testssl @ file:///tmp/acme-testssl.whl",
            id="direct-file-bypass",
        ),
    ],
)
def test_uv_package_manager_rejects_unsafe_direct_source(tmp_path: Path, source: str) -> None:
    with pytest.raises(PluginPackageManagerError):
        UvPackageManager()._plan_source(source, tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX symbolic link check")
def test_uv_package_manager_rejects_distribution_metadata_symlink(tmp_path: Path) -> None:
    environment_path = tmp_path / "environment"
    site_packages = environment_path / "lib" / "python3.14" / "site-packages"
    site_packages.mkdir(parents=True)
    outside_metadata = tmp_path / "outside.dist-info"
    outside_metadata.mkdir()
    (outside_metadata / "METADATA").write_text(
        "Metadata-Version: 2.4\nName: acme-testssl\nVersion: 2.4.1\n",
        encoding="utf-8",
    )
    (site_packages / "acme_testssl-2.4.1.dist-info").symlink_to(
        outside_metadata,
        target_is_directory=True,
    )

    with pytest.raises(PluginPackageManagerError, match="metadata escapes site-packages"):
        UvPackageManager()._inspect_environment(environment_path, "acme-testssl")


@pytest.mark.parametrize(
    "install_request",
    [
        pytest.param(
            PluginInstallRequest(
                source="acme-testssl",
                indexes=(PluginIndex(name="private", url="https://user:secret@example.test/simple"),),
            ),
            id="index-credentials",
        ),
        pytest.param(
            PluginInstallRequest(
                source="acme-testssl",
                indexes=(PluginIndex(name="private", url="https://example.test/simple"),),
                source_index="missing",
            ),
            id="unknown-source-index",
        ),
        pytest.param(
            PluginInstallRequest(
                source="acme-testssl",
                indexes=(
                    PluginIndex(name="private-one", url="https://one.example.test/simple"),
                    PluginIndex(name="private_one", url="https://two.example.test/simple"),
                ),
            ),
            id="ambiguous-credential-environment",
        ),
    ],
)
def test_uv_package_manager_rejects_unsafe_index_configuration(
    tmp_path: Path,
    install_request: PluginInstallRequest,
) -> None:
    with pytest.raises(PluginPackageManagerError):
        UvPackageManager().prepare(install_request, PluginPaths(root=tmp_path / "plugins"))
