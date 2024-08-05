from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import AnyUrl, Field, IPvAnyAddress, IPvAnyNetwork, field_validator
from unidecode import unidecode

from sereto.enums import Environment
from sereto.exceptions import SeretoPathError
from sereto.models.base import SeretoBaseModel
from sereto.models.finding import FindingsConfig
from sereto.settings import load_settings_function


class Target(SeretoBaseModel, extra="allow"):
    """Base class for model representing the details of a target."""

    category: str
    name: str
    path: Path | None = Field(exclude=True, default=None)

    @field_validator("category")
    @classmethod
    def category_valid(cls, v: str) -> str:
        settings = load_settings_function()
        if v in settings.categories:
            return v
        else:
            raise ValueError(f'category "{v}" is unknown')

    @property
    def uname(self) -> str:
        """Unique name for the target instance.

        Returns:
            The unique name of the target.
        """
        name: str = "".join([x.lower() for x in unidecode(self.name) if x.isalnum()])
        return f"target_{self.category}_{name}"

    @cached_property
    def findings_config(self) -> FindingsConfig:
        if self.path is None:
            raise SeretoPathError("target path not configured")

        fc = FindingsConfig.from_yaml_file(filepath=self.path / "findings.yaml")

        for finding in fc.findings:
            finding.path = self.path / "findings" / finding.path_name

        return fc


class TargetDast(Target):
    """Model representing a target which is characterized by IP address."""

    dst_ips: list[IPvAnyAddress | IPvAnyNetwork] = []
    dst_ips_dynamic: bool = False
    dst_ips_dynamic_details: str | None = None
    src_ips: list[IPvAnyAddress | IPvAnyNetwork] = []
    ip_filtering: bool = False
    ip_allowed: bool | None = None
    authentication: bool = False
    credentials_provided: bool | None = None
    internal: bool = False
    environment: Environment = Environment.acceptance
    urls: list[AnyUrl] = []
    waf_present: bool = False
    waf_whitelisted: bool | None = None
    clickpath: str | None = None
    api: str | None = None


class TargetSast(Target):
    """Model representing the details of the 'sast' category.
    Attributes:
        code_origin: where we obtained the code - Version Control System or archive (ZIP/TAR/...)
        code_origin_name: origin details - e.g. "Gitlab" or "project_source.zip"
        code_integrity: dictionary containing file name with hash type as the key and corresponding hash as the value
        source_code_analyzer_files: additional files from source code analyzers (like Fortify SCA or Sonarqube)
    """

    code_origin: Literal["vcs", "archive"] | None = None
    code_origin_name: str | None = None
    code_integrity: dict[str, str] = {}
    source_code_analyzer_files: list[str] = []
