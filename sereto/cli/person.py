from pydantic import EmailStr, TypeAdapter, ValidationError, validate_call
from rich.prompt import Prompt

from sereto.cli.console import Console
from sereto.models.person import Person, PersonType


@validate_call
def prompt_user_for_person(person_type: PersonType) -> Person:
    name: str | None = Prompt.ask("Name", console=Console(), default=None)
    business_unit: str | None = Prompt.ask("Business unit", console=Console(), default=None)
    while True:
        try:
            e: str | None = Prompt.ask("Email", console=Console(), default=None)
            email: EmailStr | None = TypeAdapter(EmailStr).validate_python(e) if e is not None else None
            break
        except ValidationError:
            Console().print("[red]Please enter valid email address")
    role: str | None = Prompt.ask("Role", console=Console(), default=None)

    return Person(type=person_type, name=name, business_unit=business_unit, email=email, role=role)
