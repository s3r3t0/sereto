import re
from typing import overload

import ruamel.yaml
from pydantic import validate_call

YAML = ruamel.yaml.YAML()


@overload
def replace_strings(text: str, replacements: dict[str, str]) -> str: ...


@overload
def replace_strings(text: list[str], replacements: dict[str, str]) -> list[str]: ...


@validate_call
def replace_strings(text: str | list[str], replacements: dict[str, str]) -> str | list[str]:
    """One-pass string replacement with values from dictionary.

    Args:
        text: The input text.
        replacements: Dictionary with replacements. Key-value in dictionary refers to
            pattern string and replacement string, respectively.

    Returns:
        String (or list of strings, depending on the input value) obtained by applying the replacements from the
            `replacements` dictionary.
    """
    if len(text) == 0 or len(replacements) == 0:
        return text

    pattern = re.compile("|".join([re.escape(rep) for rep in replacements]))

    if isinstance(text, str):
        return pattern.sub(lambda match: replacements[match.group(0)], text)
    else:
        return [pattern.sub(lambda match: replacements[match.group(0)], item) for item in text]
