import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, cast

import click
from pydantic import TypeAdapter, ValidationError

from sereto.enums import Risk
from sereto.exceptions import SeretoValueError
from sereto.finding import Findings, PreparedFinding
from sereto.models.finding import PackagePluginFindingOriginModel
from sereto.models.locator import LocatorModel
from sereto.package_plugins.manifest import PluginRecord
from sereto.package_plugins.protocol_v1 import FindingProposal, Grouping, OperationResultPayload
from sereto.package_plugins.resources import TargetResources
from sereto.target import Target
from sereto.utils import lower_alphanum

_TEMPLATE_SEGMENT = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")
_LOCATORS = TypeAdapter(list[LocatorModel])
MAX_PROPOSALS = 256
MAX_METADATA_BYTES = 64 * 1024
MAX_DISPLAY_TEXT_LENGTH = 256
MAX_FINDING_FILENAME_LENGTH = 128
MAX_TEMPLATE_SEGMENT_LENGTH = 128


@dataclass(frozen=True)
class ProposalOrigin:
    plugin_id: str
    distribution_name: str
    distribution_version: str
    sdk_api_major: Literal[1]
    sdk_package_version: str
    protocol_version: Literal[1]
    operation_id: str

    @classmethod
    def from_record(cls, record: PluginRecord, operation_id: str) -> "ProposalOrigin":
        return cls(
            plugin_id=record.plugin_id,
            distribution_name=record.distribution.name,
            distribution_version=record.distribution.version,
            sdk_api_major=cast(Literal[1], record.sdk_api_major),
            sdk_package_version=record.sdk_package_version,
            protocol_version=cast(Literal[1], record.selected_protocol_version),
            operation_id=operation_id,
        )

    def finding_origin(self, proposal_id: str) -> PackagePluginFindingOriginModel:
        return PackagePluginFindingOriginModel(
            plugin_id=self.plugin_id,
            distribution_name=self.distribution_name,
            distribution_version=self.distribution_version,
            sdk_api_major=self.sdk_api_major,
            sdk_package_version=self.sdk_package_version,
            protocol_version=self.protocol_version,
            operation_id=self.operation_id,
            proposal_id=proposal_id,
        )


@dataclass(frozen=True)
class PreparedProposal:
    proposal: FindingProposal
    target: Target
    finding: PreparedFinding


@dataclass(frozen=True)
class ProposalReviewOutcome:
    proposal_ids: tuple[str, ...]
    accepted_ids: tuple[str, ...]
    committed: bool


def prepare_finding_proposals(
    proposals: tuple[FindingProposal, ...],
    resources: TargetResources,
    templates: Path,
    origin: ProposalOrigin,
) -> tuple[PreparedProposal, ...]:
    """Validate every plugin proposal and prepare core findings without writing files."""
    if len(proposals) > MAX_PROPOSALS:
        raise SeretoValueError(f"package-plugin result exceeds {MAX_PROPOSALS} finding proposals")
    proposal_ids = [proposal.proposal_id for proposal in proposals]
    if len(proposal_ids) != len(set(proposal_ids)):
        raise SeretoValueError("package-plugin proposal IDs must be unique")

    prepared: list[PreparedProposal] = []
    prepared_paths: set[Path] = set()
    project_roots: set[Path] = set()
    for proposal in proposals:
        _validate_proposal_text(proposal)
        proposal = _normalize_proposal_text(proposal)
        _validate_metadata_namespace(proposal, origin.plugin_id)
        target = resources.resolve(proposal.target)
        project_roots.add(Path(target.findings.target_dir).resolve().parent)
        if len(project_roots) > 1:
            raise SeretoValueError("package-plugin finding proposals span multiple projects")
        category, template_path = _resolve_template(templates, proposal.template.id)
        if category != target.data.category:
            raise SeretoValueError(
                f"proposal {proposal.proposal_id!r} template category does not match its target"
            )
        try:
            locators = _LOCATORS.validate_python(
                [locator.model_dump(mode="json", exclude_none=True) for locator in proposal.locators]
            )
        except ValidationError as error:
            raise SeretoValueError(f"proposal {proposal.proposal_id!r} contains invalid locators") from error

        group_uname, group_name = _resolve_grouping(target, proposal)
        finding = target.findings.prepare_from_template(
            templates=templates,
            template_path=template_path,
            category=category,
            sub_finding_name=proposal.suggested_name,
            risk=Risk(proposal.suggested_risk) if proposal.suggested_risk is not None else None,
            variables=proposal.variables,
            locators=locators,
            group_uname=group_uname,
            group_name=group_name,
            origin=origin.finding_origin(proposal.proposal_id),
        )
        prepared_path = finding.sub_finding_path.resolve()
        if prepared_path in prepared_paths:
            raise SeretoValueError(
                f"proposal {proposal.proposal_id!r} conflicts with another prepared finding path"
            )
        prepared_paths.add(prepared_path)
        prepared.append(PreparedProposal(proposal=proposal, target=target, finding=finding))
    return tuple(prepared)


def review_finding_proposals(
    result: OperationResultPayload,
    resources: TargetResources,
    templates: Path,
    origin: ProposalOrigin,
    *,
    accept_ids: tuple[str, ...] = (),
    accept_all: bool = False,
    interactive: bool | None = None,
) -> ProposalReviewOutcome:
    """Validate, review, and atomically commit explicitly accepted finding proposals."""
    prepared = prepare_finding_proposals(result.finding_proposals, resources, templates, origin)
    proposal_ids = tuple(item.proposal.proposal_id for item in prepared)
    if accept_all and accept_ids:
        raise SeretoValueError("--sereto-accept and --sereto-accept-all are mutually exclusive")
    unknown_ids = sorted(set(accept_ids) - set(proposal_ids))
    if unknown_ids:
        raise SeretoValueError("unknown package-plugin proposal IDs: " + ", ".join(unknown_ids))
    if not prepared:
        return ProposalReviewOutcome(proposal_ids=(), accepted_ids=(), committed=False)

    if accept_all or accept_ids:
        accepted_ids = (
            proposal_ids
            if accept_all
            else tuple(proposal_id for proposal_id in proposal_ids if proposal_id in accept_ids)
        )
        accepted = tuple(item for item in prepared if item.proposal.proposal_id in accepted_ids)
        _commit_proposals(accepted)
        return ProposalReviewOutcome(proposal_ids=proposal_ids, accepted_ids=accepted_ids, committed=bool(accepted))

    resolved_interactive = sys.stdin.isatty() if interactive is None else interactive
    if not resolved_interactive:
        click.echo(
            f"{len(prepared)} finding proposal(s) require explicit acceptance; project unchanged.",
            err=True,
        )
        return ProposalReviewOutcome(proposal_ids=proposal_ids, accepted_ids=(), committed=False)

    accepted_proposals: list[FindingProposal] = []
    for item in prepared:
        click.echo(json.dumps(item.proposal.model_dump(mode="json"), allow_nan=False, indent=2, sort_keys=True))
        decision = click.prompt(
            f"Review proposal {item.proposal.proposal_id}",
            type=click.Choice(("accept", "reject", "modify")),
            default="reject",
            show_choices=True,
        )
        if decision == "accept":
            accepted_proposals.append(item.proposal)
        elif decision == "modify":
            accepted_proposals.append(_edit_proposal(item.proposal))

    if not accepted_proposals:
        return ProposalReviewOutcome(proposal_ids=proposal_ids, accepted_ids=(), committed=False)
    accepted = prepare_finding_proposals(tuple(accepted_proposals), resources, templates, origin)
    accepted_ids = tuple(item.proposal.proposal_id for item in accepted)
    if not click.confirm(f"Commit {len(accepted)} accepted finding proposal(s)?", default=False):
        return ProposalReviewOutcome(proposal_ids=proposal_ids, accepted_ids=accepted_ids, committed=False)
    _commit_proposals(accepted)
    return ProposalReviewOutcome(proposal_ids=proposal_ids, accepted_ids=accepted_ids, committed=True)


def _edit_proposal(proposal: FindingProposal) -> FindingProposal:
    edited = click.edit(json.dumps(proposal.model_dump(mode="json"), allow_nan=False, indent=2, sort_keys=True))
    if edited is None:
        raise SeretoValueError(f"proposal {proposal.proposal_id!r} modification was cancelled")
    try:
        modified = FindingProposal.model_validate_json(edited)
    except ValidationError as error:
        raise SeretoValueError(f"proposal {proposal.proposal_id!r} modification is invalid") from error
    if modified.proposal_id != proposal.proposal_id:
        raise SeretoValueError("proposal modification must not change proposal_id")
    return modified


def _commit_proposals(prepared: tuple[PreparedProposal, ...]) -> None:
    Findings.commit_prepared_batch(tuple((item.target.findings, item.finding) for item in prepared))


def _resolve_template(templates: Path, template_id: str) -> tuple[str, Path]:
    logical_path = PurePosixPath(template_id)
    if logical_path.is_absolute() or len(logical_path.parts) != 2:
        raise SeretoValueError(f"invalid finding template ID: {template_id!r}")
    category, template_name = logical_path.parts
    if (
        len(category) > MAX_TEMPLATE_SEGMENT_LENGTH
        or len(template_name) > MAX_TEMPLATE_SEGMENT_LENGTH
        or not _TEMPLATE_SEGMENT.fullmatch(category)
        or not _TEMPLATE_SEGMENT.fullmatch(template_name)
    ):
        raise SeretoValueError(f"invalid finding template ID: {template_id!r}")
    templates_root = templates.resolve()
    template_path = (templates_root / "categories" / category / "findings" / f"{template_name}.md.j2").resolve()
    if not template_path.is_relative_to(templates_root) or not template_path.is_file():
        raise SeretoValueError(f"finding template does not exist: {template_id!r}")
    return category, template_path


def _resolve_grouping(target: Target, proposal: FindingProposal) -> tuple[str | None, str | None]:
    if proposal.grouping is None:
        return None, None
    hint = (proposal.grouping.hint or "").strip()
    suggested_name = (proposal.grouping.suggested_name or "").strip()
    if hint:
        existing_group = target.findings.find_group_by_hint(hint)
        if existing_group is not None:
            return existing_group.uname, None
    group_name = suggested_name or hint
    if not group_name:
        raise SeretoValueError(f"proposal {proposal.proposal_id!r} has an empty grouping suggestion")
    return None, group_name


def _validate_metadata_namespace(proposal: FindingProposal, plugin_id: str) -> None:
    prefix = f"{plugin_id}."
    invalid_keys = sorted(
        key
        for key in proposal.metadata
        if len(key) > MAX_DISPLAY_TEXT_LENGTH
        or not key.startswith(prefix)
        or _contains_unsafe_text(key)
    )
    if invalid_keys:
        raise SeretoValueError(
            f"proposal {proposal.proposal_id!r} metadata keys must use the {prefix!r} namespace"
        )
    metadata_content = json.dumps(
        proposal.metadata,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(metadata_content) > MAX_METADATA_BYTES:
        raise SeretoValueError(f"proposal {proposal.proposal_id!r} metadata exceeds {MAX_METADATA_BYTES} bytes")


def _validate_proposal_text(proposal: FindingProposal) -> None:
    if proposal.suggested_name is not None:
        name = proposal.suggested_name.strip()
        if not name or len(name) > MAX_DISPLAY_TEXT_LENGTH or _contains_unsafe_text(name):
            raise SeretoValueError(f"proposal {proposal.proposal_id!r} has an invalid suggested name")
        normalized_name = lower_alphanum(name)
        if not normalized_name or len(normalized_name) > MAX_FINDING_FILENAME_LENGTH:
            raise SeretoValueError(f"proposal {proposal.proposal_id!r} suggested name is not filesystem-safe")
    if proposal.grouping is not None:
        for value in (proposal.grouping.suggested_name, proposal.grouping.hint):
            if value is not None and (
                not value.strip()
                or len(value) > MAX_DISPLAY_TEXT_LENGTH
                or _contains_unsafe_text(value)
            ):
                raise SeretoValueError(f"proposal {proposal.proposal_id!r} has invalid grouping text")


def _contains_unsafe_text(value: str) -> bool:
    return any(
        unicodedata.category(character).startswith("C")
        or unicodedata.category(character) in {"Zl", "Zp"}
        for character in value
    )


def _normalize_proposal_text(proposal: FindingProposal) -> FindingProposal:
    grouping = proposal.grouping
    normalized_grouping = (
        None
        if grouping is None
        else Grouping(
            suggested_name=grouping.suggested_name.strip() if grouping.suggested_name is not None else None,
            hint=grouping.hint.strip() if grouping.hint is not None else None,
        )
    )
    return proposal.model_copy(
        update={
            "suggested_name": proposal.suggested_name.strip() if proposal.suggested_name is not None else None,
            "grouping": normalized_grouping,
        }
    )
