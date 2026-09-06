import json
from pathlib import Path

import pytest

import sereto.file_transaction as file_transaction
import sereto.package_plugins.proposals as proposals_module
from sereto.exceptions import SeretoValueError
from sereto.finding import ExistingGroupDestination, Findings
from sereto.models.finding import SubFindingFrontmatterModel
from sereto.models.target import TargetModel
from sereto.models.version import ProjectVersion
from sereto.package_plugins.proposals import ProposalOrigin, prepare_finding_proposals, review_finding_proposals
from sereto.package_plugins.protocol_v1 import FindingProposal, OperationResultPayload
from sereto.package_plugins.resources import TargetResources
from sereto.target import Target


def _write_template(templates: Path) -> Path:
    template = templates / "categories" / "infrastructure" / "findings" / "weak_tls.md.j2"
    template.parent.mkdir(parents=True)
    template.write_text(
        """+++
name = "Weak TLS"
risk = "medium"

[[variables]]
name = "output"
description = "Scanner output"
required = true
type = "string"
+++

{{ output }}
""",
        encoding="utf-8",
    )
    return template


def _target(tmp_path: Path) -> tuple[Target, Path]:
    templates = tmp_path / "templates"
    _write_template(templates)
    target_path = tmp_path / "project" / "target_infrastructure_external_tls"
    (target_path / "findings").mkdir(parents=True)
    (target_path / "findings.toml").write_text("", encoding="utf-8")
    (target_path.parent / ".sereto").touch()
    target = Target(
        data=TargetModel.model_validate(
            {"category": "infrastructure", "name": "External TLS"},
            context={"categories": ["infrastructure"]},
        ),
        findings=Findings(groups=[], target_dir=target_path, target_locators=[]),
        path=target_path,
        version=ProjectVersion.from_str("v1.0"),
    )
    return target, templates


def _second_target(tmp_path: Path) -> Target:
    target_path = tmp_path / "project" / "target_infrastructure_internal_tls"
    (target_path / "findings").mkdir(parents=True)
    (target_path / "findings.toml").write_text("", encoding="utf-8")
    return Target(
        data=TargetModel.model_validate(
            {"category": "infrastructure", "name": "Internal TLS"},
            context={"categories": ["infrastructure"]},
        ),
        findings=Findings(groups=[], target_dir=target_path, target_locators=[]),
        path=target_path,
        version=ProjectVersion.from_str("v1.0"),
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _proposal(**changes: object) -> FindingProposal:
    values: dict[str, object] = {
        "proposal_id": "weak-tls-example",
        "target": {"kind": "sereto.target.v1", "id": "target_1"},
        "template": {"kind": "sereto.finding-template.v1", "id": "infrastructure/weak_tls"},
        "suggested_name": "Weak TLS on example.test",
        "suggested_risk": "high",
        "grouping": {"hint": "Transport security"},
        "variables": {"output": "TLS 1.0 enabled"},
        "locators": [{"type": "hostname", "value": "example.test"}],
    }
    values.update(changes)
    return FindingProposal.model_validate(values)


def _origin() -> ProposalOrigin:
    return ProposalOrigin(
        plugin_id="acme-testssl",
        distribution_name="Acme_TestSSL",
        distribution_version="2.4.1",
        sdk_api_major=1,
        sdk_package_version="0.1.0",
        protocol_version=1,
        operation_id="testssl.analyze",
    )


def test_prepare_proposals_validates_core_finding_without_project_writes(tmp_path: Path) -> None:
    target, templates = _target(tmp_path)
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")
    project_root = target.path.parent
    before = _snapshot(project_root)
    proposal = _proposal()

    prepared = prepare_finding_proposals(
        proposals=(proposal,),
        resources=resources,
        templates=templates,
        origin=_origin(),
    )

    assert len(prepared) == 1
    assert prepared[0].proposal.proposal_id == "weak-tls-example"
    assert 'name = "Weak TLS on example.test"' in prepared[0].finding.sub_finding_content
    assert 'risk = "high"' in prepared[0].finding.sub_finding_content
    assert 'plugin_id = "acme-testssl"' in prepared[0].finding.sub_finding_content
    assert _snapshot(project_root) == before


def test_noninteractive_review_without_acceptance_does_not_write(tmp_path: Path) -> None:
    target, templates = _target(tmp_path)
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")
    before = _snapshot(target.path.parent)

    outcome = review_finding_proposals(
        OperationResultPayload(finding_proposals=(_proposal(),)),
        resources,
        templates,
        _origin(),
        interactive=False,
    )

    assert outcome.proposal_ids == ("weak-tls-example",)
    assert outcome.accepted_ids == ()
    assert outcome.committed is False
    assert _snapshot(target.path.parent) == before


def test_explicit_accept_all_commits_validated_finding_with_origin(tmp_path: Path) -> None:
    target, templates = _target(tmp_path)
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")

    outcome = review_finding_proposals(
        OperationResultPayload(finding_proposals=(_proposal(),)),
        resources,
        templates,
        _origin(),
        accept_all=True,
        interactive=False,
    )

    assert outcome.accepted_ids == ("weak-tls-example",)
    assert outcome.committed is True
    finding_path = target.findings.groups[0].sub_findings[0].path
    frontmatter = SubFindingFrontmatterModel.load_from(finding_path)
    assert frontmatter.origin is not None
    assert frontmatter.origin.proposal_id == "weak-tls-example"
    assert frontmatter.origin.operation_id == "testssl.analyze"
    assert target.findings.groups[0].sub_findings[0].origin == frontmatter.origin


def test_invalid_proposal_blocks_all_proposals_without_writes(tmp_path: Path) -> None:
    target, templates = _target(tmp_path)
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")
    before = _snapshot(target.path.parent)
    invalid = _proposal(
        proposal_id="invalid-template",
        template={"kind": "sereto.finding-template.v1", "id": "../outside"},
    )

    with pytest.raises(SeretoValueError, match="invalid finding template ID"):
        review_finding_proposals(
            OperationResultPayload(finding_proposals=(_proposal(), invalid)),
            resources,
            templates,
            _origin(),
            accept_all=True,
            interactive=False,
        )

    assert _snapshot(target.path.parent) == before


def test_interactive_modify_requires_batch_confirmation_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, templates = _target(tmp_path)
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")
    modified = _proposal(suggested_name="Modified TLS finding")
    monkeypatch.setattr(proposals_module.click, "prompt", lambda *args, **kwargs: "modify")
    monkeypatch.setattr(
        proposals_module.click,
        "edit",
        lambda value: json.dumps(modified.model_dump(mode="json")),
    )
    monkeypatch.setattr(proposals_module.click, "confirm", lambda *args, **kwargs: False)
    before = _snapshot(target.path.parent)

    outcome = review_finding_proposals(
        OperationResultPayload(finding_proposals=(_proposal(),)),
        resources,
        templates,
        _origin(),
        interactive=True,
    )

    assert outcome.accepted_ids == ("weak-tls-example",)
    assert outcome.committed is False
    assert _snapshot(target.path.parent) == before


def test_interactive_modify_commits_only_modified_in_memory_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, templates = _target(tmp_path)
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")
    modified = _proposal(suggested_name="Modified TLS finding", suggested_risk="critical")
    monkeypatch.setattr(proposals_module.click, "prompt", lambda *args, **kwargs: "modify")
    monkeypatch.setattr(
        proposals_module.click,
        "edit",
        lambda value: json.dumps(modified.model_dump(mode="json")),
    )
    monkeypatch.setattr(proposals_module.click, "confirm", lambda *args, **kwargs: True)

    outcome = review_finding_proposals(
        OperationResultPayload(finding_proposals=(_proposal(),)),
        resources,
        templates,
        _origin(),
        interactive=True,
    )

    assert outcome.committed is True
    committed = target.findings.groups[0].sub_findings[0]
    assert committed.name == "Modified TLS finding"
    assert committed.risk.value == "critical"


def test_interactive_review_accepts_and_rejects_individual_proposals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, templates = _target(tmp_path)
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")
    decisions = iter(("reject", "accept"))
    monkeypatch.setattr(proposals_module.click, "prompt", lambda *args, **kwargs: next(decisions))
    monkeypatch.setattr(proposals_module.click, "confirm", lambda *args, **kwargs: True)
    first = _proposal(proposal_id="first", suggested_name="Rejected finding")
    second = _proposal(proposal_id="second", suggested_name="Accepted finding")

    outcome = review_finding_proposals(
        OperationResultPayload(finding_proposals=(first, second)),
        resources,
        templates,
        _origin(),
        interactive=True,
    )

    assert outcome.accepted_ids == ("second",)
    assert outcome.committed is True
    assert [finding.name for finding in target.findings.groups[0].sub_findings] == ["Accepted finding"]


def test_interactive_modify_cannot_change_proposal_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, templates = _target(tmp_path)
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")
    changed_identity = _proposal(proposal_id="other-id")
    monkeypatch.setattr(proposals_module.click, "prompt", lambda *args, **kwargs: "modify")
    monkeypatch.setattr(
        proposals_module.click,
        "edit",
        lambda value: json.dumps(changed_identity.model_dump(mode="json")),
    )
    before = _snapshot(target.path.parent)

    with pytest.raises(SeretoValueError, match="must not change proposal_id"):
        review_finding_proposals(
            OperationResultPayload(finding_proposals=(_proposal(),)),
            resources,
            templates,
            _origin(),
            interactive=True,
        )

    assert _snapshot(target.path.parent) == before


def test_explicit_accept_commits_only_selected_proposal_after_validating_all(tmp_path: Path) -> None:
    target, templates = _target(tmp_path)
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")
    first = _proposal(proposal_id="first", suggested_name="First TLS finding")
    second = _proposal(proposal_id="second", suggested_name="Second TLS finding")

    outcome = review_finding_proposals(
        OperationResultPayload(finding_proposals=(first, second)),
        resources,
        templates,
        _origin(),
        accept_ids=("second",),
        interactive=False,
    )

    assert outcome.proposal_ids == ("first", "second")
    assert outcome.accepted_ids == ("second",)
    assert [finding.name for finding in target.findings.groups[0].sub_findings] == ["Second TLS finding"]


@pytest.mark.parametrize(
    ("proposals", "message"),
    [
        pytest.param(
            (_proposal(), _proposal()),
            "proposal IDs must be unique",
            id="duplicate-id",
        ),
        pytest.param(
            (_proposal(metadata={"unscoped": True}),),
            "metadata keys must use",
            id="metadata-namespace",
        ),
        pytest.param(
            (_proposal(target={"kind": "sereto.target.v1", "id": "target_other"}),),
            "unknown package-plugin target resource",
            id="unknown-target",
        ),
        pytest.param(
            (
                _proposal(
                    template={"kind": "sereto.finding-template.v1", "id": "generic/weak_tls"},
                ),
            ),
            "template category does not match",
            id="category-mismatch",
        ),
        pytest.param(
            (_proposal(variables={"unknown": "value"}),),
            "invalid template variables",
            id="unknown-variable",
        ),
        pytest.param(
            (_proposal(variables={}),),
            "invalid template variables",
            id="missing-required-variable",
        ),
    ],
)
def test_invalid_proposal_sets_leave_project_unchanged(
    tmp_path: Path,
    proposals: tuple[FindingProposal, ...],
    message: str,
) -> None:
    target, templates = _target(tmp_path)
    generic_template = templates / "categories" / "generic" / "findings" / "weak_tls.md.j2"
    generic_template.parent.mkdir(parents=True)
    source_template = templates / "categories" / "infrastructure" / "findings" / "weak_tls.md.j2"
    generic_template.write_text(source_template.read_text(encoding="utf-8"), encoding="utf-8")
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")
    before = _snapshot(target.path.parent)

    with pytest.raises(SeretoValueError, match=message):
        prepare_finding_proposals(proposals, resources, templates, _origin())

    assert _snapshot(target.path.parent) == before


def test_unknown_explicit_acceptance_id_is_rejected_without_writes(tmp_path: Path) -> None:
    target, templates = _target(tmp_path)
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")
    before = _snapshot(target.path.parent)

    with pytest.raises(SeretoValueError, match="unknown package-plugin proposal IDs"):
        review_finding_proposals(
            OperationResultPayload(finding_proposals=(_proposal(),)),
            resources,
            templates,
            _origin(),
            accept_ids=("missing",),
            interactive=False,
        )

    assert _snapshot(target.path.parent) == before


def test_acceptance_modes_are_mutually_exclusive_without_writes(tmp_path: Path) -> None:
    target, templates = _target(tmp_path)
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")
    before = _snapshot(target.path.parent)

    with pytest.raises(SeretoValueError, match="mutually exclusive"):
        review_finding_proposals(
            OperationResultPayload(finding_proposals=(_proposal(),)),
            resources,
            templates,
            _origin(),
            accept_ids=("weak-tls-example",),
            accept_all=True,
            interactive=False,
        )

    assert _snapshot(target.path.parent) == before


def test_duplicate_prepared_finding_paths_are_rejected_without_writes(tmp_path: Path) -> None:
    target, templates = _target(tmp_path)
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")
    first = _proposal(proposal_id="first")
    second = _proposal(proposal_id="second")
    before = _snapshot(target.path.parent)

    with pytest.raises(SeretoValueError, match="conflicts with another prepared finding path"):
        prepare_finding_proposals((first, second), resources, templates, _origin())

    assert _snapshot(target.path.parent) == before


@pytest.mark.parametrize(
    ("proposal", "message"),
    [
        pytest.param(
            _proposal(suggested_name="\u202eunsafe"),
            "invalid suggested name",
            id="unicode-control-name",
        ),
        pytest.param(
            _proposal(suggested_name="漏洞"),
            "filesystem-safe",
            id="empty-normalized-name",
        ),
        pytest.param(
            _proposal(grouping={"hint": "unsafe\nname"}),
            "invalid grouping text",
            id="control-grouping",
        ),
        pytest.param(
            _proposal(metadata={"acme-testssl.data": "x" * (proposals_module.MAX_METADATA_BYTES + 1)}),
            "metadata exceeds",
            id="oversized-metadata",
        ),
    ],
)
def test_plugin_controlled_proposal_text_is_bounded_and_safe(
    tmp_path: Path,
    proposal: FindingProposal,
    message: str,
) -> None:
    target, templates = _target(tmp_path)
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")
    before = _snapshot(target.path.parent)

    with pytest.raises(SeretoValueError, match=message):
        prepare_finding_proposals((proposal,), resources, templates, _origin())

    assert _snapshot(target.path.parent) == before


def test_proposal_count_is_bounded_before_preparation(tmp_path: Path) -> None:
    target, templates = _target(tmp_path)
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")
    proposals = tuple(
        _proposal(proposal_id=f"proposal-{index}", suggested_name=f"Finding {index}")
        for index in range(proposals_module.MAX_PROPOSALS + 1)
    )

    with pytest.raises(SeretoValueError, match="exceeds .* finding proposals"):
        prepare_finding_proposals(proposals, resources, templates, _origin())


def test_grouping_hint_reuses_existing_group(tmp_path: Path) -> None:
    target, templates = _target(tmp_path)
    existing = target.findings.prepare_from_template(
        templates=templates,
        template_path=templates / "categories" / "infrastructure" / "findings" / "weak_tls.md.j2",
        category="infrastructure",
        sub_finding_name="Existing TLS finding",
        variables={"output": "existing"},
        group_name="Transport security",
    )
    target.findings.commit_prepared(existing)
    resources = TargetResources.from_targets((target,), id_factory=lambda: "target_1")

    prepared = prepare_finding_proposals((_proposal(),), resources, templates, _origin())

    assert prepared[0].finding.registration == ExistingGroupDestination(
        uname=target.findings.groups[0].uname,
        expected_name="Transport security",
    )


def test_accept_all_commits_proposals_across_targets_in_one_project(tmp_path: Path) -> None:
    first_target, templates = _target(tmp_path)
    second_target = _second_target(tmp_path)
    resource_ids = iter(("target_1", "target_2"))
    resources = TargetResources.from_targets((first_target, second_target), id_factory=lambda: next(resource_ids))
    first = _proposal(proposal_id="external", suggested_name="External TLS finding")
    second = _proposal(
        proposal_id="internal",
        suggested_name="Internal TLS finding",
        target={"kind": "sereto.target.v1", "id": "target_2"},
    )

    outcome = review_finding_proposals(
        OperationResultPayload(finding_proposals=(first, second)),
        resources,
        templates,
        _origin(),
        accept_all=True,
        interactive=False,
    )

    assert outcome.accepted_ids == ("external", "internal")
    assert [group.name for group in first_target.findings.groups] == ["Transport security"]
    assert [group.name for group in second_target.findings.groups] == ["Transport security"]


def test_cross_target_batch_failure_rolls_back_every_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_target, templates = _target(tmp_path)
    second_target = _second_target(tmp_path)
    resource_ids = iter(("target_1", "target_2"))
    resources = TargetResources.from_targets((first_target, second_target), id_factory=lambda: next(resource_ids))
    proposals = (
        _proposal(proposal_id="external", suggested_name="External TLS finding"),
        _proposal(
            proposal_id="internal",
            suggested_name="Internal TLS finding",
            target={"kind": "sereto.target.v1", "id": "target_2"},
        ),
    )
    before = _snapshot(first_target.path.parent)
    real_replace = file_transaction.os.replace

    def fail_second_target(source: Path, destination: Path) -> None:
        if Path(destination).parent == second_target.findings.findings_dir:
            raise OSError("injected cross-target failure")
        real_replace(source, destination)

    monkeypatch.setattr(file_transaction.os, "replace", fail_second_target)

    with pytest.raises(OSError, match="injected cross-target failure"):
        review_finding_proposals(
            OperationResultPayload(finding_proposals=proposals),
            resources,
            templates,
            _origin(),
            accept_all=True,
            interactive=False,
        )

    assert _snapshot(first_target.path.parent) == before


def test_proposals_spanning_projects_are_rejected_before_review(tmp_path: Path) -> None:
    first_target, templates = _target(tmp_path)
    other_root = tmp_path / "other"
    second_target = _second_target(other_root)
    resource_ids = iter(("target_1", "target_2"))
    resources = TargetResources.from_targets((first_target, second_target), id_factory=lambda: next(resource_ids))
    proposals = (
        _proposal(proposal_id="first"),
        _proposal(
            proposal_id="second",
            target={"kind": "sereto.target.v1", "id": "target_2"},
        ),
    )
    before = _snapshot(tmp_path)

    with pytest.raises(SeretoValueError, match="span multiple projects"):
        prepare_finding_proposals(proposals, resources, templates, _origin())

    assert _snapshot(tmp_path) == before
