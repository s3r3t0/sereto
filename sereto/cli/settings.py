import json
from pathlib import Path

import click
from pydantic import validate_call

from sereto.exceptions import SeretoValueError
from sereto.models.settings import Settings
from sereto.settings import load_settings_function, write_settings


@validate_call
def edit_settings(extra_file: Path | None = None) -> None:
    """Edit the global settings file.

    When `extra_file` is provided, the settings are updated non-interactively from the JSON file.
    Otherwise, the settings file is opened in the default editor.

    Args:
        extra_file: Path to a JSON file with settings fields to update (non-interactive).
    """
    if not (path := Settings.get_path()).is_file():
        load_settings_function()

    if extra_file is not None:
        try:
            raw = json.loads(extra_file.read_text())
        except json.JSONDecodeError as e:
            raise SeretoValueError(f"Invalid JSON in '{extra_file}': {e}") from e

        if not isinstance(raw, dict):
            raise SeretoValueError(f"Content of '{extra_file}' must be a JSON object")

        settings = Settings.load_from(path)

        for key in raw:
            if not isinstance(key, str):
                raise SeretoValueError(f"Invalid key in '{extra_file}': '{key}'")
            if key not in Settings.model_fields:
                raise SeretoValueError(f"Unknown settings field: '{key}'")
            setattr(settings, key, raw[key])

        write_settings(settings)
    else:
        click.edit(filename=str(path))
