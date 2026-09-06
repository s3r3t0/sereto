import asyncio
import importlib.metadata
import json
import unicodedata
from collections import Counter
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal, cast

import click

from sereto.cli.aliases import cli_aliases
from sereto.exceptions import SeretoRuntimeError, handle_exceptions
from sereto.package_plugins.manifest import PluginRecord
from sereto.package_plugins.paths import PluginPaths
from sereto.package_plugins.protocol_v1 import (
    Command,
    Operation,
    OperationRequest,
    OperationResultPayload,
    ProgressPayload,
)
from sereto.package_plugins.registry import PluginRegistry
from sereto.package_plugins.resources import TargetResources
from sereto.package_plugins.session import PluginLaunch, PluginSession
from sereto.project import Project

MAX_COMMAND_TEXT_LENGTH = 1024


class PluginCommandError(SeretoRuntimeError):
    """A cached package-plugin command cannot be registered or invoked safely."""


@dataclass(frozen=True)
class CommandRegistrationIssue:
    plugin_id: str
    path: tuple[str, ...]
    code: Literal["command-collision", "invalid-command-parent", "invalid-command-metadata"]
    message: str


_registration_issues: tuple[CommandRegistrationIssue, ...] = ()


class ManagedPluginCommand(click.Command):
    """A Click leaf backed only by a validated cached plugin command."""

    def __init__(self, record: PluginRecord, declaration: Command) -> None:
        self.plugin_record = record
        self.declaration = declaration
        usage = declaration.usage or "[PLUGIN-ARGS]"
        super().__init__(
            name=declaration.path[-1],
            callback=self._invoke,
            help=declaration.summary,
            options_metavar=f"[OPTIONS] {usage}",
            params=[
                click.Option(
                    ["--sereto-target", "target_selector"],
                    help="Target selector (index, category, or uname).",
                )
            ],
            context_settings={
                "allow_extra_args": True,
                "ignore_unknown_options": True,
                "help_option_names": ["-h", "--help"],
            },
        )

    @handle_exceptions
    def _invoke(self, target_selector: str | None) -> None:
        context = click.get_current_context()
        project = context.find_object(Project)
        if project is None:
            raise PluginCommandError("managed package-plugin command has no SeReTo project context")
        with _locked_active_record(self.plugin_record) as record:
            operation = _resolve_operation(record, self.declaration)
            target_resources = _target_resources(project, operation, target_selector)
            result = asyncio.run(
                PluginSession(
                    launch=PluginLaunch(
                        python=record.runtime.python_path,
                        distribution_name=record.distribution.name,
                        distribution_version=record.distribution.version,
                        entry_point=record.entry_point,
                        expected_plugin_id=record.plugin_id,
                        sdk_api_major=cast(Literal[1], record.sdk_api_major),
                    ),
                    sereto_version=importlib.metadata.version("sereto"),
                ).run(
                    OperationRequest(
                        operation_id=operation.id,
                        arguments={"argv": list(context.args)},
                        resources=target_resources.resources,
                    ),
                    on_progress=_show_progress,
                )
            )
        if not isinstance(result, OperationResultPayload):
            raise PluginCommandError("managed package-plugin operation returned a manifest result")
        click.echo(json.dumps(result.model_dump(mode="json"), allow_nan=False, indent=2, sort_keys=True))


def collect_group_paths(root: click.Group) -> frozenset[tuple[str, ...]]:
    """Collect existing group paths without resolving or invoking commands."""
    paths: set[tuple[str, ...]] = set()

    def visit(group: click.Group, prefix: tuple[str, ...]) -> None:
        for name, child in group.commands.items():
            if isinstance(child, click.Group):
                path = (*prefix, name)
                paths.add(path)
                visit(child, path)

    visit(root, ())
    return frozenset(paths)


def snapshot_command_tree(root: click.Group) -> tuple[tuple[tuple[str, ...], click.Command], ...]:
    """Capture core command identities before legacy plugins can mutate the tree."""
    commands: list[tuple[tuple[str, ...], click.Command]] = []

    def visit(group: click.Group, prefix: tuple[str, ...]) -> None:
        for name, child in group.commands.items():
            path = (*prefix, name)
            commands.append((path, child))
            if isinstance(child, click.Group):
                visit(child, path)

    visit(root, ())
    return tuple(commands)


def restore_command_tree(
    root: click.Group,
    snapshot: tuple[tuple[tuple[str, ...], click.Command], ...],
) -> None:
    """Restore every core command identity while preserving non-conflicting legacy leaves."""
    for path, command in sorted(snapshot, key=lambda item: len(item[0])):
        parent = _resolve_group(root, path[:-1])
        if parent is not None:
            parent.commands[path[-1]] = command


def reserved_top_level_paths(*names: str) -> frozenset[tuple[str, ...]]:
    """Return explicit CLI aliases and deferred core command names."""
    return frozenset((name,) for name in (*cli_aliases, *names))


def register_cached_plugin_commands(
    root: click.Group,
    records: Iterable[PluginRecord],
    allowed_parent_paths: frozenset[tuple[str, ...]],
    reserved_paths: frozenset[tuple[str, ...]] = frozenset(),
) -> tuple[CommandRegistrationIssue, ...]:
    """Register cached managed leaves after core and legacy commands."""
    candidates = sorted(
        (
            (record, declaration)
            for record in records
            if record.health == "healthy"
            for declaration in record.manifest.commands
        ),
        key=lambda item: (item[1].path, item[0].plugin_id),
    )
    path_counts = Counter(declaration.path for _, declaration in candidates if _command_metadata_is_safe(declaration))
    issues: list[CommandRegistrationIssue] = []

    for record, declaration in candidates:
        path = declaration.path
        if not _command_metadata_is_safe(declaration):
            issues.append(
                CommandRegistrationIssue(
                    plugin_id=record.plugin_id,
                    path=path,
                    code="invalid-command-metadata",
                    message=f"managed command {' '.join(path)!r} has unsafe summary or usage text",
                )
            )
            continue
        if path_counts[path] > 1 or path in reserved_paths:
            issues.append(
                CommandRegistrationIssue(
                    plugin_id=record.plugin_id,
                    path=path,
                    code="command-collision",
                    message=(
                        f"managed command {' '.join(path)!r} conflicts with a reserved core command"
                        if path in reserved_paths
                        else f"multiple managed plugins declare command {' '.join(path)!r}"
                    ),
                )
            )
            continue

        parent_path = path[:-1]
        if parent_path and parent_path not in allowed_parent_paths:
            issues.append(
                CommandRegistrationIssue(
                    plugin_id=record.plugin_id,
                    path=path,
                    code="invalid-command-parent",
                    message=f"managed command parent {' '.join(parent_path)!r} is not a core command group",
                )
            )
            continue

        parent = _resolve_group(root, parent_path)
        if parent is None:
            issues.append(
                CommandRegistrationIssue(
                    plugin_id=record.plugin_id,
                    path=path,
                    code="invalid-command-parent",
                    message=f"managed command parent {' '.join(parent_path)!r} is unavailable",
                )
            )
            continue
        if path[-1] in parent.commands:
            issues.append(
                CommandRegistrationIssue(
                    plugin_id=record.plugin_id,
                    path=path,
                    code="command-collision",
                    message=f"managed command {' '.join(path)!r} conflicts with an existing command",
                )
            )
            continue
        parent.add_command(ManagedPluginCommand(record, declaration))

    return tuple(issues)


def load_cached_plugin_commands(
    root: click.Group,
    allowed_parent_paths: frozenset[tuple[str, ...]],
    reserved_paths: frozenset[tuple[str, ...]] = frozenset(),
) -> tuple[CommandRegistrationIssue, ...]:
    """Load the inert registry and register its healthy cached command leaves."""
    global _registration_issues
    _registration_issues = ()
    _remove_managed_commands(root)
    snapshot = PluginRegistry(
        paths=PluginPaths.default(),
        sereto_version=importlib.metadata.version("sereto"),
    ).load()
    _registration_issues = register_cached_plugin_commands(
        root,
        records=snapshot.state.plugins.values(),
        allowed_parent_paths=allowed_parent_paths,
        reserved_paths=reserved_paths,
    )
    return _registration_issues


def command_registration_issues() -> tuple[CommandRegistrationIssue, ...]:
    """Return command issues detected during the current CLI startup."""
    return _registration_issues


def _resolve_group(root: click.Group, path: tuple[str, ...]) -> click.Group | None:
    group = root
    for segment in path:
        child = group.commands.get(segment)
        if not isinstance(child, click.Group):
            return None
        group = child
    return group


def _remove_managed_commands(group: click.Group) -> None:
    for name, child in tuple(group.commands.items()):
        if isinstance(child, ManagedPluginCommand):
            del group.commands[name]
        elif isinstance(child, click.Group):
            _remove_managed_commands(child)


def _command_metadata_is_safe(declaration: Command) -> bool:
    return all(
        len(value) <= MAX_COMMAND_TEXT_LENGTH
        and not any(
            unicodedata.category(character).startswith("C") or unicodedata.category(character) in {"Zl", "Zp"}
            for character in value
        )
        for value in (declaration.summary, declaration.usage)
    )


@contextmanager
def _locked_active_record(cached_record: PluginRecord) -> Generator[PluginRecord]:
    registry = PluginRegistry(
        paths=PluginPaths.default(),
        sereto_version=importlib.metadata.version("sereto"),
    )
    with registry.locked_runtime(cached_record.plugin_id):
        yield _load_active_record(cached_record, registry)


def _load_active_record(cached_record: PluginRecord, registry: PluginRegistry) -> PluginRecord:
    snapshot = registry.load()
    active_record = snapshot.state.plugins.get(cached_record.plugin_id)
    if active_record is None:
        raise PluginCommandError(f"package plugin {cached_record.plugin_id!r} is no longer active; restart SeReTo")
    if active_record.health != "healthy":
        raise PluginCommandError(f"package plugin {cached_record.plugin_id!r} is unhealthy; run plugin doctor")
    if (
        active_record.runtime.generation_id != cached_record.runtime.generation_id
        or active_record.manifest_digest != cached_record.manifest_digest
    ):
        raise PluginCommandError(f"package plugin {cached_record.plugin_id!r} changed after startup; restart SeReTo")
    return active_record


def _resolve_operation(record: PluginRecord, declaration: Command) -> Operation:
    operation = next(
        (operation for operation in record.manifest.operations if operation.id == declaration.operation_id),
        None,
    )
    if operation is None or declaration not in record.manifest.commands:
        raise PluginCommandError(f"cached command {' '.join(declaration.path)!r} is no longer declared")
    return operation


def _target_resources(
    project: Project,
    operation: Operation,
    target_selector: str | None,
) -> TargetResources:
    if "sereto.target.v1" not in operation.resource_kinds:
        return TargetResources.from_targets(())
    target = project.config.last_config.select_target(
        categories=project.settings.categories,
        selector=target_selector,
    )
    return TargetResources.from_targets((target,))


def _show_progress(progress: ProgressPayload) -> None:
    if progress.message is not None:
        click.echo(progress.message, err=True)
