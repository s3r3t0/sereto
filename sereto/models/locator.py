from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import AnyUrl, Discriminator, IPvAnyAddress, IPvAnyNetwork, validate_call

from sereto.models.base import SeretoBaseModel


class UrlLocatorModel(SeretoBaseModel):
    """Model representing a URL locator.

    Attributes:
        type: The discriminator for the locator type, which is always "url".
        value: The URL of the locator.
        description: Optional description of the URL locator.
    """

    type: Literal["url"] = "url"
    value: AnyUrl
    description: str | None = None


class IpLocatorModel(SeretoBaseModel):
    """Model representing an IP locator.

    Attributes:
        type: The discriminator for the locator type, which is always "ip".
        value: The IP address or network of the locator.
        description: Optional description of the IP locator.
    """

    type: Literal["ip"] = "ip"
    value: IPvAnyAddress | IPvAnyNetwork
    description: str | None = None


class FileLocatorModel(SeretoBaseModel):
    """Model representing a file locator.

    Attributes:
        type: The discriminator for the locator type, which is always "file".
        value: The path to the file, may contain specific line.
        description: Optional description of the file locator.
    """

    type: Literal["file"] = "file"
    value: str  # Path to the file
    description: str | None = None


LocatorModel = Annotated[UrlLocatorModel | IpLocatorModel | FileLocatorModel, Discriminator("type")]


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
        desc = f", description={loc.description!r}" if loc.description else ""
        lines.append(f'{{type={loc.type!r}, value="{loc.value}"{desc}}},')
    return "[\n    " + "\n    ".join(lines) + "\n]"
