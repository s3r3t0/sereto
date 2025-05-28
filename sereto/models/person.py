from enum import Enum

from pydantic import EmailStr, Field

from sereto.models.base import SeretoBaseModel


class PersonType(str, Enum):
    """Enum representing a person's role in regards to the current assessment.

    Attributes:
        author: Author of the report.
        requestor: Person who requested the assessment.
        asset_owner: Owner of the asset being tested.
        security_officer: Security officer responsible for the asset.
        technical_contact: Person who can answer technical questions about the asset.
        reviewer: Reviewer of the report.
    """

    author = "author"
    requestor = "requestor"
    asset_owner = "asset_owner"
    security_officer = "security_officer"
    technical_contact = "technical_contact"
    reviewer = "reviewer"


class Person(SeretoBaseModel):
    """Model representing a person.

    Attributes:
        type: Type of the person in relation to the assessment.
        name: Full name of the person.
        business_unit: Business unit the person belongs to.
        email: Email address of the person.
        role: Role of the person within the organization.
    """

    type: PersonType = Field(strict=False)  # `strict=False` allows coercion from string
    name: str | None = None
    business_unit: str | None = None
    email: EmailStr | None = None
    role: str | None = None
