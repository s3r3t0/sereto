from prompt_toolkit import prompt
from pydantic import EmailStr, TypeAdapter, ValidationError, validate_call

from sereto.cli.utils import Console
from sereto.models.person import Person, PersonType


@validate_call
def prompt_user_for_person(person_type: PersonType) -> Person:
    """Interactively prompt for a person's details.

    Args:
        person_type: The type of person to prompt for.

    Returns:
        The person as provided by the user.
    """
    name = prompt("Name: ")
    business_unit = prompt("Business unit: ")
    while True:
        try:
            e = prompt("Email: ")
            ta: TypeAdapter[EmailStr] = TypeAdapter(EmailStr)  # hack for mypy
            email: EmailStr | None = ta.validate_python(e) if len(e) > 0 else None
            break
        except ValidationError:
            Console().print("[red]Please enter valid email address")
    role = prompt("Role: ")

    return Person(
        type=person_type,
        name=name if len(name) > 0 else None,
        business_unit=business_unit if len(business_unit) > 0 else None,
        email=email,
        role=role if len(role) > 0 else None,
    )
