from enum import Enum

from pydantic import EmailStr, Field

from sereto.models.base import SeretoBaseModel


class PersonType(str, Enum):
    """Enum representing a person's role in regards to the current assessment."""

    author = "author"
    requestor = "requestor"
    asset_owner = "asset_owner"
    security_officer = "security_officer"
    technical_contact = "technical_contact"
    reviewer = "reviewer"


class Person(SeretoBaseModel):
    """Model representing a person."""

    type: PersonType = Field(strict=False)  # `strict=False` allows coercion from string
    name: str | None = None
    business_unit: str | None = None
    email: EmailStr | None = None
    role: str | None = None
