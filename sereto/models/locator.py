from collections.abc import Iterable
from typing import Annotated, Literal, get_args

from pydantic import AnyUrl, Discriminator, IPvAnyAddress, IPvAnyNetwork, field_serializer, validate_call

from sereto.models.base import SeretoBaseModel


class BaseLocatorModel(SeretoBaseModel):
    """Common base model for all locator types.

    You should typically use `LocatorModel` instead of this class directly.

    Attributes:
        type: The type of locator (discriminator field).
        description: An optional description of the locator.
    """

    type: str
    description: str | None = None


class UrlLocatorModel(BaseLocatorModel):
    """Model representing a URL locator.

    Attributes:
        type: The discriminator for the locator type, which is always "url".
        value: The URL of the locator.
        description: Optional description of the URL locator.
    """

    type: Literal["url"] = "url"
    value: AnyUrl

    @field_serializer("value")
    def serialize_value(self, value: AnyUrl) -> str:
        return str(value)


class HostnameLocatorModel(BaseLocatorModel):
    """Model representing a hostname locator.

    Attributes:
        type: The discriminator for the locator type, which is always "hostname".
        value: The hostname of the locator.
        description: Optional description of the hostname locator.
    """

    type: Literal["hostname"] = "hostname"
    value: str  # Hostname as a string


class DomainLocatorModel(BaseLocatorModel):
    """Model representing a domain locator.

    Attributes:
        type: The discriminator for the locator type, which is always "domain".
        value: The domain of the locator.
        description: Optional description of the domain locator.
    """

    type: Literal["domain"] = "domain"
    value: str  # Domain as a string


class IpLocatorModel(BaseLocatorModel):
    """Model representing an IP locator.

    Attributes:
        type: The discriminator for the locator type, which is always "ip".
        value: The IP address or network of the locator.
        description: Optional description of the IP locator.
    """

    type: Literal["ip"] = "ip"
    value: IPvAnyAddress | IPvAnyNetwork

    @field_serializer("value")
    def serialize_value(self, value: IPvAnyAddress | IPvAnyNetwork) -> str:
        return str(value)


class FileLocatorModel(BaseLocatorModel):
    """Model representing a file locator.

    Attributes:
        type: The discriminator for the locator type, which is always "file".
        value: The path to the file, may contain specific line.
        description: Optional description of the file locator.
    """

    type: Literal["file"] = "file"
    value: str  # Path to the file


# For automatic subclass selection during validation
LocatorModel = Annotated[
    UrlLocatorModel | HostnameLocatorModel | DomainLocatorModel | IpLocatorModel | FileLocatorModel,
    Discriminator("type"),
]


@validate_call
def dump_locators_to_toml(locators: Iterable[LocatorModel]) -> str:
    """Dump locators to a TOML string.

    Args:
        locators: An iterable of LocatorModel instances.

    Returns:
        A TOML formatted string representing the locators.
    """
    if len(loc_list := list(locators)) == 0:
        return "[]"

    lines: list[str] = []
    for loc in loc_list:
        desc = f', description="{loc.description}"' if loc.description else ""
        lines.append(f'{{type="{loc.type}", value="{loc.value}"{desc}}},')
    return "[\n    " + "\n    ".join(lines) + "\n]"


def get_locator_types() -> list[str]:
    """Get all locator types defined in LocatorModel."""
    union_type, *_ = get_args(LocatorModel)  # first arg is `UrlLocatorModel | HostnameLocatorModel | ...`
    locator_classes = get_args(union_type)  # the individual model classes
    return [cls.model_fields["type"].default for cls in locator_classes]
