from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import AnyUrl, Field, IPvAnyAddress, IPvAnyNetwork, field_validator, validate_call
from unidecode import unidecode

from sereto.enums import Environment
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.base import SeretoBaseModel
from sereto.models.finding import FindingGroup, FindingsConfig
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

        fc = FindingsConfig.from_yaml(file=self.path / "findings.yaml")

        for finding in fc.findings:
            finding.path = self.path / "findings" / finding.path_name

        return fc

    @validate_call
    def select_finding_group(self, selector: int | str | None = None) -> FindingGroup:
        """Select a finding group from the target.

        Args:
            selector: The index or name of the finding group to select.

        Returns:
            The selected finding group.
        """
        finding_groups = self.findings_config.finding_groups

        # only single finding group present
        if selector is None:
            if len(finding_groups) != 1:
                raise SeretoValueError(
                    f"cannot select finding group; no selector provided and there are {len(finding_groups)} finding "
                    "groups present"
                )
            return finding_groups[0]

        # by index
        if isinstance(selector, int) or selector.isnumeric():
            ix = selector - 1 if isinstance(selector, int) else int(selector) - 1
            if not (0 <= ix <= len(finding_groups) - 1):
                raise SeretoValueError("finding group index out of range")
            return finding_groups[ix]

        # by uname
        fg_matches = [fg for fg in finding_groups if fg.uname == selector]
        if len(fg_matches) != 1:
            raise SeretoValueError(f"finding group with uname {selector!r} not found")
        return fg_matches[0]


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
