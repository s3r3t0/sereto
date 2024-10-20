import re
import tarfile
from typing import overload

import click
import ruamel.yaml
from humanize import naturalsize
from pydantic import DirectoryPath, FilePath, validate_call

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
def untar_sources(file: FilePath, output_dir: DirectoryPath, keep_original: bool = True) -> None:
    """Extracts sources from a given tarball file.

    Expects the tarball file to be Gzip-compressed.

    Args:
        file: The path to the .tgz file.
        output_dir: The directory where the sources will be extracted.
        keep_original: If True, the original tarball file is kept. Defaults to True.
    """
    with tarfile.open(file, "r:gz") as tar:
        tar.extractall(path=output_dir)
        Console().log(f"[green]+[/green] Extracted sources from '{file}' to '{output_dir}'")

    if not keep_original:
        file.unlink()
        Console().log(f"[red]-[/red] Deleted tarball: '{file}'")


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
