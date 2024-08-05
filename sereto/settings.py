from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import TypeVar

from click import get_current_context
from pydantic import ValidationError, validate_call
from rich.prompt import Confirm, Prompt
from typing_extensions import ParamSpec

from sereto.cli.console import Console
from sereto.models.settings import Settings

P = ParamSpec("P")
R = TypeVar("R")


def load_settings(f: Callable[P, R]) -> Callable[P, R]:
    """Decorator which calls `load_settings_function` and provides Settings as the first argument"""

    @wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        settings = load_settings_function()
        return get_current_context().invoke(f, settings, *args, **kwargs)

    return wrapper


def _ask_for_dirpath(prompt: str) -> Path:
    while True:
        input = Prompt.ask(prompt, console=Console())
        path = Path(input).resolve()

        if path.exists():
            if path.is_dir():
                return path
            else:
                Console().print("the provided path is not a directory")
                continue
        else:
            if Confirm.ask(
                f'[yellow]Directory "{path}" does not exist. Create?',
                console=Console(),
                default=True,
            ):
                path.mkdir(parents=True)
            return path


def load_settings_function() -> Settings:
    if (path := Settings.get_path()).is_file():
        return Settings.from_file(path)
    else:
        Console().print("[cyan]It seems like this is the first time you're running the tool. Let's set it up!\n")

        reports_path = _ask_for_dirpath(":open_file_folder: Enter the path to the reports directory")
        templates_path = _ask_for_dirpath(":open_file_folder: Enter the path to the templates directory")

        Console().print("\nThank you! The minimal setup is complete.")
        Console().print(
            "You can always change these settings or configure additional using [magenta]sereto settings[/magenta]"
        )
        Console().rule()

        settings = Settings(reports_path=reports_path, templates_path=templates_path)
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


@validate_call
def is_settings_valid(print: bool = False) -> bool:
    """Check if the settings are valid.

    Args:
        print: Whether to print the validation status. Defaults to False.

    Returns:
        True if the settings are valid, False otherwise.
    """
    try:
        Settings.model_validate_json(Settings.get_path().read_bytes())
        if print:
            Console().log("[green]Settings are valid")
        return True
    except ValidationError:
        if print:
            Console().log("[red]Settings are invalid")
        return False
