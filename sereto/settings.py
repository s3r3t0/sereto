from pathlib import Path
from typing import TypeVar

from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import yes_no_dialog
from pydantic import validate_call
from typing_extensions import ParamSpec

from sereto.cli.utils import Console
from sereto.models.settings import Settings

P = ParamSpec("P")
R = TypeVar("R")


def _ask_for_dirpath(message: str) -> Path:
    while True:
        input = prompt(f"{message}: ")
        path = Path(input).resolve()

        if path.exists():
            if path.is_dir():
                return path
            else:
                Console().print("the provided path is not a directory")
                continue
        else:
            if yes_no_dialog(title="Warning", text=f"Directory '{path}' does not exist. Create?").run():
                path.mkdir(parents=True)
            return path


def load_settings_function() -> Settings:
    if (path := Settings.get_path()).is_file():
        return Settings.load_from(path)
    else:
        Console().print("[cyan]It seems like this is the first time you're running the tool. Let's set it up!\n")

        projects_path = _ask_for_dirpath("Enter the path to the projects directory")
        templates_path = _ask_for_dirpath("Enter the path to the templates directory")

        Console().print("\nThank you! The minimal setup is complete.")
        Console().print(
            "You can always change these settings or configure additional using [magenta]sereto settings[/magenta]"
        )
        Console().rule()

        settings = Settings(projects_path=projects_path, templates_path=templates_path)
        write_settings(settings)

        return settings


@validate_call
def write_settings(settings: Settings) -> None:
    """Write settings to a standard system location.

    Args:
        settings: The Settings object to write.
    """
    settings_path = Settings.get_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    with settings_path.open("w", encoding="utf-8") as f:
        f.write(settings.model_dump_json(indent=2, exclude_defaults=True))
        f.write("\n")
