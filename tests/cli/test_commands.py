from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from sereto.cli.commands import repl_cd
from sereto.project import Project


@pytest.fixture
def settings_stub(tmp_path: Path) -> SimpleNamespace:
    templates_path = tmp_path / "templates"
    templates_path.mkdir()
    return SimpleNamespace(
        projects_path=tmp_path,
        templates_path=templates_path,
        risk_due_dates={},
    )


def test_repl_cd_delegates_to_resolver(monkeypatch: pytest.MonkeyPatch, settings_stub: SimpleNamespace):
    project = Project(_settings=settings_stub)
    resolved_path = settings_stub.projects_path / "resolved"
    resolved_path.mkdir()

    calls: dict[str, object] = {}

    def fake_resolver(**kwargs):
        calls.update(kwargs)
        return resolved_path

    monkeypatch.setattr("sereto.cli.commands.resolve_project_directory", fake_resolver)

    changed_paths: list[Path] = []

    def fake_change(self, dst: Path) -> None:  # type: ignore[override]
        changed_paths.append(dst)

    monkeypatch.setattr("sereto.cli.commands.WorkingDir.change", fake_change, raising=True)

    runner = CliRunner()
    result = runner.invoke(repl_cd, ["PROJECT-123"], obj=project)

    assert result.exit_code == 0
    assert changed_paths == [resolved_path]
    assert calls["projects_path"] == settings_stub.projects_path
    assert calls["project_id"] == "PROJECT-123"
    assert calls["templates_path"] == settings_stub.templates_path
