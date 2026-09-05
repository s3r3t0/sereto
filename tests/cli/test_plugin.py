from types import SimpleNamespace
from typing import Any

from click.testing import CliRunner

import sereto.cli.plugin as plugin_module
from sereto.cli.plugin import plugin
from sereto.package_plugins.lifecycle import PluginInstallRequest


def test_plugin_help_does_not_construct_lifecycle(monkeypatch: Any) -> None:
    def fail() -> None:
        raise AssertionError("plugin help constructed lifecycle state")

    monkeypatch.setattr(plugin_module, "_new_lifecycle", fail)

    result = CliRunner().invoke(plugin, ["--help"])

    assert result.exit_code == 0
    assert "install" in result.output


def test_plugin_install_translates_index_options(monkeypatch: Any) -> None:
    captured: list[PluginInstallRequest] = []

    class FakeLifecycle:
        async def install(self, request: PluginInstallRequest) -> Any:
            captured.append(request)
            return SimpleNamespace(
                plugin_id="acme-testssl",
                distribution=SimpleNamespace(version="2.4.1"),
            )

    monkeypatch.setattr(plugin_module, "_new_lifecycle", FakeLifecycle)

    result = CliRunner().invoke(
        plugin,
        [
            "install",
            "acme-testssl>=2",
            "--index",
            "private=https://packages.example.test/simple",
            "--source-index",
            "private",
            "--keyring-provider",
            "subprocess",
        ],
    )

    assert result.exit_code == 0
    assert result.output == "Installed acme-testssl 2.4.1\n"
    assert captured == [
        PluginInstallRequest(
            source="acme-testssl>=2",
            indexes=(
                plugin_module.PluginIndex(
                    name="private",
                    url="https://packages.example.test/simple",
                ),
            ),
            source_index="private",
            keyring_provider="subprocess",
        )
    ]


def test_plugin_remove_yes_skips_confirmation(monkeypatch: Any) -> None:
    removed: list[str] = []

    class FakeLifecycle:
        def remove(self, plugin_id: str) -> None:
            removed.append(plugin_id)

    monkeypatch.setattr(plugin_module, "_new_lifecycle", FakeLifecycle)

    result = CliRunner().invoke(plugin, ["remove", "acme-testssl", "--yes"])

    assert result.exit_code == 0
    assert result.output == "Removed acme-testssl\n"
    assert removed == ["acme-testssl"]


def test_plugin_remove_can_be_cancelled(monkeypatch: Any) -> None:
    def fail() -> None:
        raise AssertionError("cancelled removal constructed lifecycle state")

    monkeypatch.setattr(plugin_module, "_new_lifecycle", fail)

    result = CliRunner().invoke(plugin, ["remove", "acme-testssl"], input="n\n")

    assert result.exit_code == 0
    assert result.output.endswith("Removal cancelled.\n")


def test_plugin_doctor_exits_nonzero_for_registry_issue(monkeypatch: Any) -> None:
    class FakeLifecycle:
        def package_manager_version(self) -> str:
            return "0.12.3"

        def doctor(self) -> tuple[Any, ...]:
            return (
                SimpleNamespace(
                    plugin_id="acme-testssl",
                    code="missing-python",
                    message="plugin Python does not exist",
                ),
            )

    monkeypatch.setattr(plugin_module, "_new_lifecycle", FakeLifecycle)

    result = CliRunner().invoke(plugin, ["doctor"])

    assert result.exit_code == 1
    assert "uv: 0.12.3" in result.output
    assert "acme-testssl: missing-python: plugin Python does not exist" in result.output
