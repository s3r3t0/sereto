from typing import Any

import sereto.cli.cli as cli_module


def test_entry_point_loads_legacy_before_cached_managed_commands(monkeypatch: Any) -> None:
    calls: list[object] = []
    core_paths = frozenset({("findings",)})
    core_commands = ((("findings",), object()),)

    monkeypatch.setattr(cli_module, "setup_logging", lambda: calls.append("logging"))
    monkeypatch.setattr(
        cli_module,
        "collect_group_paths",
        lambda root: calls.append("collect-core") or core_paths,
    )
    monkeypatch.setattr(
        cli_module,
        "snapshot_command_tree",
        lambda root: calls.append("snapshot-core") or core_commands,
    )
    monkeypatch.setattr(
        cli_module,
        "restore_command_tree",
        lambda root, snapshot: calls.append(("restore-core", snapshot)),
    )
    monkeypatch.setattr(cli_module, "load_plugins", lambda: calls.append("legacy"))
    monkeypatch.setattr(
        cli_module,
        "reserved_top_level_paths",
        lambda *names: calls.append(("reserve", names)) or frozenset({("c",), ("cd",), ("exit",), ("log",)}),
    )
    monkeypatch.setattr(
        cli_module,
        "load_cached_plugin_commands",
        lambda root, allowed_parent_paths, reserved_paths: calls.append(
            ("managed", allowed_parent_paths, reserved_paths)
        ),
    )
    monkeypatch.setattr(cli_module, "cli", lambda: calls.append("invoke"))

    cli_module.entry_point()

    assert calls == [
        "logging",
        "snapshot-core",
        "collect-core",
        ("reserve", ("cd", "exit", "log")),
        "legacy",
        ("restore-core", core_commands),
        ("managed", core_paths, frozenset({("c",), ("cd",), ("exit",), ("log",)})),
        "invoke",
    ]
