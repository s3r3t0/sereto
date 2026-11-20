from threading import Event

import pytest

from sereto.tui.watcher import ProjectsDirWatcher


@pytest.mark.parametrize("identity_file", ["config.json", ".sereto"])
def test_project_identity_changes_detected_after_directory_replacement(tmp_path, monkeypatch, identity_file):
    project = tmp_path / "PRJ"
    project.mkdir()
    (project / "config.json").write_text("{}")
    (project / ".sereto").touch()
    changed = Event()
    watcher = ProjectsDirWatcher(tmp_path, changed.set)
    monkeypatch.setattr(watcher, "is_relevant", lambda path: path == project / identity_file)

    watcher.start()
    try:
        project.rename(tmp_path / "OLD")
        project.mkdir()
        (project / "config.json").write_text("{}")
        (project / ".sereto").touch()
        watcher.sync_project_dirs()
        changed.clear()

        if identity_file == "config.json":
            (project / identity_file).write_text('{"name": "Changed"}')
        else:
            (project / identity_file).unlink()

        assert changed.wait(timeout=5), "The replaced project's identity-file change was not detected"
    finally:
        watcher.stop()
