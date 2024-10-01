import click
from rich.prompt import Prompt

from sereto.cli.utils import Console
from sereto.exceptions import SeretoRuntimeError
from sereto.models.settings import Settings
from sereto.models.target import Target, TargetDast, TargetSast


def prompt_user_for_target(settings: Settings) -> Target:
    """Interactively prompt for a target's details.

    Args:
        settings: The Settings object.

    Returns:
        The target as provided by the user.
    """
    Console().line()
    category = Prompt.ask("Category", choices=list(settings.categories), console=Console())
    name = Prompt.ask("Name", console=Console())

    match category:
        case "dast":
            target: Target = TargetDast(category=category, name=name)
        case "sast":
            target = TargetSast(category=category, name=name)
        case _:
            target = Target(category=category, name=name)

    target_edited = click.edit(target.model_dump_json(indent=2))

    if target_edited is None:
        raise SeretoRuntimeError("aborting, editor closed without saving")

    return Target.model_validate_json(target_edited)
