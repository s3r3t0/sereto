import click
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import radiolist_dialog

from sereto.cli.utils import Console
from sereto.exceptions import SeretoRuntimeError
from sereto.models.settings import Settings
from sereto.models.target import TargetDastModel, TargetModel, TargetSastModel


def prompt_user_for_target(settings: Settings) -> TargetModel:
    """Interactively prompt for a target's details.

    Args:
        settings: The Settings object.

    Returns:
        The target as provided by the user.
    """
    Console().line()
    category = radiolist_dialog(
        title="New target",
        text="Category:",
        values=[(c, c.upper()) for c in list(settings.categories)],
    ).run()
    name = prompt("Name: ")

    match category:
        case "dast":
            target: TargetModel = TargetDastModel(category=category, name=name)
        case "sast":
            target = TargetSastModel(category=category, name=name)
        case _:
            target = TargetModel(category=category, name=name)

    target_edited = click.edit(target.model_dump_json(indent=2))

    if target_edited is None:
        raise SeretoRuntimeError("aborting, editor closed without saving")

    return TargetModel.model_validate_json(target_edited)
