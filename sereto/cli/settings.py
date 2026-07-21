import json

import click
from pydantic import validate_call

from sereto.exceptions import SeretoValueError
from sereto.models.settings import Settings
from sereto.settings import load_settings_function, write_settings


@validate_call
def edit_settings(non_interactive: bool = False, extra_json: str | None = None) -> None:
    """Edit the global settings file.

    When `non_interactive` is True, the settings are updated from `extra_json` without opening an editor.
    Otherwise, the settings file is opened in the default editor.

    Args:
        non_interactive: If True, run non-interactively.
        extra_json: A JSON string with settings fields to update.
    """
    path = Settings.get_path()

    if non_interactive:
        if extra_json is None:
            raise SeretoValueError("'--extra' is required in non-interactive mode.")
        try:
            raw = json.loads(extra_json)
        except json.JSONDecodeError as e:
            raise SeretoValueError(f"Invalid JSON in '--extra': {e}") from e

        if not isinstance(raw, dict):
            raise SeretoValueError("Value of '--extra' must be a JSON object")

        if path.is_file():
            # Update existing settings with fields from extra_json
            settings = Settings.load_from(path)
            for key in raw:
                if not isinstance(key, str):
                    raise SeretoValueError(f"Invalid key in '--extra': '{key}'")
                if key not in Settings.model_fields:
                    raise SeretoValueError(f"Unknown settings field: '{key}'")
                setattr(settings, key, raw[key])
        else:
            # No existing settings file, construct settings from extra_json
            try:
                settings = Settings.model_validate(raw)
            except Exception as e:
                raise SeretoValueError(f"Failed to initialize settings from '--extra': {e}") from e

        write_settings(settings)
    else:
        if not path.is_file():
            load_settings_function()
        click.edit(filename=str(path))
