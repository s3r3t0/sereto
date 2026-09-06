from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import click
import pytest
from click.testing import CliRunner

import sereto.package_plugins.commands as commands_module
from sereto.package_plugins.commands import (
    PluginCommandError,
    collect_group_paths,
    load_cached_plugin_commands,
    register_cached_plugin_commands,
    reserved_top_level_paths,
    restore_command_tree,
    snapshot_command_tree,
)
from sereto.package_plugins.manifest import PluginRecord
from sereto.package_plugins.paths import PluginPaths
from sereto.package_plugins.protocol_v1 import Command, Operation, OperationResultPayload, Resource
from sereto.project import Project


def _record(
    *commands: Command,
    plugin_id: str = "acme-testssl",
    health: str = "healthy",
) -> PluginRecord:
    return cast(
        PluginRecord,
        SimpleNamespace(
            plugin_id=plugin_id,
            health=health,
            manifest=SimpleNamespace(commands=commands),
        ),
    )


def test_cached_commands_register_beneath_core_group_without_starting_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @click.group()
    def root() -> None:
        pass

    @root.group()
    def findings() -> None:
        pass

    @findings.command(name="add")
    def add_finding() -> None:
        pass

    def fail_session(*args: object, **kwargs: object) -> None:
        raise AssertionError("cached command help started a plugin session")

    monkeypatch.setattr(commands_module, "PluginSession", fail_session)
    issues = register_cached_plugin_commands(
        root,
        records=(
            _record(
                Command(
                    path=("findings", "testssl"),
                    operation_id="testssl.analyze",
                    summary="Analyze testssl output",
                    usage="[PLUGIN-ARGS]",
                ),
                Command(
                    path=("findings", "add"),
                    operation_id="testssl.collide",
                    summary="Must not replace core",
                ),
            ),
        ),
        allowed_parent_paths=collect_group_paths(root),
    )

    result = CliRunner().invoke(root, ["findings", "testssl", "--help"])

    assert result.exit_code == 0
    assert "Analyze testssl output" in result.output
    assert "[PLUGIN-ARGS]" in result.output
    assert findings.commands["add"] is add_finding
    assert [(issue.code, issue.path) for issue in issues] == [
        ("command-collision", ("findings", "add")),
    ]


def test_cached_command_invokes_active_plugin_with_target_and_opaque_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declaration = Command(
        path=("findings", "testssl"),
        operation_id="testssl.analyze",
        summary="Analyze testssl output",
        usage="[PLUGIN-ARGS]",
    )
    operation = Operation(
        id="testssl.analyze",
        capability="finding.propose",
        resource_kinds=("sereto.target.v1",),
    )
    record = cast(
        PluginRecord,
        SimpleNamespace(
            plugin_id="acme-testssl",
            health="healthy",
            entry_point="acme-testssl",
            sdk_api_major=1,
            manifest_digest="a" * 64,
            distribution=SimpleNamespace(name="Acme_TestSSL", version="2.4.1"),
            runtime=SimpleNamespace(
                generation_id="generation-1",
                python_path="/managed/python",
            ),
            manifest=SimpleNamespace(commands=(declaration,), operations=(operation,)),
        ),
    )
    resource = Resource(
        kind="sereto.target.v1",
        id="target_1",
        attributes={"category": "infrastructure", "name": "External TLS", "version": "v1.0", "locators": []},
    )
    captured: dict[str, object] = {}

    class FakeSession:
        def __init__(self, **kwargs: object) -> None:
            captured["session"] = kwargs

        async def run(self, request: object, on_progress: object) -> OperationResultPayload:
            assert captured["runtime_lock"] == "held"
            captured["request"] = request
            captured["progress"] = on_progress
            return OperationResultPayload(output={"analyzed": True})

    @contextmanager
    def locked_active_record(cached: PluginRecord) -> object:
        captured["runtime_lock"] = "held"
        try:
            yield record
        finally:
            captured["runtime_lock"] = "released"

    monkeypatch.setattr(commands_module, "_locked_active_record", locked_active_record)
    monkeypatch.setattr(
        commands_module,
        "_target_resources",
        lambda project, selected_operation, target_selector: SimpleNamespace(resources=(resource,)),
    )
    monkeypatch.setattr(commands_module, "PluginSession", FakeSession)

    @click.group()
    def root() -> None:
        pass

    @root.group()
    def findings() -> None:
        pass

    register_cached_plugin_commands(
        root,
        records=(record,),
        allowed_parent_paths=collect_group_paths(root),
    )

    result = CliRunner().invoke(
        root,
        ["findings", "testssl", "--sereto-target", "external", "--target", "plugin-value"],
        obj=Project(),
    )

    assert result.exit_code == 0
    request = captured["request"]
    assert request.operation_id == "testssl.analyze"  # type: ignore[union-attr]
    assert request.arguments == {"argv": ["--target", "plugin-value"]}  # type: ignore[union-attr]
    assert request.resources == (resource,)  # type: ignore[union-attr]
    assert '"analyzed": true' in result.output
    assert captured["runtime_lock"] == "released"


def test_registration_rejects_duplicate_managed_paths_and_non_core_parent() -> None:
    @click.group()
    def root() -> None:
        pass

    @root.group()
    def findings() -> None:
        pass

    allowed_parent_paths = collect_group_paths(root)

    @root.group()
    def legacy() -> None:
        pass

    duplicate = Command(
        path=("findings", "scan"),
        operation_id="scan.run",
        summary="Scan target",
    )
    issues = register_cached_plugin_commands(
        root,
        records=(
            _record(duplicate, plugin_id="alpha-plugin"),
            _record(duplicate, plugin_id="beta-plugin"),
            _record(
                Command(path=("legacy", "scan"), operation_id="legacy.run", summary="Invalid parent"),
                plugin_id="parent-plugin",
            ),
            _record(
                Command(path=("top-level-scan",), operation_id="top.run", summary="Top-level command"),
                plugin_id="top-plugin",
            ),
            _record(
                Command(path=("findings", "unhealthy"), operation_id="bad.run", summary="Unavailable"),
                plugin_id="unhealthy-plugin",
                health="unhealthy",
            ),
            _record(
                Command(path=("c",), operation_id="alias.run", summary="Must not shadow core alias"),
                plugin_id="alias-plugin",
            ),
            _record(
                Command(path=("unsafe",), operation_id="unsafe.run", summary="unsafe\nsummary"),
                plugin_id="unsafe-plugin",
            ),
            _record(
                Command(path=("bidi",), operation_id="bidi.run", summary="safe\u202etext"),
                plugin_id="bidi-plugin",
            ),
            _record(
                Command(path=("separator",), operation_id="separator.run", summary="unsafe\u2028text"),
                plugin_id="separator-plugin",
            ),
        ),
        allowed_parent_paths=allowed_parent_paths,
        reserved_paths=reserved_top_level_paths("cd", "exit", "log"),
    )

    assert "scan" not in findings.commands
    assert "unhealthy" not in findings.commands
    assert "scan" not in legacy.commands
    assert "top-level-scan" in root.commands
    assert [(issue.plugin_id, issue.code, issue.path) for issue in issues] == [
        ("bidi-plugin", "invalid-command-metadata", ("bidi",)),
        ("alias-plugin", "command-collision", ("c",)),
        ("alpha-plugin", "command-collision", ("findings", "scan")),
        ("beta-plugin", "command-collision", ("findings", "scan")),
        ("parent-plugin", "invalid-command-parent", ("legacy", "scan")),
        ("separator-plugin", "invalid-command-metadata", ("separator",)),
        ("unsafe-plugin", "invalid-command-metadata", ("unsafe",)),
    ]


def test_restore_command_tree_preserves_core_precedence_and_legacy_additions() -> None:
    @click.group()
    def root() -> None:
        pass

    @root.group()
    def findings() -> None:
        pass

    @findings.command(name="add")
    def core_add() -> None:
        pass

    snapshot = snapshot_command_tree(root)

    @click.command(name="add")
    def conflicting_legacy() -> None:
        pass

    @click.command(name="legacy")
    def legacy_leaf() -> None:
        pass

    findings.add_command(conflicting_legacy)
    findings.add_command(legacy_leaf)
    restore_command_tree(root, snapshot)

    assert findings.commands["add"] is core_add
    assert findings.commands["legacy"] is legacy_leaf


def test_restore_command_tree_restores_replaced_core_group_and_descendants() -> None:
    @click.group()
    def root() -> None:
        pass

    @root.group()
    def findings() -> None:
        pass

    @findings.command(name="add")
    def core_add() -> None:
        pass

    snapshot = snapshot_command_tree(root)
    root.add_command(click.Command(name="findings", callback=lambda: None))

    restore_command_tree(root, snapshot)

    assert root.commands["findings"] is findings
    assert findings.commands["add"] is core_add


def test_unsafe_metadata_does_not_block_valid_managed_command_at_same_path() -> None:
    @click.group()
    def root() -> None:
        pass

    unsafe = Command(path=("scan",), operation_id="unsafe.run", summary="unsafe\nsummary")
    safe = Command(path=("scan",), operation_id="safe.run", summary="Scan target")

    issues = register_cached_plugin_commands(
        root,
        records=(
            _record(unsafe, plugin_id="unsafe-plugin"),
            _record(safe, plugin_id="safe-plugin"),
        ),
        allowed_parent_paths=frozenset(),
    )

    assert isinstance(root.commands["scan"], commands_module.ManagedPluginCommand)
    assert root.commands["scan"].plugin_record.plugin_id == "safe-plugin"  # type: ignore[attr-defined]
    assert [(issue.plugin_id, issue.code) for issue in issues] == [
        ("unsafe-plugin", "invalid-command-metadata"),
    ]


def test_cached_command_loader_is_inert_when_registry_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PluginPaths(root=tmp_path / "plugins")
    monkeypatch.setattr(commands_module.PluginPaths, "default", lambda: paths)
    monkeypatch.setattr(
        commands_module,
        "PluginSession",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("session started")),
    )

    @click.group()
    def root() -> None:
        pass

    issues = load_cached_plugin_commands(root, allowed_parent_paths=frozenset())

    assert issues == ()
    assert not paths.root.exists()


def test_cached_command_loader_replaces_only_previous_managed_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declaration = Command(
        path=("findings", "testssl"),
        operation_id="testssl.analyze",
        summary="Analyze testssl output",
    )
    record = _record(declaration)
    snapshot = SimpleNamespace(state=SimpleNamespace(plugins={record.plugin_id: record}))
    monkeypatch.setattr(
        commands_module,
        "PluginRegistry",
        lambda **kwargs: SimpleNamespace(load=lambda: snapshot),
    )

    @click.group()
    def root() -> None:
        pass

    @root.group()
    def findings() -> None:
        pass

    @findings.command(name="legacy")
    def legacy() -> None:
        pass

    allowed_parent_paths = collect_group_paths(root)
    first_issues = load_cached_plugin_commands(root, allowed_parent_paths)
    first_proxy = findings.commands["testssl"]
    second_issues = load_cached_plugin_commands(root, allowed_parent_paths)

    assert first_issues == second_issues == ()
    assert findings.commands["legacy"] is legacy
    assert findings.commands["testssl"] is not first_proxy


def test_active_record_revalidation_rejects_unhealthy_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    cached = _record()
    active = _record(health="unhealthy")
    registry = cast(
        object,
        SimpleNamespace(
            load=lambda: SimpleNamespace(state=SimpleNamespace(plugins={cached.plugin_id: active})),
        ),
    )

    with pytest.raises(PluginCommandError, match="is unhealthy"):
        commands_module._load_active_record(cached, registry)  # type: ignore[arg-type]


def test_target_resources_use_core_target_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    selected_target = SimpleNamespace()
    captured: dict[str, object] = {}

    def select_target(*, categories: object, selector: object) -> object:
        captured["categories"] = categories
        captured["selector"] = selector
        return selected_target

    project = cast(
        Project,
        SimpleNamespace(
            config=SimpleNamespace(last_config=SimpleNamespace(select_target=select_target)),
            settings=SimpleNamespace(categories=("infrastructure",)),
        ),
    )
    expected_resources = SimpleNamespace(resources=())

    def build_resources(targets: object) -> object:
        captured["targets"] = tuple(targets)  # type: ignore[arg-type]
        return expected_resources

    monkeypatch.setattr(
        commands_module.TargetResources,
        "from_targets",
        staticmethod(build_resources),
    )
    operation = Operation(
        id="testssl.analyze",
        capability="finding.propose",
        resource_kinds=("sereto.target.v1",),
    )

    result = commands_module._target_resources(project, operation, "external")

    assert captured == {
        "categories": ("infrastructure",),
        "selector": "external",
        "targets": (selected_target,),
    }
    assert result is expected_resources
