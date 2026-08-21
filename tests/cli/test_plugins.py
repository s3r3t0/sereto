import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import click
import pytest

import sereto.cli.cli as cli_module


class LogCapture:
    def __init__(self) -> None:
        self.debug_messages: list[str] = []
        self.error_messages: list[str] = []

    def debug(self, message: str, *args: object) -> None:
        self.debug_messages.append(message.format(*args))

    def error(self, message: str, *args: object) -> None:
        self.error_messages.append(message.format(*args))


@pytest.fixture(autouse=True)
def isolate_plugins_package() -> None:
    original_path = sys.path.copy()
    original_modules = {
        name: module for name, module in sys.modules.items() if name == "plugins" or name.startswith("plugins.")
    }
    for name in original_modules:
        del sys.modules[name]
    importlib.invalidate_caches()

    yield

    for name in list(sys.modules):
        if name == "plugins" or name.startswith("plugins."):
            del sys.modules[name]
    sys.modules.update(original_modules)
    sys.path[:] = original_path
    importlib.invalidate_caches()


@pytest.fixture
def command_group() -> click.Group:
    group = click.Group(name="sereto")
    group.add_command(click.Group(name="findings"))
    return group


@pytest.fixture
def plugins_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "plugins"
    directory.mkdir()
    (directory / "__init__.py").write_text("", encoding="utf-8")
    return directory


@pytest.fixture
def log_capture(monkeypatch: pytest.MonkeyPatch) -> LogCapture:
    capture = LogCapture()
    monkeypatch.setattr(cli_module, "logger", capture)
    return capture


def write_plugin(plugins_dir: Path, relative_path: str, source: str) -> None:
    path = plugins_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_load_plugins_skips_disabled_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.touch()
    settings = SimpleNamespace(plugins=SimpleNamespace(enabled=False))
    called = False

    def load_from_directory(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(cli_module.Settings, "get_path", lambda: settings_path)
    monkeypatch.setattr(cli_module.Settings, "load_from", lambda _path: settings)
    monkeypatch.setattr(cli_module, "_load_plugins_from_directory", load_from_directory)

    cli_module.load_plugins()

    assert not called


def test_load_plugins_uses_configured_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.touch()
    templates_path = tmp_path / "templates"
    plugins_dir = templates_path / "plugins"
    plugins_dir.mkdir(parents=True)
    settings = SimpleNamespace(
        plugins=SimpleNamespace(enabled=True, directory="%TEMPLATES%/plugins"),
        templates_path=templates_path,
    )
    captured: dict[str, object] = {}

    def load_from_directory(*, plugins_dir: Path, command_group: click.Group) -> None:
        captured["plugins_dir"] = plugins_dir
        captured["command_group"] = command_group

    monkeypatch.setattr(cli_module.Settings, "get_path", lambda: settings_path)
    monkeypatch.setattr(cli_module.Settings, "load_from", lambda _path: settings)
    monkeypatch.setattr(cli_module, "_load_plugins_from_directory", load_from_directory)

    cli_module.load_plugins()

    assert captured == {"plugins_dir": plugins_dir, "command_group": cli_module.cli}


def test_load_plugins_registers_package_with_relative_import(
    command_group: click.Group, log_capture: LogCapture, plugins_dir: Path
) -> None:
    write_plugin(
        plugins_dir,
        "relative_plugin/__init__.py",
        "from .commands import relative\n\n"
        "def register_commands(cli):\n"
        '    cli.commands["findings"].add_command(relative)\n',
    )
    write_plugin(
        plugins_dir,
        "relative_plugin/commands.py",
        "import click\n\n@click.command()\ndef relative():\n    pass\n",
    )

    cli_module._load_plugins_from_directory(plugins_dir, command_group)

    findings = command_group.commands["findings"]
    assert isinstance(findings, click.Group)
    assert "relative" in findings.commands
    assert log_capture.error_messages == []
    assert log_capture.debug_messages == ["Plugin registered: 'relative_plugin'"]


def test_load_plugins_registers_files_in_name_order(command_group: click.Group, plugins_dir: Path) -> None:
    write_plugin(
        plugins_dir,
        "zeta.py",
        "import click\n\n"
        "@click.command()\n"
        "def zeta():\n"
        "    pass\n\n"
        "def register_commands(cli):\n"
        "    cli.add_command(zeta)\n",
    )
    write_plugin(
        plugins_dir,
        "alpha.py",
        "import click\n\n"
        "@click.command()\n"
        "def alpha():\n"
        "    pass\n\n"
        "def register_commands(cli):\n"
        "    cli.add_command(alpha)\n",
    )

    cli_module._load_plugins_from_directory(plugins_dir, command_group)

    assert list(command_group.commands) == ["findings", "alpha", "zeta"]


@pytest.mark.parametrize(
    ("source", "expected_message"),
    [
        ("value = 1\n", "Plugin 'missing.py' does not define register_commands(cli)."),
        ("register_commands = 1\n", "Plugin 'not_callable.py': register_commands must be callable."),
    ],
)
def test_load_plugins_reports_invalid_registration_contract(
    command_group: click.Group,
    expected_message: str,
    log_capture: LogCapture,
    plugins_dir: Path,
    source: str,
) -> None:
    file_name = "missing.py" if "does not define" in expected_message else "not_callable.py"
    write_plugin(plugins_dir, file_name, source)

    cli_module._load_plugins_from_directory(plugins_dir, command_group)

    assert log_capture.error_messages == [expected_message]


def test_load_plugins_reports_import_and_registration_failures(
    command_group: click.Group, log_capture: LogCapture, plugins_dir: Path
) -> None:
    write_plugin(plugins_dir, "broken_import.py", 'raise RuntimeError("import boom")\n')
    write_plugin(
        plugins_dir,
        "broken_registration.py",
        'def register_commands(cli):\n    raise RuntimeError("registration boom")\n',
    )

    cli_module._load_plugins_from_directory(plugins_dir, command_group)

    assert log_capture.error_messages == [
        "Failed to load plugin 'broken_import.py': RuntimeError: import boom",
        "Failed to register plugin 'broken_registration.py': RuntimeError: registration boom",
    ]
