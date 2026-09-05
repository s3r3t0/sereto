import asyncio
import importlib.metadata
from typing import Literal

import click
from rich import box
from rich.markup import escape
from rich.table import Table

from sereto.cli.utils import AliasedGroup, Console
from sereto.exceptions import SeretoValueError, handle_exceptions
from sereto.package_plugins.lifecycle import PluginIndex, PluginInstallRequest, PluginLifecycle
from sereto.package_plugins.package_manager import PluginPackageManagerError, UvPackageManager
from sereto.package_plugins.paths import PluginPaths
from sereto.package_plugins.registry import PluginRegistry


def _new_lifecycle() -> PluginLifecycle:
    paths = PluginPaths.default()
    return PluginLifecycle(
        registry=PluginRegistry(paths=paths, sereto_version=importlib.metadata.version("sereto")),
        package_manager=UvPackageManager(),
    )


def _parse_indexes(values: tuple[str, ...]) -> tuple[PluginIndex, ...]:
    indexes: list[PluginIndex] = []
    for value in values:
        name, separator, url = value.partition("=")
        if not separator or not name or not url:
            raise SeretoValueError("plugin indexes must use NAME=URL syntax")
        indexes.append(PluginIndex(name=name, url=url))
    return tuple(indexes)


@click.group(cls=AliasedGroup)
def plugin() -> None:
    """Manage isolated package plugins."""


@plugin.command(name="install")
@click.argument("source")
@click.option(
    "--index",
    "indexes",
    multiple=True,
    metavar="NAME=URL",
    help="Add a named package index. May be repeated.",
)
@click.option("--default-index", metavar="URL", help="Replace PyPI as the default package index.")
@click.option("--source-index", metavar="NAME", help="Pin the plugin package itself to a named index.")
@click.option(
    "--keyring-provider",
    type=click.Choice(["disabled", "subprocess"]),
    default="disabled",
    show_default=True,
    help="Select uv's package-index credential provider.",
)
@handle_exceptions
def plugin_install(
    source: str,
    indexes: tuple[str, ...],
    default_index: str | None,
    source_index: str | None,
    keyring_provider: Literal["disabled", "subprocess"],
) -> None:
    """Install SOURCE into a new isolated managed environment."""
    request = PluginInstallRequest(
        source=source,
        indexes=_parse_indexes(indexes),
        default_index=default_index,
        source_index=source_index,
        keyring_provider=keyring_provider,
    )
    record = asyncio.run(_new_lifecycle().install(request))
    click.echo(f"Installed {record.plugin_id} {record.distribution.version}")


@plugin.command(name="remove")
@click.argument("plugin_id")
@click.option("-y", "--yes", is_flag=True, help="Remove without confirmation.")
@handle_exceptions
def plugin_remove(plugin_id: str, yes: bool) -> None:
    """Remove PLUGIN_ID and all of its managed data."""
    if not yes and not click.confirm(f"Remove package plugin {plugin_id!r} and all managed data?"):
        click.echo("Removal cancelled.")
        return
    _new_lifecycle().remove(plugin_id)
    click.echo(f"Removed {plugin_id}")


@plugin.command(name="list")
@handle_exceptions
def plugin_list() -> None:
    """List installed package plugins from the cached registry."""
    snapshot = _new_lifecycle().snapshot()
    table = Table("Plugin", "Version", "Health", title="Managed package plugins", box=box.MINIMAL)
    for plugin_id, record in sorted(snapshot.state.plugins.items()):
        table.add_row(escape(plugin_id), escape(record.distribution.version), record.health)
    for issue in sorted(snapshot.issues, key=lambda item: item.plugin_id):
        table.add_row(escape(issue.plugin_id), "unavailable", issue.code)
    Console().print(table, justify="center")


@plugin.command(name="show")
@click.argument("plugin_id")
@handle_exceptions
def plugin_show(plugin_id: str) -> None:
    """Show cached metadata for one installed package plugin."""
    record = _new_lifecycle().show(plugin_id)
    table = Table("Field", "Value", title=record.plugin_id, box=box.MINIMAL)
    values = (
        ("Distribution", f"{record.distribution.name} {record.distribution.version}"),
        ("Source", record.source.requirement),
        ("Origin", record.source.origin),
        ("Generation", record.runtime.generation_id),
        ("Environment", str(record.runtime.environment_path)),
        ("Python", record.runtime.python_version),
        ("SDK", f"v{record.sdk_api_major} ({record.sdk_package_version})"),
        ("Protocol", str(record.selected_protocol_version)),
        ("Health", record.health),
    )
    for field, value in values:
        table.add_row(field, escape(value))
    Console().print(table, justify="center")


@plugin.command(name="doctor")
@handle_exceptions
def plugin_doctor() -> None:
    """Check uv availability and cached plugin environments without running plugins."""
    lifecycle = _new_lifecycle()
    package_manager_error: PluginPackageManagerError | None = None
    try:
        package_manager_version = lifecycle.package_manager_version()
    except PluginPackageManagerError as error:
        package_manager_version = "unavailable"
        package_manager_error = error

    click.echo(f"uv: {package_manager_version}")
    issues = lifecycle.doctor()
    if package_manager_error is not None:
        click.echo(f"host: {package_manager_error}")
    for issue in issues:
        click.echo(f"{issue.plugin_id}: {issue.code}: {issue.message}")
    if package_manager_error is not None or issues:
        raise click.exceptions.Exit(1)
    click.echo("No package-plugin issues found.")
