import hashlib
import re
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import overload

import click
import ruamel.yaml
from humanize import naturalsize
from pydantic import FilePath, validate_call

from sereto.cli.utils import Console
from sereto.exceptions import SeretoPathError, SeretoValueError

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
        replacements: Dictionary with replacements. Key-value in dictionary refers to pattern string and replacement
            string, respectively.

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


@validate_call
def _compute_md5(file: FilePath) -> str:
    """Computes the MD5 hash of the file content.

    This must be used only for non-cryptographic purposes.

    Args:
        file: The path to the file.

    Returns:
        The MD5 hash of the file content.
    """
    md5 = hashlib.md5()

    with file.open("rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            md5.update(chunk)

    return md5.hexdigest()


@validate_call
def write_if_different(file: Path, content: str) -> bool:
    """Writes content to file only if the content is different from the existing file content.

    The comparison is done using the MD5 hash of the file content.

    Args:
        file: The path to the file.
        content: The content to write to the file.

    Returns:
        True if new content was written to the file, False otherwise.
    """
    with NamedTemporaryFile(delete=False, mode="w", encoding="utf-8") as tmp_file:
        tmp_file_path = Path(tmp_file.name)
        tmp_file_path.write_text(content, encoding="utf-8")

    if file.is_file() and _compute_md5(tmp_file_path) == _compute_md5(file):
        # No changes, remove the temporary file
        tmp_file_path.unlink()
        return False

    # Changes detected, write the content to the file
    shutil.move(src=tmp_file_path, dst=file)
    return True


@validate_call
def assert_file_size_within_range(
    file: FilePath, max_bytes: int, min_bytes: int = 0, interactive: bool = False
) -> None:
    """Evaluates if the file size is within the specified range.

    If `interactive` is True, the user is first prompted whether to continue if the file size is not within the range.

    Args:
        file: The path to the file.
        max_bytes: The maximum file size in bytes.
        min_bytes: The minimum file size in bytes. Defaults to 0.
        interactive: If True, the user is prompted whether to continue if the file size is not within the range.
            Defaults to False.

    Raises:
        SeretoPathError: If the file does not exist.
        SeretoValueError: If the file size is not within the specified range.
    """
    # Check the input values
    if not file.is_file():
        raise SeretoPathError(f"File '{file}' does not exist")

    if not 0 <= min_bytes <= max_bytes:
        raise SeretoValueError(f"Invalid size threshold range: {min_bytes} - {max_bytes}")

    # Get the file size in bytes
    size = file.stat().st_size

    # Check if the file size is within the specified range
    if min_bytes <= size <= max_bytes:
        return

    # File size is not within the range

    Console().log(
        f"[yellow]File '{file}' size is {naturalsize(size, binary=True)}, which is not within the allowed range "
        f"{naturalsize(min_bytes, binary=True)} - {naturalsize(max_bytes, binary=True)}"
    )

    # In interactive mode, user can choose to continue
    if interactive and click.confirm("Do you want to continue?", default=False):
        return

    # Otherwise, raise an error
    raise SeretoValueError(f"File '{file}' size is not within the range {min_bytes} - {max_bytes} B")
