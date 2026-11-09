from collections.abc import Mapping
from secrets import token_hex
from typing import Annotated, Any, Literal
from pydantic import (
    BeforeValidator,
    Discriminator,
    Field,
    IPvAnyAddress,
    IPvAnyNetwork,
    Tag,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)
from sereto.enums import Environment, TargetExposure
from sereto.models.base import SeretoBaseModel
from sereto.models.document import DocumentModel
from sereto.models.locator import LocatorModel
from sereto.models.version import ProjectVersion
from sereto.settings import load_settings_function

TARGET_ID_PATTERN = r"[A-Za-z0-9_][A-Za-z0-9_.-]*"


def target_directory_name(target_id: str, version: ProjectVersion) -> str:
    return f"target_{target_id}{version.path_suffix}"


class TargetModel(SeretoBaseModel, extra="allow"):
    """Base class for model representing the details of a target.

    Attributes:
        id: Stable filesystem identifier, generated as eight random hex characters when not provided.
        category: The category of the target.
        name: The name of the target (e.g. DAST, SAST).
        locators: List of locators for the target, such as URLs or IP addresses, source code files, etc.
    """

    id: str = Field(
        default_factory=lambda: token_hex(4), pattern=f"^{TARGET_ID_PATTERN}$", frozen=True, validate_default=True
    )
    category: str
    name: str
    locators: list[LocatorModel] = Field(default_factory=list)
    documents: list[DocumentModel] = Field(default_factory=list)

    @field_validator("id", mode="before")
    @classmethod
    def generate_missing_id(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return token_hex(4)
        return value

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


class TargetDastModel(TargetModel):
    """Model representing a target which is characterized by IP address."""

    @model_validator(mode="before")
    @classmethod
    def migrate_internal_to_exposure(cls, data: Any) -> Any:
        """Migrate deprecated 'internal' field to 'exposure'."""
        if isinstance(data, dict):
            data = data.copy()
            internal = data.get("internal")
            exposure = data.get("exposure")

            if internal is not None:
                # Determine the expected exposure based on internal value
                expected_exposure = TargetExposure.internal if internal else TargetExposure.external
                expected_exposure_str = "internal" if internal else "external"

                if exposure is not None:
                    # Both are present - check for conflicts
                    # Normalize exposure to string for comparison
                    exposure_str = exposure.value if isinstance(exposure, TargetExposure) else exposure
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
    src_ips: list[IPvAnyAddress | IPvAnyNetwork] = []  # ty: ignore[unsupported-operator]
    ip_filtering: bool = False
    ip_allowed: bool | None = None
    authentication: bool = False
    credentials_provided: bool | None = None
    exposure: TargetExposure = Field(strict=False, default=TargetExposure.external)
    environment: Environment = Field(strict=False, default=Environment.acceptance)
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


def _target_payload(data: object) -> object:
    if isinstance(data, TargetModel):
        return data.model_dump()
    if isinstance(data, Mapping):
        return dict(data)
    return data


def _target_discriminator(data: object) -> str | None:
    category: object
    if isinstance(data, TargetModel):
        category = data.category
    elif isinstance(data, Mapping):
        category = data.get("category")
    else:
        return None
    if not isinstance(category, str):
        return None
    return category if category in {"dast", "sast", "mobile"} else "generic"


type AnyTargetModel = Annotated[
    Annotated[TargetDastModel, Tag("dast")]
    | Annotated[TargetSastModel, Tag("sast")]
    | Annotated[TargetMobileModel, Tag("mobile")]
    | Annotated[TargetModel, Tag("generic")],
    Discriminator(_target_discriminator),
    BeforeValidator(_target_payload),
]

_TARGET_ADAPTER = TypeAdapter(AnyTargetModel)


def parse_target_model(
    data: AnyTargetModel | Mapping[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> AnyTargetModel:
    """Parse raw target data into the correct target model subtype."""
    if not isinstance(data, TargetModel | Mapping):
        raise TypeError("target data must be a mapping or TargetModel instance")
    return _TARGET_ADAPTER.validate_python(data, context=context)
