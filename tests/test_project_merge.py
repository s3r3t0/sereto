import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from textual.app import App
from textual.widgets import Button, DataTable, Static

from sereto.project_merge import (
    DateKey,
    FindingKey,
    MergeDate,
    MergeSource,
    MergeStatus,
    TargetKey,
    apply_entity_merge,
    discover_merge_dates,
    discover_merge_findings,
    discover_merge_people,
    discover_merge_targets,
)
from sereto.tui.merge import ConflictResolutionScreen, MergeUnpackedScreen


class _MergeTestApp(App[None]):
    CSS_PATH = "../sereto/tui/merge.tcss"

    def __init__(self, screen: MergeUnpackedScreen) -> None:
        super().__init__()
        self.merge_screen = screen

    def on_mount(self) -> None:
        self.push_screen(self.merge_screen)


def _write(project_dir: Path, relative_path: str, content: str) -> None:
    path = project_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_config(project_dir: Path, targets: list[dict[str, Any]], **extra: Any) -> None:
    config = {
        "sereto_version": "1.0.0",
        "version_configs": {
            "v1.0": {
                "id": "project",
                "name": "Project",
                "version_description": "Initial",
                "targets": targets,
                "dates": [],
                "people": [],
                **extra,
            }
        },
    }
    _write(project_dir, "config.json", json.dumps(config))


def _target(category: str, name: str, **extra: Any) -> dict[str, Any]:
    return {"category": category, "name": name, "locators": [], "documents": [], **extra}


def test_discovers_targets_and_findings_with_project_provenance(tmp_path: Path) -> None:
    local_dir = tmp_path / "local"
    unpacked_dir = tmp_path / "unpacked"
    _write_config(local_dir, [_target("dast", "Shared"), _target("sast", "Local")])
    _write_config(unpacked_dir, [_target("dast", "Shared"), _target("mobile", "Unpacked")])
    _write(local_dir, "target_dast_shared/findings.toml", '[group]\nfindings = ["local", "shared"]\n')
    _write(unpacked_dir, "target_dast_shared/findings.toml", '[group]\nfindings = ["shared", "unpacked"]\n')
    _write(local_dir, "target_sast_local/findings.toml", '[group]\nfindings = ["local-only"]\n')
    _write(unpacked_dir, "target_mobile_unpacked/findings.toml", '[group]\nfindings = ["new"]\n')

    targets = discover_merge_targets(local_dir, unpacked_dir)
    findings = discover_merge_findings(local_dir, unpacked_dir, targets, {target.key for target in targets})

    assert [(target.key.category, target.key.name, target.in_local, target.in_unpacked) for target in targets] == [
        ("dast", "Shared", True, True),
        ("mobile", "Unpacked", False, True),
        ("sast", "Local", True, False),
    ]
    shared_findings = [finding for finding in findings if finding.key.target == TargetKey("v1.0", "dast", "Shared")]
    assert [(finding.key.name, finding.in_local, finding.in_unpacked) for finding in shared_findings] == [
        ("local", True, False),
        ("shared", True, True),
        ("unpacked", False, True),
    ]


def test_discovers_and_selectively_merges_dates_and_people(tmp_path: Path) -> None:
    local_dir = tmp_path / "local"
    unpacked_dir = tmp_path / "unpacked"
    local_date = {"type": "review", "date": "01-Jan-2026"}
    changed_local_date = {"type": "review", "date": "02-Jan-2026"}
    unpacked_date = {"type": "report_sent", "date": "03-Jan-2026"}
    _write_config(
        local_dir,
        [],
        dates=[local_date],
        people=[
            {"type": "author", "name": "Alice", "email": "alice@example.com"},
            {"type": "reviewer", "name": "Local only"},
        ],
    )
    _write_config(
        unpacked_dir,
        [],
        dates=[changed_local_date, unpacked_date],
        people=[
            {"type": "author", "name": "Alice", "email": "alice@example.com", "role": "Lead"},
            {"type": "reviewer", "name": "Alice", "email": "other@example.com"},
            {"type": "reviewer", "name": "No email"},
        ],
    )

    dates = discover_merge_dates(local_dir, unpacked_dir)
    people = discover_merge_people(local_dir, unpacked_dir)
    statuses = {record.key: record.default_status for record in [*dates, *people]}
    statuses[dates[1].key] = MergeStatus.UNPACKED

    assert [(date.key.type, date.source, date.available_statuses) for date in dates] == [
        ("report_sent", MergeSource.UNPACKED, (MergeStatus.UNPACKED, MergeStatus.EXCLUDED)),
        ("review", MergeSource.BOTH, (MergeStatus.LOCAL, MergeStatus.UNPACKED)),
    ]
    assert [
        ((person.local or person.unpacked)["name"], person.source, person.default_status) for person in people
    ] == [
        ("Alice", MergeSource.BOTH, MergeStatus.MERGED),
        ("Local only", MergeSource.LOCAL, MergeStatus.LOCAL),
        ("Alice", MergeSource.UNPACKED, MergeStatus.UNPACKED),
        ("No email", MergeSource.UNPACKED, MergeStatus.UNPACKED),
    ]

    apply_entity_merge(local_dir, unpacked_dir, dates, people, [], [], statuses)

    version_config = json.loads((local_dir / "config.json").read_text())["version_configs"]["v1.0"]
    assert version_config["dates"] == [changed_local_date, unpacked_date]
    assert version_config["people"] == [
        {"type": "author", "name": "Alice", "email": "alice@example.com", "role": "Lead"},
        {"type": "reviewer", "name": "Local only"},
        {"type": "reviewer", "name": "Alice", "email": "other@example.com"},
        {"type": "reviewer", "name": "No email"},
    ]


def test_apply_entity_merge_uses_selected_record_versions(tmp_path: Path) -> None:
    local_dir = tmp_path / "local"
    unpacked_dir = tmp_path / "unpacked"
    _write_config(local_dir, [_target("dast", "Shared"), _target("sast", "Remove")])
    _write_config(unpacked_dir, [_target("dast", "Shared"), _target("mobile", "Add")])
    _write(local_dir, "target_dast_shared/findings.toml", '[group]\nfindings = ["remove", "shared"]\n')
    _write(unpacked_dir, "target_dast_shared/findings.toml", '[group]\nfindings = ["shared", "add"]\n')
    _write(local_dir, "target_dast_shared/findings/remove.md.j2", "remove")
    _write(local_dir, "target_dast_shared/findings/shared.md.j2", "heading\nlocal\ncommon\n")
    _write(unpacked_dir, "target_dast_shared/findings/shared.md.j2", "heading\ncommon\nunpacked\n")
    _write(unpacked_dir, "target_dast_shared/findings/add.md.j2", "added")
    _write(local_dir, "target_sast_remove/findings.toml", '[group]\nfindings = ["old"]\n')
    _write(unpacked_dir, "target_mobile_add/findings.toml", '[group]\nfindings = ["new"]\n')
    _write(unpacked_dir, "target_mobile_add/findings/new.md.j2", "new")
    _write(unpacked_dir, "pictures/unpacked.png", "picture")

    targets = discover_merge_targets(local_dir, unpacked_dir)
    findings = discover_merge_findings(local_dir, unpacked_dir, targets, {target.key for target in targets})
    statuses = {record.key: record.default_status for record in [*targets, *findings]}
    statuses[FindingKey(TargetKey("v1.0", "dast", "Shared"), "shared")] = MergeStatus.UNPACKED

    apply_entity_merge(
        local_dir,
        unpacked_dir,
        [],
        [],
        targets,
        findings,
        statuses,
    )

    config = json.loads((local_dir / "config.json").read_text(encoding="utf-8"))
    assert [target["name"] for target in config["version_configs"]["v1.0"]["targets"]] == [
        "Shared",
        "Remove",
        "Add",
    ]
    assert (local_dir / "target_sast_remove").exists()
    assert (local_dir / "target_mobile_add/findings/new.md.j2").read_text(encoding="utf-8") == "new"
    assert (local_dir / "target_dast_shared/findings/remove.md.j2").read_text(encoding="utf-8") == "remove"
    assert (local_dir / "target_dast_shared/findings/add.md.j2").read_text(encoding="utf-8") == "added"
    assert (local_dir / "target_dast_shared/findings/shared.md.j2").read_text(encoding="utf-8") == (
        "heading\ncommon\nunpacked\n"
    )
    assert (local_dir / "pictures/unpacked.png").is_file()


def test_merge_tui_resolves_conflicting_fields_and_applies(tmp_path: Path) -> None:
    local_dir = tmp_path / "local"
    unpacked_dir = tmp_path / "unpacked"
    local_person = {
        "type": "author",
        "name": "Alice",
        "email": "alice@example.com",
        "role": "Security Analyst",
    }
    unpacked_person = {**local_person, "role": "Lead"}
    _write_config(local_dir, [], people=[local_person])
    _write_config(unpacked_dir, [], people=[unpacked_person])

    async def run_app() -> None:
        screen = MergeUnpackedScreen(local_dir, unpacked_dir)
        app = _MergeTestApp(screen)
        async with app.run_test() as pilot:
            table = screen.query_one("#merge-table", DataTable)
            person = screen.people[0]
            assert [str(column.label) for column in table.columns.values()] == [
                "Local Project",
                "Unpacked Project",
                "Status",
                "Action",
            ]
            assert screen._status_label(person) == "Conflict"
            assert screen.query_one("#merge-apply").disabled
            await pilot.click("#merge-table", offset=(table.size.width - 5, 2))
            assert isinstance(app.screen, ConflictResolutionScreen)
            await pilot.press("escape")
            assert person.key not in screen.resolved_values
            assert screen.query_one("#merge-apply").disabled
            await pilot.press("enter")
            await pilot.click("#conflict-choice-unpacked-3")
            await pilot.click("#conflict-apply")
            assert screen.resolved_values[person.key] == unpacked_person
            assert screen._status_label(person) == "Resolved"
            assert not screen.query_one("#merge-apply").disabled
            await pilot.press("enter")
            assert isinstance(app.screen, ConflictResolutionScreen)
            assert app.screen.choices[3] == "unpacked"
            await pilot.press("escape")
            await pilot.press("ctrl+s")

    asyncio.run(run_app())

    config = json.loads((local_dir / "config.json").read_text(encoding="utf-8"))
    assert config["version_configs"]["v1.0"]["people"] == [unpacked_person]


def test_comparison_and_exclusion_statuses() -> None:
    key = DateKey("v1.0", "review")
    value = {"type": "review", "date": "01-Jan-2026"}
    identical = MergeDate(key, value, value, value)
    conflict = MergeDate(key, value, {**value, "date": "02-Jan-2026"}, None)
    local = MergeDate(key, value, None, None)
    assert identical.is_identical and not identical.is_conflict
    assert conflict.is_conflict and not conflict.is_identical
    assert local.available_statuses == (MergeStatus.LOCAL, MergeStatus.EXCLUDED)
    with pytest.raises(ValueError, match="excluded"):
        local.value_for(MergeStatus.EXCLUDED)


def test_exclusions_apply_to_config_targets_and_findings(tmp_path: Path) -> None:
    local_dir, unpacked_dir = tmp_path / "local", tmp_path / "unpacked"
    _write_config(
        local_dir,
        [_target("dast", "Shared"), _target("sast", "Local")],
        dates=[{"type": "review", "date": "01-Jan-2026"}],
        people=[{"type": "author", "name": "Local"}],
    )
    _write_config(
        unpacked_dir,
        [_target("dast", "Shared"), _target("mobile", "Incoming"), _target("sast", "Ignored")],
        people=[{"type": "reviewer", "name": "Incoming"}],
    )
    _write(local_dir, "target_dast_shared/findings.toml", '[group]\nfindings = ["local"]\n')
    _write(local_dir, "target_dast_shared/findings/local.md.j2", "local")
    _write(unpacked_dir, "target_mobile_incoming/findings.toml", '[group]\nfindings = ["keep", "skip"]\n')
    _write(unpacked_dir, "target_mobile_incoming/findings/keep.md.j2", "keep")
    _write(unpacked_dir, "target_mobile_incoming/findings/skip.md.j2", "skip")
    _write(unpacked_dir, "target_sast_ignored/findings.toml", '[group]\nfindings = ["skip"]\n')
    dates = discover_merge_dates(local_dir, unpacked_dir)
    people = discover_merge_people(local_dir, unpacked_dir)
    targets = discover_merge_targets(local_dir, unpacked_dir)
    findings = discover_merge_findings(local_dir, unpacked_dir, targets, {target.key for target in targets})
    statuses = {record.key: record.default_status for record in [*dates, *people, *targets, *findings]}
    for record in [*dates, *people]:
        statuses[record.key] = MergeStatus.EXCLUDED
    for target in targets:
        if target.key.name in ("Local", "Ignored"):
            statuses[target.key] = MergeStatus.EXCLUDED
    for finding in findings:
        if finding.key.name in ("local", "skip"):
            statuses[finding.key] = MergeStatus.EXCLUDED
    apply_entity_merge(local_dir, unpacked_dir, dates, people, targets, findings, statuses)
    config = json.loads((local_dir / "config.json").read_text())["version_configs"]["v1.0"]
    assert config["dates"] == []
    assert config["people"] == []
    assert [target["name"] for target in config["targets"]] == ["Shared", "Incoming"]
    assert not (local_dir / "target_sast_ignored").exists()
    assert (local_dir / "target_mobile_incoming/findings/keep.md.j2").read_text() == "keep"
    assert not (local_dir / "target_mobile_incoming/findings/skip.md.j2").exists()
    assert "local" not in (local_dir / "target_dast_shared/findings.toml").read_text()
    assert (local_dir / "target_dast_shared/findings/local.md.j2").read_text() == "local"


def test_modal_requires_choices_and_preserves_nested_values() -> None:
    local = {"name": "Local", "nested": {"shared": "same", "text": "old"}, "only_local": False}
    incoming = {"name": "Incoming", "nested": {"shared": "same", "text": "new"}, "only_incoming": None}
    expected = {
        "name": "Local",
        "nested": {"shared": "same", "text": "new"},
        "only_local": False,
        "only_incoming": None,
    }

    async def run_app() -> None:
        app = App()
        async with app.run_test(size=(120, 40)) as pilot:
            modal = ConflictResolutionScreen("[literal]", local, incoming, None)
            await app.push_screen(modal)
            await pilot.pause()
            assert modal.query_one("#conflict-apply", Button).disabled
            await pilot.click("#conflict-choice-local-0")
            assert modal.query_one("#conflict-apply", Button).disabled
            await pilot.click("#conflict-choice-unpacked-2")
            assert not modal.query_one("#conflict-apply", Button).disabled
            assert modal._build_result() == expected
            assert str(modal.query_one("#conflict-result-2", Static).render()) == '"new"'
            await pilot.click("#conflict-cancel")
            assert app.screen is not modal
            restored = ConflictResolutionScreen("Restored", local, incoming, expected)
            assert restored._all_fields_selected()
            assert restored._build_result() == expected
            assert local["nested"]["text"] == "old"

    asyncio.run(run_app())


def test_tui_shows_side_specific_values_and_toggles_one_sided_records(tmp_path: Path) -> None:
    local_dir, unpacked_dir = tmp_path / "local", tmp_path / "unpacked"
    _write_config(
        local_dir,
        [_target("dast", "Local")],
        people=[
            {"type": "author", "name": "Alice", "email": "alice@example.com"},
            {"type": "reviewer", "name": "Same", "email": "same@example.com"},
        ],
    )
    _write_config(
        unpacked_dir,
        [],
        people=[
            {"type": "author", "name": "Alicia", "email": "alice@example.com"},
            {"type": "reviewer", "name": "Same", "email": "same@example.com"},
        ],
    )
    _write(local_dir, "target_dast_local/findings.toml", '[group]\nfindings = ["local"]\n')

    async def run_app() -> None:
        screen = MergeUnpackedScreen(local_dir, unpacked_dir)
        async with _MergeTestApp(screen).run_test(size=(120, 40)) as pilot:
            table = screen.query_one("#merge-table", DataTable)
            assert "Alice" in str(table.get_cell("0", "local"))
            assert "Alicia" in str(table.get_cell("0", "unpacked"))
            assert table.get_cell("1", "status") == "Identical"
            assert table.get_cell("1", "action") == "—"
            table.move_cursor(row=2, column=3)
            await pilot.press("enter")
            assert table.get_cell("2", "status") == "Excluded"
            assert table.get_cell("3", "status") == "Excluded"
            assert table.get_cell("3", "action") == "Include target first"
            await pilot.press("space")
            assert table.get_cell("2", "status") == "Local only"
            assert table.get_cell("3", "status") == "Local only"
            await pilot.resize_terminal(80, 24)
            assert len(table.columns) == 4
            assert table.virtual_size.width <= table.content_size.width
            await pilot.press("escape")

    asyncio.run(run_app())


def test_tui_cycles_mergeable_sources_and_cancellation_does_not_write(tmp_path: Path) -> None:
    local_dir, unpacked_dir = tmp_path / "local", tmp_path / "unpacked"
    person = {"type": "author", "name": "Alice", "email": "alice@example.com"}
    _write_config(local_dir, [], people=[person])
    _write_config(unpacked_dir, [], people=[{**person, "role": "Lead"}])
    original = (local_dir / "config.json").read_bytes()

    async def run_app() -> None:
        screen = MergeUnpackedScreen(local_dir, unpacked_dir)
        async with _MergeTestApp(screen).run_test() as pilot:
            table = screen.query_one("#merge-table", DataTable)
            table.move_cursor(column=3)
            for status in (MergeStatus.LOCAL, MergeStatus.UNPACKED, MergeStatus.MERGED):
                await pilot.press("enter")
                assert screen.statuses[screen.people[0].key] is status
            await pilot.press("escape")

    asyncio.run(run_app())
    assert (local_dir / "config.json").read_bytes() == original


def test_modal_preserves_complete_finding_content() -> None:
    local = b"# Finding\n" + b"local details\n" * 20
    incoming = b"# Finding\n" + b"incoming details\n" * 20
    modal = ConflictResolutionScreen("Finding", local, incoming, None)
    assert not modal._all_fields_selected()
    assert local.decode() in modal._button_label(0, "local").plain
    modal.choices[0] = "unpacked"
    assert modal._build_result() == incoming

    async def run_app() -> None:
        async with App().run_test(size=(120, 40)) as pilot:
            await pilot.app.push_screen(modal)
            await pilot.pause()
            assert modal.query_one("#conflict-choice-local-0", Button).content_size.height >= 20
            await pilot.press("escape")

    asyncio.run(run_app())


def test_invalid_resolution_is_rejected_before_writing(tmp_path: Path) -> None:
    local_dir, unpacked_dir = tmp_path / "local", tmp_path / "unpacked"
    _write_config(local_dir, [], dates=[{"type": "review", "date": "01-Jan-2026"}])
    _write_config(unpacked_dir, [], dates=[{"type": "review", "date": "02-Jan-2026"}])
    original = (local_dir / "config.json").read_bytes()
    dates = discover_merge_dates(local_dir, unpacked_dir)
    with pytest.raises(ValueError):
        apply_entity_merge(
            local_dir,
            unpacked_dir,
            dates,
            [],
            [],
            [],
            {},
            {dates[0].key: {"type": "review", "date": "invalid"}},
        )
    assert (local_dir / "config.json").read_bytes() == original


def test_tui_reports_apply_errors(tmp_path: Path, monkeypatch) -> None:
    local_dir, unpacked_dir = tmp_path / "local", tmp_path / "unpacked"
    _write_config(local_dir, [])
    _write_config(unpacked_dir, [])

    def fail(*args):
        raise OSError("Cannot write project")

    monkeypatch.setattr("sereto.tui.merge.apply_entity_merge", fail)
    notifications = []

    async def run_app() -> None:
        screen = MergeUnpackedScreen(local_dir, unpacked_dir)
        monkeypatch.setattr(screen, "notify", lambda message, **kwargs: notifications.append((message, kwargs)))
        app = _MergeTestApp(screen)
        async with app.run_test() as pilot:
            await pilot.press("ctrl+s")
            assert app.screen is screen
            assert notifications[0][1]["severity"] == "error"
            assert "Cannot write project" in notifications[0][0]

    asyncio.run(run_app())
