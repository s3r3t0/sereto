import json
from datetime import datetime
from typing import Annotated, Literal, NoReturn, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from sereto.exceptions import SeretoRuntimeError

PROTOCOL_VERSION = 1
SUBPROTOCOL = "sereto.plugin.v1"
MANIFEST_OPERATION_ID = "sereto.manifest.get"

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

Identifier = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$",
    ),
]
CommandSegment = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
    ),
]
NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
VersionOne = Annotated[int, Field(strict=True, ge=1, le=1)]
type Capability = Literal["finding.propose"]
type ResourceKind = Literal["sereto.target.v1"]
type Risk = Literal["critical", "high", "medium", "low", "info"]
type LocatorType = Literal["url", "hostname", "domain", "ip", "file", "platform"]


class PluginProtocolError(SeretoRuntimeError):
    """A package plugin sent an invalid or unexpected protocol message."""


class ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class DistributionIdentity(ProtocolModel):
    name: NonEmptyString
    version: NonEmptyString


class SDKIdentity(ProtocolModel):
    api_major: VersionOne = 1
    package_version: NonEmptyString


class Operation(ProtocolModel):
    id: Identifier
    capability: Capability
    resource_kinds: tuple[ResourceKind, ...] = ()


class Command(ProtocolModel):
    path: tuple[CommandSegment, ...] = Field(min_length=1)
    operation_id: Identifier
    summary: NonEmptyString
    usage: str = ""


class Manifest(ProtocolModel):
    manifest_version: VersionOne = 1
    plugin_id: Identifier
    sdk_api_major: VersionOne = 1
    protocol_versions: tuple[VersionOne, ...] = Field(default=(1,), min_length=1)
    requires_sereto: NonEmptyString
    capabilities: tuple[Capability, ...] = Field(min_length=1)
    resource_kinds: tuple[ResourceKind, ...] = ()
    operations: tuple[Operation, ...] = Field(min_length=1)
    commands: tuple[Command, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest_links(self) -> Self:
        operation_ids = [operation.id for operation in self.operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("operation IDs must be unique")
        command_paths = [command.path for command in self.commands]
        if len(command_paths) != len(set(command_paths)):
            raise ValueError("command paths must be unique")
        declared_operation_ids = set(operation_ids)
        for command in self.commands:
            if command.operation_id not in declared_operation_ids:
                raise ValueError(f"command references unknown operation {command.operation_id!r}")

        declared_capabilities = set(self.capabilities)
        declared_resource_kinds = set(self.resource_kinds)
        if len(self.protocol_versions) != len(set(self.protocol_versions)):
            raise ValueError("protocol versions must be unique")
        if len(self.capabilities) != len(declared_capabilities):
            raise ValueError("capabilities must be unique")
        if len(self.resource_kinds) != len(declared_resource_kinds):
            raise ValueError("resource kinds must be unique")
        for operation in self.operations:
            if operation.capability not in declared_capabilities:
                raise ValueError(f"operation {operation.id!r} uses an undeclared capability")
            if not set(operation.resource_kinds) <= declared_resource_kinds:
                raise ValueError(f"operation {operation.id!r} uses an undeclared resource kind")
            if len(operation.resource_kinds) != len(set(operation.resource_kinds)):
                raise ValueError(f"operation {operation.id!r} resource kinds must be unique")
        return self


class Locator(ProtocolModel):
    type: LocatorType
    value: NonEmptyString
    description: str | None = None


class ResourceReference(ProtocolModel):
    kind: ResourceKind
    id: Identifier


class TemplateReference(ProtocolModel):
    kind: Literal["sereto.finding-template.v1"] = "sereto.finding-template.v1"
    id: NonEmptyString


class Resource(ProtocolModel):
    kind: ResourceKind
    id: Identifier
    attributes: dict[str, JsonValue]


class Grouping(ProtocolModel):
    suggested_name: str | None = None
    hint: str | None = None

    @model_validator(mode="after")
    def require_suggestion(self) -> Self:
        if self.suggested_name is None and self.hint is None:
            raise ValueError("grouping must define suggested_name or hint")
        return self


class FindingProposal(ProtocolModel):
    proposal_id: Identifier
    target: ResourceReference
    template: TemplateReference
    suggested_name: str | None = None
    suggested_risk: Risk | None = None
    grouping: Grouping | None = None
    variables: dict[str, JsonValue] = Field(default_factory=dict)
    locators: tuple[Locator, ...] = ()
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class OperationRequest(ProtocolModel):
    operation_id: Identifier
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    resources: tuple[Resource, ...] = ()


class ProgressPayload(ProtocolModel):
    sequence: int = Field(strict=True, ge=1)
    fraction: float | None = Field(default=None, ge=0, le=1)
    message: str | None = None


class ManifestResultPayload(ProtocolModel):
    kind: Literal["manifest"] = "manifest"
    manifest: Manifest


class OperationResultPayload(ProtocolModel):
    kind: Literal["operation"] = "operation"
    output: dict[str, JsonValue] = Field(default_factory=dict)
    finding_proposals: tuple[FindingProposal, ...] = ()


type ResultPayload = Annotated[
    ManifestResultPayload | OperationResultPayload,
    Field(discriminator="kind"),
]


class ErrorPayload(ProtocolModel):
    code: Identifier
    message: NonEmptyString
    retryable: StrictBool = False
    details: dict[str, JsonValue] = Field(default_factory=dict)


class HelloPayload(ProtocolModel):
    plugin_id: Identifier
    distribution: DistributionIdentity
    sdk: SDKIdentity
    protocol_versions: tuple[VersionOne, ...] = Field(default=(1,), min_length=1)


class ReadyLimits(ProtocolModel):
    max_message_bytes: int = Field(strict=True, ge=1024)


class ReadyPayload(ProtocolModel):
    selected_protocol_version: VersionOne = 1
    sereto_version: NonEmptyString
    deadline: datetime
    limits: ReadyLimits
    resource_kinds: tuple[ResourceKind, ...] = ()

    @field_validator("deadline")
    @classmethod
    def deadline_must_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deadline must include a timezone")
        return value


class CancelPayload(ProtocolModel):
    reason: str | None = None


class HelloMessage(ProtocolModel):
    protocol_version: VersionOne = 1
    type: Literal["hello"] = "hello"
    request_id: Identifier
    payload: HelloPayload


class ReadyMessage(ProtocolModel):
    protocol_version: VersionOne = 1
    type: Literal["ready"] = "ready"
    request_id: Identifier
    payload: ReadyPayload


class RequestMessage(ProtocolModel):
    protocol_version: VersionOne = 1
    type: Literal["request"] = "request"
    request_id: Identifier
    payload: OperationRequest


class ProgressMessage(ProtocolModel):
    protocol_version: VersionOne = 1
    type: Literal["progress"] = "progress"
    request_id: Identifier
    payload: ProgressPayload


class ResultMessage(ProtocolModel):
    protocol_version: VersionOne = 1
    type: Literal["result"] = "result"
    request_id: Identifier
    payload: ResultPayload


class ErrorMessage(ProtocolModel):
    protocol_version: VersionOne = 1
    type: Literal["error"] = "error"
    request_id: Identifier
    payload: ErrorPayload


class CancelMessage(ProtocolModel):
    protocol_version: VersionOne = 1
    type: Literal["cancel"] = "cancel"
    request_id: Identifier
    payload: CancelPayload = Field(default_factory=CancelPayload)


type HostMessage = ReadyMessage | RequestMessage | CancelMessage
type PluginMessage = Annotated[
    HelloMessage | ProgressMessage | ResultMessage | ErrorMessage,
    Field(discriminator="type"),
]

_PLUGIN_MESSAGE_ADAPTER: TypeAdapter[PluginMessage] = TypeAdapter(PluginMessage)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number {value!r}")


def decode_plugin_message(message: str | bytes) -> PluginMessage:
    if isinstance(message, bytes):
        raise PluginProtocolError("binary plugin protocol messages are not supported")
    try:
        decoded = json.loads(
            message,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
        return _PLUGIN_MESSAGE_ADAPTER.validate_python(cast(object, decoded))
    except (json.JSONDecodeError, ValueError, ValidationError) as error:
        raise PluginProtocolError(f"invalid plugin protocol message: {error}") from error


def encode_host_message(message: HostMessage) -> str:
    try:
        return json.dumps(
            message.model_dump(mode="json", exclude_none=True),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise PluginProtocolError(f"host protocol message is not JSON serializable: {error}") from error
