import hashlib
import json
import os
import re
import stat
from dataclasses import replace
from pathlib import Path

import pytest

import sereto.file_transaction as file_transaction
from sereto.enums import Risk
from sereto.exceptions import SeretoRuntimeError, SeretoValueError
from sereto.file_transaction import AtomicFileTransaction, ProjectFileLock
from sereto.finding import Findings, NewGroupDestination, SubFinding
from sereto.models.locator import HostnameLocatorModel


def _write_template(templates: Path) -> Path:
    template_path = templates / "categories" / "test" / "findings" / "prepared.md.j2"
    template_path.parent.mkdir(parents=True)
    template_path.write_text(
        """+++
name = "Prepared Finding"
risk = "medium"

[[variables]]
name = "proof"
description = "Finding evidence"
required = true
type = "string"

[[variables]]
name = "count"
description = "Occurrence count"
type = "integer"

[[variables]]
name = "flags"
description = "Validation flags"
list = true
type = "boolean"
+++

Prepared finding body: {{ proof }}
""",
        encoding="utf-8",
    )
    return template_path


def _make_findings(tmp_path: Path) -> tuple[Findings, Path, Path]:
    templates = tmp_path / "templates"
    template_path = _write_template(templates)
    target_dir = tmp_path / "project" / "target_test_example"
    (target_dir / "findings").mkdir(parents=True)
    (target_dir / "findings.toml").write_text("", encoding="utf-8")
    findings = Findings(groups=[], target_dir=target_dir, target_locators=[])
    return findings, templates, template_path


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_prepare_from_template_does_not_write_project_files(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    config_before = findings.config_file.read_bytes()

    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "validated"},
    )

    assert prepared.sub_finding_path == findings.findings_dir / "test_prepared_finding.md.j2"
    assert 'name = "Prepared Finding"' in prepared.sub_finding_content
    assert 'proof = "validated"' in prepared.sub_finding_content
    assert prepared.registration == NewGroupDestination(name="Prepared Finding")
    assert prepared.templates_root == templates.resolve()
    assert not prepared.sub_finding_path.exists()
    assert findings.config_file.read_bytes() == config_before
    assert list(findings.findings_dir.iterdir()) == []


def test_commit_prepared_persists_finding_and_config(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "validated"},
    )

    findings.commit_prepared(prepared)

    assert prepared.sub_finding_path.read_text(encoding="utf-8") == prepared.sub_finding_content
    assert findings.config_file.read_text(encoding="utf-8")
    assert len(findings.groups) == 1
    assert findings.groups[0].name == "Prepared Finding"
    assert [finding.name for finding in findings.groups[0].sub_findings] == ["Prepared Finding"]


def test_commit_prepared_merges_unrelated_group_added_after_preparation(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "prepared"},
    )
    findings.add_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        sub_finding_name="Concurrent Finding",
        variables={"proof": "concurrent"},
    )

    findings.commit_prepared(prepared)

    assert [group.name for group in findings.groups] == ["Concurrent Finding", "Prepared Finding"]
    assert sorted(path.name for path in findings.findings_dir.iterdir()) == [
        "test_concurrent_finding.md.j2",
        "test_prepared_finding.md.j2",
    ]


def test_add_from_template_uses_validated_commit_boundary(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)

    findings.add_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "validated"},
    )

    finding_path = findings.findings_dir / "test_prepared_finding.md.j2"
    assert finding_path.is_file()
    assert len(findings.groups) == 1
    assert findings.groups[0].sub_findings[0].path == finding_path


def test_add_from_template_overwrite_without_existing_file_creates_group(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)

    findings.add_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "validated"},
        overwrite=True,
    )

    assert len(findings.groups) == 1
    assert len(findings.groups[0].sub_findings) == 1


def test_add_from_template_collision_uses_unique_file_in_same_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    monkeypatch.setattr("sereto.finding.random.choices", lambda *args, **kwargs: list("abc12"))

    for proof in ("first", "second"):
        findings.add_from_template(
            templates=templates,
            template_path=template_path,
            category="test",
            variables={"proof": proof},
        )

    assert sorted(path.name for path in findings.findings_dir.iterdir()) == [
        "test_prepared_finding.md.j2",
        "test_prepared_finding_abc12.md.j2",
    ]
    assert len(findings.groups) == 1
    assert len(findings.groups[0].sub_findings) == 2


def test_add_from_template_overwrites_existing_finding_without_changing_group(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    findings.add_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "first"},
    )
    config_before = findings.config_file.read_bytes()

    findings.add_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "replacement"},
        overwrite=True,
    )

    assert findings.config_file.read_bytes() == config_before
    assert len(findings.groups) == 1
    assert len(findings.groups[0].sub_findings) == 1
    assert findings.groups[0].sub_findings[0].vars == {"proof": "replacement"}


def test_prepare_from_template_rejects_ambiguous_group_selection(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    findings.add_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "first"},
    )
    project_before = _snapshot_tree(findings.target_dir.parent)

    with pytest.raises(SeretoValueError, match="group_uname and group_name are mutually exclusive"):
        findings.prepare_from_template(
            templates=templates,
            template_path=template_path,
            category="test",
            variables={"proof": "second"},
            group_uname=findings.groups[0].uname,
            group_name="Ignored group",
        )

    assert _snapshot_tree(findings.target_dir.parent) == project_before


def test_prepare_from_template_rejects_template_outside_root(tmp_path: Path) -> None:
    findings, templates, _ = _make_findings(tmp_path)
    external_templates = tmp_path / "external-templates"
    external_template = _write_template(external_templates)
    project_before = _snapshot_tree(findings.target_dir.parent)

    with pytest.raises(SeretoValueError, match="template is outside the templates directory"):
        findings.prepare_from_template(
            templates=templates,
            template_path=external_template,
            category="test",
            variables={"proof": "validated"},
        )

    assert _snapshot_tree(findings.target_dir.parent) == project_before


def test_prepare_from_template_appends_to_selected_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    findings.add_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "first"},
        group_name="Selected group",
    )
    monkeypatch.setattr("sereto.finding.random.choices", lambda *args, **kwargs: list("group"))

    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "second"},
        group_uname=findings.groups[0].uname,
    )
    findings.commit_prepared(prepared)

    assert len(findings.groups) == 1
    assert findings.groups[0].name == "Selected group"
    assert len(findings.groups[0].sub_findings) == 2


def test_commit_prepared_preserves_concurrent_append_to_selected_group(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    findings.add_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        sub_finding_name="Base finding",
        variables={"proof": "base"},
        group_name="Selected group",
    )
    group_uname = findings.groups[0].uname
    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        sub_finding_name="Prepared append",
        variables={"proof": "prepared"},
        group_uname=group_uname,
    )
    findings.add_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        sub_finding_name="Concurrent append",
        variables={"proof": "concurrent"},
        group_uname=group_uname,
    )

    findings.commit_prepared(prepared)

    assert [finding.name for finding in findings.groups[0].sub_findings] == [
        "Base finding",
        "Concurrent append",
        "Prepared append",
    ]


@pytest.mark.parametrize("config_change", ["delete", "rename"])
def test_commit_prepared_rejects_selected_group_identity_change(
    tmp_path: Path,
    config_change: str,
) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    findings.add_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        sub_finding_name="Base finding",
        variables={"proof": "base"},
        group_name="Selected group",
    )
    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        sub_finding_name="Prepared append",
        variables={"proof": "prepared"},
        group_uname=findings.groups[0].uname,
    )
    current_config = findings.config_file.read_text(encoding="utf-8")
    changed_config = "" if config_change == "delete" else current_config.replace("Selected group", "Renamed group")
    findings.config_file.write_text(changed_config, encoding="utf-8")
    project_after_change = _snapshot_tree(findings.target_dir.parent)

    with pytest.raises(SeretoValueError, match="finding group 'Selected group' changed after preparation"):
        findings.commit_prepared(prepared)

    assert _snapshot_tree(findings.target_dir.parent) == project_after_change
    assert not prepared.sub_finding_path.exists()


def test_commit_prepared_rejects_finding_registered_in_another_group(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        sub_finding_name="Contested finding",
        variables={"proof": "prepared"},
        group_name="Prepared group",
    )
    findings.add_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        sub_finding_name="Contested finding",
        variables={"proof": "concurrent"},
        group_name="Concurrent group",
    )
    project_after_change = _snapshot_tree(findings.target_dir.parent)

    with pytest.raises(
        SeretoValueError,
        match="finding 'test_contested_finding' was registered in group 'Concurrent group' after preparation",
    ):
        findings.commit_prepared(prepared)

    assert _snapshot_tree(findings.target_dir.parent) == project_after_change


def test_commit_prepared_merges_same_name_group_created_after_preparation(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        sub_finding_name="Prepared append",
        variables={"proof": "prepared"},
        group_name="Shared group",
    )
    findings.add_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        sub_finding_name="Concurrent append",
        variables={"proof": "concurrent"},
        group_name="Shared group",
    )

    findings.commit_prepared(prepared)

    assert len(findings.groups) == 1
    assert [finding.name for finding in findings.groups[0].sub_findings] == [
        "Concurrent append",
        "Prepared append",
    ]


def test_commit_prepared_can_reject_same_name_group_created_after_preparation(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        sub_finding_name="Prepared append",
        variables={"proof": "prepared"},
        group_name="Shared group",
    )
    prepared = replace(
        prepared,
        registration=NewGroupDestination(name="Shared group", on_conflict="fail"),
    )
    findings.add_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        sub_finding_name="Concurrent append",
        variables={"proof": "concurrent"},
        group_name="Shared group",
    )
    project_after_change = _snapshot_tree(findings.target_dir.parent)

    with pytest.raises(SeretoValueError, match="finding group 'Shared group' was created after preparation"):
        findings.commit_prepared(prepared)

    assert _snapshot_tree(findings.target_dir.parent) == project_after_change
    assert not prepared.sub_finding_path.exists()


def test_prepare_from_template_round_trips_locators(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "validated"},
        locators=[HostnameLocatorModel(value="example.test", description="Affected host")],
    )

    findings.commit_prepared(prepared)

    locators = findings.groups[0].sub_findings[0].locators
    assert [(locator.type, str(locator.value), locator.description) for locator in locators] == [
        ("hostname", "example.test", "Affected host")
    ]


def test_add_from_template_rejects_invalid_variables_before_writes(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    project_before = _snapshot_tree(findings.target_dir.parent)

    with pytest.raises(SeretoValueError, match="unknown variable 'other'"):
        findings.add_from_template(
            templates=templates,
            template_path=template_path,
            category="test",
            variables={"proof": "validated", "other": "unexpected"},
        )

    assert _snapshot_tree(findings.target_dir.parent) == project_before
    assert findings.groups == []


def test_commit_prepared_rolls_back_failed_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "validated"},
    )
    project_root = findings.target_dir.parent
    project_before = _snapshot_tree(project_root)
    real_replace = file_transaction.os.replace

    def fail_config_replacement(source: Path, destination: Path) -> None:
        if Path(destination) == findings.config_file:
            raise OSError("injected replacement failure")
        real_replace(source, destination)

    monkeypatch.setattr(file_transaction.os, "replace", fail_config_replacement)

    with pytest.raises(OSError, match="injected replacement failure"):
        findings.commit_prepared(prepared)

    assert _snapshot_tree(project_root) == project_before
    assert findings.groups == []


def test_commit_prepared_rolls_back_failed_state_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "validated"},
    )
    project_root = findings.target_dir.parent
    project_before = _snapshot_tree(project_root)

    def reject_generated_state(*args: object, **kwargs: object) -> Findings:
        raise SeretoValueError("injected generated-state failure")

    monkeypatch.setattr(Findings, "_load_from_unlocked", reject_generated_state)

    with pytest.raises(SeretoValueError, match="injected generated-state failure"):
        findings.commit_prepared(prepared)

    assert _snapshot_tree(project_root) == project_before
    assert findings.groups == []


def test_commit_prepared_preserves_config_changes_after_preparation(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "validated"},
    )
    findings.config_file.write_text("# newer project state\n", encoding="utf-8")

    findings.commit_prepared(prepared)

    assert findings.config_file.read_text(encoding="utf-8").startswith("# newer project state\n")
    assert prepared.sub_finding_path.is_file()
    assert [group.name for group in findings.groups] == ["Prepared Finding"]


def test_commit_planner_binds_config_digest_to_content_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    real_read_bytes = Path.read_bytes
    changed_config = False

    def change_config_after_read(path: Path) -> bytes:
        nonlocal changed_config
        content = real_read_bytes(path)
        if path == findings.config_file and not changed_config:
            findings.config_file.write_text("# concurrent project state\n", encoding="utf-8")
            changed_config = True
        return content

    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "validated"},
    )
    monkeypatch.setattr(Path, "read_bytes", change_config_after_read)

    with pytest.raises(SeretoRuntimeError, match="file changed after validation"):
        findings.commit_prepared(prepared)

    assert findings.config_file.read_text(encoding="utf-8") == "# concurrent project state\n"
    assert not prepared.sub_finding_path.exists()


def test_prepare_binds_absent_finding_before_commit(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "validated"},
    )
    prepared.sub_finding_path.write_text("concurrent finding\n", encoding="utf-8")

    with pytest.raises(SeretoRuntimeError, match="file changed after validation"):
        findings.commit_prepared(prepared)

    assert prepared.sub_finding_path.read_text(encoding="utf-8") == "concurrent finding\n"
    assert findings.config_file.read_text(encoding="utf-8") == ""


def test_commit_prepared_rejects_draft_from_another_target(tmp_path: Path) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "validated"},
    )
    other_target_dir = findings.target_dir.parent / "target_test_other"
    (other_target_dir / "findings").mkdir(parents=True)
    (other_target_dir / "findings.toml").write_text("", encoding="utf-8")
    other_findings = Findings(groups=[], target_dir=other_target_dir, target_locators=[])
    project_before = _snapshot_tree(findings.target_dir.parent)

    with pytest.raises(SeretoValueError, match="prepared finding belongs to another target"):
        other_findings.commit_prepared(prepared)

    assert _snapshot_tree(findings.target_dir.parent) == project_before
    assert findings.groups == []
    assert other_findings.groups == []


def test_recover_restores_interrupted_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    existing_path = findings.findings_dir / "test_prepared_finding.md.j2"
    existing_path.write_text("original finding\n", encoding="utf-8")
    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "replacement"},
        overwrite=True,
    )
    project_root = findings.target_dir.parent
    project_before = _snapshot_tree(project_root)
    real_write_journal = AtomicFileTransaction._write_journal
    real_recover_transaction = AtomicFileTransaction._recover_transaction

    def interrupt_commit(transaction_dir: Path, state: str, entries: list[dict[str, object]]) -> None:
        if state == "committed":
            raise SystemExit("simulated process interruption")
        real_write_journal(transaction_dir, state, entries)

    def skip_exception_recovery(self: AtomicFileTransaction, transaction_dir: Path) -> None:
        return None

    monkeypatch.setattr(AtomicFileTransaction, "_write_journal", staticmethod(interrupt_commit))
    monkeypatch.setattr(AtomicFileTransaction, "_recover_transaction", skip_exception_recovery)

    with pytest.raises(SystemExit, match="simulated process interruption"):
        findings.commit_prepared(prepared)

    assert existing_path.read_text(encoding="utf-8") == prepared.sub_finding_content

    monkeypatch.setattr(AtomicFileTransaction, "_write_journal", staticmethod(real_write_journal))
    monkeypatch.setattr(AtomicFileTransaction, "_recover_transaction", real_recover_transaction)
    AtomicFileTransaction.recover(project_root)

    assert _snapshot_tree(project_root) == project_before
    assert not (project_root / ".sereto").exists()


def test_load_from_recovers_interrupted_transaction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    existing_path = findings.findings_dir / "test_prepared_finding.md.j2"
    existing_path.write_text("original finding\n", encoding="utf-8")
    prepared = findings.prepare_from_template(
        templates=templates,
        template_path=template_path,
        category="test",
        variables={"proof": "replacement"},
        overwrite=True,
    )
    real_write_journal = AtomicFileTransaction._write_journal
    real_recover_transaction = AtomicFileTransaction._recover_transaction

    def interrupt_commit(transaction_dir: Path, state: str, entries: list[dict[str, object]]) -> None:
        if state == "committed":
            raise SystemExit("simulated process interruption")
        real_write_journal(transaction_dir, state, entries)

    monkeypatch.setattr(AtomicFileTransaction, "_write_journal", staticmethod(interrupt_commit))
    monkeypatch.setattr(AtomicFileTransaction, "_recover_transaction", lambda self, transaction_dir: None)
    with pytest.raises(SystemExit, match="simulated process interruption"):
        findings.commit_prepared(prepared)
    assert existing_path.read_text(encoding="utf-8") == prepared.sub_finding_content

    monkeypatch.setattr(AtomicFileTransaction, "_write_journal", staticmethod(real_write_journal))
    monkeypatch.setattr(AtomicFileTransaction, "_recover_transaction", real_recover_transaction)
    loaded = Findings.load_from(target_dir=findings.target_dir, target_locators=[], templates=templates)

    assert loaded.groups == []
    assert existing_path.read_text(encoding="utf-8") == "original finding\n"
    assert not (findings.target_dir.parent / ".sereto").exists()


def test_recover_rejects_backup_path_outside_transaction(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    target = project_root / "target_test_example" / "findings" / "test_existing.md.j2"
    target.parent.mkdir(parents=True)
    replacement = b"replacement finding\n"
    target.write_bytes(replacement)
    external_backup = project_root / "external-backup"
    external_backup.write_bytes(b"original finding\n")
    transaction_dir = project_root / ".sereto" / "transactions" / "tampered"
    transaction_dir.mkdir(parents=True)
    (transaction_dir / "journal.json").write_text(
        json.dumps(
            {
                "version": 1,
                "state": "applying",
                "entries": [
                    {
                        "path": "target_test_example/findings/test_existing.md.j2",
                        "staged": "staged/0",
                        "backup": "../../../external-backup",
                        "had_original": True,
                        "original_digest": hashlib.sha256(external_backup.read_bytes()).hexdigest(),
                        "replacement_digest": hashlib.sha256(replacement).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SeretoRuntimeError, match="invalid transaction entry"):
        AtomicFileTransaction.recover(project_root)

    assert target.read_bytes() == replacement
    assert external_backup.read_bytes() == b"original finding\n"


def test_recover_rejects_backup_with_wrong_digest(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    target = project_root / "target_test_example" / "findings" / "test_existing.md.j2"
    target.parent.mkdir(parents=True)
    replacement = b"replacement finding\n"
    target.write_bytes(replacement)
    transaction_dir = project_root / ".sereto" / "transactions" / "damaged"
    backup = transaction_dir / "backup" / "0"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"damaged backup\n")
    (transaction_dir / "journal.json").write_text(
        json.dumps(
            {
                "version": 1,
                "state": "applying",
                "entries": [
                    {
                        "path": "target_test_example/findings/test_existing.md.j2",
                        "staged": "staged/0",
                        "backup": "backup/0",
                        "had_original": True,
                        "original_digest": hashlib.sha256(b"original finding\n").hexdigest(),
                        "replacement_digest": hashlib.sha256(replacement).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SeretoRuntimeError, match="transaction backup does not match original file"):
        AtomicFileTransaction.recover(project_root)

    assert target.read_bytes() == replacement


def test_project_file_lock_times_out_on_contention(tmp_path: Path) -> None:
    lock_path = tmp_path / "project.lock"

    with (
        ProjectFileLock(lock_path),
        pytest.raises(SeretoRuntimeError, match="timed out waiting for project lock"),
        ProjectFileLock(lock_path, timeout=0),
    ):
        pytest.fail("second writer acquired the project lock")


@pytest.mark.skipif(os.name == "nt", reason="POSIX ownership and mode check")
def test_project_lock_directories_are_private_with_permissive_umask(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(file_transaction.tempfile, "gettempdir", lambda: str(tmp_path))
    project_root = tmp_path / "project"
    project_root.mkdir()
    previous_umask = os.umask(0)
    try:
        AtomicFileTransaction.recover(project_root)
    finally:
        os.umask(previous_umask)

    lock_root = tmp_path / f"sereto-{os.getuid()}"
    for directory in (lock_root, lock_root / "project-locks"):
        metadata = directory.stat()
        assert metadata.st_uid == os.getuid()
        assert stat.S_IMODE(metadata.st_mode) == 0o700


@pytest.mark.parametrize(
    ("variables", "message"),
    [
        pytest.param({}, "missing required variable 'proof'", id="missing-required"),
        pytest.param(
            {"proof": ""},
            "required variable 'proof' must not be empty",
            id="empty-required",
        ),
        pytest.param(
            {"proof": "validated", "other": "unexpected"},
            "unknown variable 'other'",
            id="unknown",
        ),
        pytest.param({"proof": ["not scalar"]}, "variable 'proof' must be string", id="scalar-shape"),
        pytest.param(
            {"proof": "validated", "count": True},
            "variable 'count' must be integer",
            id="bool-is-not-integer",
        ),
        pytest.param(
            {"proof": "validated", "flags": [True, "not boolean"]},
            "variable 'flags' must be list[boolean]",
            id="list-item-type",
        ),
    ],
)
def test_prepare_from_template_rejects_invalid_variables_without_writes(
    tmp_path: Path,
    variables: dict[str, object],
    message: str,
) -> None:
    findings, templates, template_path = _make_findings(tmp_path)
    config_before = findings.config_file.read_bytes()

    with pytest.raises(SeretoValueError, match=re.escape(message)):
        findings.prepare_from_template(
            templates=templates,
            template_path=template_path,
            category="test",
            variables=variables,
        )

    assert findings.config_file.read_bytes() == config_before
    assert list(findings.findings_dir.iterdir()) == []


def test_sub_finding_validate_vars_uses_strict_template_schema(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    template_path = _write_template(templates)
    sub_finding = SubFinding(
        name="Prepared Finding",
        risk=Risk.medium,
        vars={"proof": 1},
        path=template_path,
        template=template_path,
    )

    with pytest.raises(SeretoValueError, match="variable 'proof' must be string"):
        sub_finding.validate_vars()
