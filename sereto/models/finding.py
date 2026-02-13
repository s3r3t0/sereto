import tomllib
from collections.abc import ItemsView
from pathlib import Path
from typing import Any, Literal, Self

import frontmatter  # type: ignore[import-untyped]
from pydantic import Field, FilePath, RootModel, ValidationError, field_validator, validate_call
from tomlkit import dumps as toml_dumps

from sereto.enums import FileFormat
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.base import SeretoBaseModel
from sereto.models.date import SeretoDate
from sereto.models.locator import LocatorModel, get_locator_types
from sereto.sereto_types import TypeCategoryName, TypeRisk, TypeRiskOptional


class VarsMetadataModel(SeretoBaseModel):
    name: str
    description: str
    required: bool = False
    is_list: bool = Field(False, alias="list")
    type: Literal["string", "integer", "boolean"] = "string"

    @property
    def type_annotation(self) -> str:
        """Get description of the variable type and required state."""
        type_annotation = f"list[{self.type}]" if self.is_list else self.type
        required = "required" if self.required else "optional"
        return f"{type_annotation}, {required}"


class FindingTemplateFrontmatterModel(SeretoBaseModel):
    """Representation of the frontmatter of a finding template.

    Attributes:
        name: The name of the sub-finding.
        risk: The risk level of the sub-finding.
        keywords: A list of keywords used to search for the sub-finding.
        variables: A list of variables used in the sub-finding.
    """

    name: str
    risk: TypeRisk
    keywords: list[str] = []
    variables: list[VarsMetadataModel] = []

    @classmethod
    @validate_call
    def load_from(cls, path: Path) -> Self:
        """Load FindingTemplateFrontmatterModel from a file."""
        try:
            metadata, _ = frontmatter.parse(path.read_text(encoding="utf-8"), encoding="utf-8")
            return cls.model_validate(metadata)
        except ValidationError as ex:
            raise SeretoValueError(f"invalid template frontmatter in '{path}'") from ex


class SubFindingFrontmatterModel(SeretoBaseModel):
    """Frontmatter metadata for a sub-finding included in a project.

    Attributes:
        name: Sub-finding display name.
        risk: Risk classification of the sub-finding.
        category: Category from which the sub-finding originates.
        variables: Variable values injected into the sub-finding.
        template_path: Relative path to the sub-finding template file.
        locators: A list of locators used to find the sub-finding.
        format: The file format of the sub-finding (defaults to markdown).
        reported_on: Date the finding was first reported. Only useful if introduced later.
    """

    name: str
    risk: TypeRisk
    category: TypeCategoryName
    variables: dict[str, Any] = {}
    template_path: str | None = None
    locators: list[LocatorModel] = Field(default_factory=list)
    format: FileFormat = Field(default=FileFormat.md)
    reported_on: SeretoDate | None = None

    def dumps_toml(self) -> str:
        """Dump the model to a TOML-formatted string using a TOML library."""
        # Prepare the data dict in the desired structure
        data: dict[str, Any] = {
            "name": self.name,
            "risk": self.risk.value,
            "category": self.category.lower(),
            "locators": [locator.model_dump(exclude_none=True) for locator in self.locators],
        }
        if self.template_path:
            data["template_path"] = self.template_path
        if len(self.variables) > 0 and any(v is not None for v in self.variables.values()):
            data["variables"] = {k: v for k, v in self.variables.items() if v is not None}

        # Dump to TOML string
        return toml_dumps(data)

    @classmethod
    @validate_call
    def load_from(cls, path: Path) -> Self:
        """Load FindingFrontmatterModel from a file."""
        try:
            metadata, _ = frontmatter.parse(path.read_text(encoding="utf-8"), encoding="utf-8")
            return cls.model_validate(metadata)
        except ValidationError as ex:
            raise SeretoValueError(f"invalid finding frontmatter in '{path}'") from ex


class FindingGroupModel(SeretoBaseModel, extra="allow"):
    """Representation of a single finding group from `findings.toml`.

    Attributes:
        risks: Explicit risks associated with the finding group for specific versions.
        findings: The list of sub-findings in the format of their unique name to include in the report.
        locators: A list of locators used to find the finding group.
        show_locator_types: A list of locator types to return from the FindingGroup.locators() property.

    Note:
        This model allows extra fields (via `extra="allow"`) to support plugin-specific data storage.
        Plugins should use namespaced keys (e.g., `yourplugin_var`) to avoid collisions with future core fields.
    """

    risk: TypeRiskOptional = None
    findings: list[str] = Field(min_length=1)
    locators: list[LocatorModel] = Field(default_factory=list)
    show_locator_types: list[str] = Field(default_factory=get_locator_types)

    @field_validator("findings", mode="after")
    @classmethod
    def unique_finding_names(cls, findings: list[str]) -> list[str]:
        """Ensure that all finding names are unique."""
        if len(findings) != len(set(findings)):
            raise ValueError("finding names must be unique")
        return findings


class FindingsConfigModel(RootModel[dict[str, FindingGroupModel]]):
    """Model representing the included findings configuration.

    The data itself is expected to be a dict where each key is
    the name of a finding group and the value is a FindingGroupModel.
    """

    root: dict[str, FindingGroupModel]

    @field_validator("root", mode="after")
    @classmethod
    def unique_findings(cls, findings: dict[str, FindingGroupModel]) -> dict[str, FindingGroupModel]:
        all_findings: list[str] = []
        for _, group in findings.items():
            all_findings.extend(group.findings)
        if len(all_findings) != len(set(all_findings)):
            raise ValueError("each sub-finding must be included only once")
        return findings

    @classmethod
    @validate_call
    def load_from(cls, file: FilePath) -> Self:
        try:
            with file.open(mode="rb") as f:
                return cls.model_validate(tomllib.load(f))
        except FileNotFoundError:
            raise SeretoPathError(f"file not found at '{file}'") from None
        except PermissionError:
            raise SeretoPathError(f"permission denied for '{file}'") from None
        except ValueError as e:
            raise SeretoValueError("invalid findings.toml") from e

    def items(self) -> ItemsView[str, FindingGroupModel]:
        return self.root.items()
