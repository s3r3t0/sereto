import tomllib
from collections.abc import ItemsView
from pathlib import Path
from textwrap import dedent
from typing import Any, Literal, Self

import frontmatter  # type: ignore[import-untyped]
from pydantic import Field, FilePath, RootModel, ValidationError, field_validator, validate_call

from sereto.enums import Risk
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.base import SeretoBaseModel
from sereto.types import TypeCategoryName


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
    risk: Risk
    keywords: list[str] = []
    variables: list[VarsMetadataModel] = []

    @field_validator("risk", mode="before")
    @classmethod
    def convert_risk_type(cls, risk: Any) -> Risk:
        match risk:
            case Risk():
                return risk
            case str():
                return Risk(risk)
            case _:
                raise ValueError("unsupported type for Risk")

    @classmethod
    @validate_call
    def load_from(cls, path: Path) -> Self:
        """Load FindingTemplateFrontmatterModel from a file."""
        try:
            metadata, _ = frontmatter.parse(path.read_text(), encoding="utf-8")
            return cls.model_validate(metadata)
        except ValidationError as ex:
            raise SeretoValueError(f"invalid template frontmatter in '{path}'") from ex


class SubFindingFrontmatterModel(SeretoBaseModel):
    """Representation of the frontmatter of a sub-finding included in project.

    Attributes:
        name: The name of the sub-finding.
        risk: The risk level of the sub-finding.
        category: From which category the sub-finding originates.
        variables: A dictionary of variables used in the sub-finding.
        template_path: Relative path to the finding in templates directory.
        locators: A list of locators used to find the sub-finding.
    """

    name: str
    risk: Risk
    category: TypeCategoryName
    variables: dict[str, Any] = {}
    template_path: str | None = None
    locators: list[str] = Field(default_factory=list)

    @field_validator("risk", mode="before")
    @classmethod
    def convert_risk_type(cls, risk: Any) -> Risk:
        """Convert risk to Risk enum."""
        match risk:
            case Risk():
                return risk
            case str():
                return Risk(risk)
            case _:
                raise ValueError("unsupported type for Risk")

    def dumps_toml(self) -> str:
        """Dump the model to a TOML-formatted string."""
        output = dedent(f"""\
            name = "{self.name}"
            risk = "{self.risk.value}"
            category = "{self.category.lower()}"
        """)

        if self.template_path:
            output += f'template_path = "{self.template_path}"'

        output += "\n\n[variables]\n"
        output += "\n".join(f"{k} = {v!r}" for k, v in self.variables.items())
        return output + "\n"

    @classmethod
    @validate_call
    def load_from(cls, path: Path) -> Self:
        """Load FindingFrontmatterModel from a file."""
        try:
            metadata, _ = frontmatter.parse(path.read_text(), encoding="utf-8")
            return cls.model_validate(metadata)
        except ValidationError as ex:
            raise SeretoValueError(f"invalid finding frontmatter in '{path}'") from ex


class FindingGroupModel(SeretoBaseModel):
    """Representation of a single finding group from `findings.toml`.

    Attributes:
        risks: Explicit risks associated with the finding group for specific versions.
        findings: The list of sub-findings in the format of their unique name to include in the report.
        locators: A list of locators used to find the finding group.
    """

    risk: Risk | None = None
    findings: list[str] = Field(min_length=1)
    locators: list[str] = Field(default_factory=list)

    @field_validator("risk", mode="before")
    @classmethod
    def load_risk(cls, risk: Any) -> Risk | None:
        """Convert risk to correct type."""
        match risk:
            case Risk() | None:
                return risk
            case str():
                return Risk(risk)
            case _:
                raise ValueError("invalid risk type")

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
