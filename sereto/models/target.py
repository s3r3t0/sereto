from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, IPvAnyAddress, IPvAnyNetwork, ValidationInfo, field_validator, model_validator

from sereto.enums import Environment, TargetExposure
from sereto.models.base import SeretoBaseModel
from sereto.models.document import DocumentModel
from sereto.models.locator import LocatorModel
from sereto.settings import load_settings_function
from sereto.utils import lower_alphanum


class TargetModel(SeretoBaseModel, extra="allow"):
    """Base class for model representing the details of a target.

    Attributes:
        id: Unique identifier for the target, optional.
        category: The category of the target.
        name: The name of the target (e.g. DAST, SAST).
        locators: List of locators for the target, such as URLs or IP addresses, source code files, etc.
    """

    id: str | None = None
    category: str
    name: str
    locators: list[LocatorModel] = Field(default_factory=list)
    documents: list[DocumentModel] = Field(default_factory=list)

    @field_validator("category")
    @classmethod
    def category_valid(cls, v: str, info: ValidationInfo) -> str:
        # Skip validation if categories provided in context (for testing)
        if info.context and (categories := info.context.get("categories")):
            if v in categories:
                return v
            else:
                raise ValueError(f'category "{v}" is unknown')

        # Normal validation: load settings
        settings = load_settings_function()
        if v in settings.categories:
            return v
        else:
            raise ValueError(f'category "{v}" is unknown')

    @property
    def uname(self) -> str:
        """Unique name for the target instance (version is not included)."""
        return lower_alphanum(f"target_{self.category}_{self.name}")


class TargetDastModel(TargetModel):
    """Model representing a target which is characterized by IP address."""

    @model_validator(mode="before")
    @classmethod
    def migrate_internal_to_exposure(cls, data: Any) -> Any:
        """Migrate deprecated 'internal' field to 'exposure'."""
        if isinstance(data, dict):
            internal = data.get("internal")
            exposure = data.get("exposure")

            if internal is not None:
                # Determine the expected exposure based on internal value
                expected_exposure = TargetExposure.internal if internal else TargetExposure.external
                expected_exposure_str = "internal" if internal else "external"

                if exposure is not None:
                    # Both are present - check for conflicts
                    # Normalize exposure to string for comparison
                    exposure_str = exposure if isinstance(exposure, str) else exposure.value
                    if exposure_str != expected_exposure_str:
                        raise ValueError(f"Conflicting values: internal={internal} and exposure={exposure}.")
                else:
                    # Set exposure based on internal (use enum)
                    data["exposure"] = expected_exposure

                # Remove the internal field
                data.pop("internal", None)

        return data

    dst_ips_dynamic: bool = False
    dst_ips_dynamic_details: str | None = None
    src_ips: list[IPvAnyAddress | IPvAnyNetwork] = []
    ip_filtering: bool = False
    ip_allowed: bool | None = None
    authentication: bool = False
    credentials_provided: bool | None = None
    exposure: TargetExposure = TargetExposure.external
    environment: Environment = Environment.acceptance
    waf_present: bool = False
    waf_whitelisted: bool | None = None


class TargetSastModel(TargetModel):
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


class TargetMobileModel(TargetModel):
    """Model representing the details of the 'mobile' category."""

    class MobilePlatform(SeretoBaseModel):
        file_integrity: dict[str, str] = {}

    class AndroidMobilePlatform(MobilePlatform):
        package_name: str | None = None
        version_name: str | None = None
        version_code: str | None = None

    class iOSMobilePlatform(MobilePlatform):
        bundle_id: str | None = None
        short_version_string: str | None = None
        version: str | None = None

    android: AndroidMobilePlatform | None = AndroidMobilePlatform()
    ios: iOSMobilePlatform | None = iOSMobilePlatform()


type AnyTargetModel = TargetDastModel | TargetSastModel | TargetMobileModel | TargetModel

_TARGET_MODEL_BY_CATEGORY: dict[str, type[TargetModel]] = {
    "dast": TargetDastModel,
    "sast": TargetSastModel,
    "mobile": TargetMobileModel,
}


def parse_target_model(
    data: AnyTargetModel | Mapping[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> AnyTargetModel:
    """Parse raw target data into the correct target model subtype."""
    if isinstance(data, TargetModel):
        payload: dict[str, Any] = data.model_dump()
    elif isinstance(data, Mapping):
        payload = dict(data)
    else:
        raise TypeError("target data must be a mapping or TargetModel instance")

    category = payload.get("category")
    model_cls = _TARGET_MODEL_BY_CATEGORY.get(category, TargetModel) if isinstance(category, str) else TargetModel
    return model_cls.model_validate(payload, context=context)
