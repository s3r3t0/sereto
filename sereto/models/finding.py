from pathlib import Path
from typing import Any, Self

import frontmatter  # type: ignore[import-untyped]
from pydantic import Field, FilePath, ValidationError, field_validator, model_validator, validate_call

from sereto.enums import Risk
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.base import SeretoBaseModel
from sereto.utils import YAML, lower_alphanum


class VarsMetadataModel(SeretoBaseModel):
    name: str
    description: str
    required: bool = False
    list: bool = False

    def __str__(self) -> str:
        if self.required:
            params = " (required, list)" if self.list else " (required)"
        else:
            params = " (list)" if self.list else ""

        return f"{self.name}{params}: {self.description}"


class FindingTemplateFrontmatterModel(SeretoBaseModel):
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
        try:
            metadata, _ = frontmatter.parse(path.read_text(), encoding="utf-8")
            return cls.model_validate(metadata)
        except ValidationError as ex:
            raise SeretoValueError(f"invalid template frontmatter in '{path}'") from ex


class FindingFrontmatterModel(SeretoBaseModel):
    name: str
    risk: Risk

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

    @classmethod
    @validate_call
    def load_from(cls, path: Path) -> Self:
        try:
            metadata, _ = frontmatter.parse(path.read_text(), encoding="utf-8")
            return cls.model_validate(metadata)
        except ValidationError as ex:
            raise SeretoValueError(f"invalid finding frontmatter in '{path}'") from ex


class FindingGroupModel(SeretoBaseModel):
    """Representation of a single item in the `report_include` list inside findings.yaml.

    Attributes:
        name: The name of the finding group.
        risks: Explicit risks associated with the finding group for specific versions.
        findings: The list of sub-findings in the format of their unique name to include in the report.
    """

    name: str
    risk: Risk | None = None
    findings: list[str] = Field(min_length=1)

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

    @property
    def uname(self) -> str:
        """Get unique name for the finding group instance.

        Returns:
            The unique name of the finding group.
        """
        return lower_alphanum(f"finding_group_{self.name}")


class FindingsConfigModel(SeretoBaseModel):
    report_include: list[FindingGroupModel]

    @model_validator(mode="after")
    def unique_findings(self) -> Self:
        """Ensure that all finding are included only once."""
        unique_names = [uname for finding_group in self.report_include for uname in finding_group.findings]
        if len(unique_names) != len(set(unique_names)):
            raise ValueError("finding names must be unique")
        return self

    @classmethod
    @validate_call
    def from_yaml(cls, file: FilePath) -> Self:
        """Load FindingsConfigModel from a YAML file."""
        try:
            return cls.model_validate(YAML.load(file))
        except FileNotFoundError:
            raise SeretoPathError(f"file not found at '{file}'") from None
        except PermissionError:
            raise SeretoPathError(f"permission denied for '{file}'") from None
        except ValueError as e:
            raise SeretoValueError("invalid findings.yaml") from e
