from pathlib import Path

from pydantic import validate_call

from sereto.enums import FileFormat
from sereto.exceptions import SeretoValueError
from sereto.models.finding import Finding
from sereto.models.settings import Render
from sereto.models.version import ReportVersion


@validate_call
def convert_file_to_tex(
    finding: Finding,
    render: Render,
    templates: Path,
    version: ReportVersion,
    recipe: str | None = None,
) -> None:
    """
    Convert a file to TeX format using the specified finding, render, templates, version, and recipe.

    Args:
        finding: The finding object representing the file to be converted.
        render: The render object containing convert_recipes and tools for the conversion.
        templates: The path to the templates directory.
        version: The report version object.
        recipe: The name of the recipe to use for conversion. Defaults to None.

    Raises:
        SeretoValueError: If no converter is found for the specified file format or if the specified recipe is not
            found.

    Returns:
        None
    """

    assert finding.path is not None

    if finding.format == FileFormat.tex:
        return
    convert_recipes = [c for c in render.convert_recipes if c.input_format == finding.format]
    if len(convert_recipes) == 0:
        raise SeretoValueError(f"no converter for {finding.format.value!r} format")

    if recipe is None:  # user did not provide recipe's name -> use the first
        run_recipe = convert_recipes[0]
    else:
        if len(res := [c for c in convert_recipes if c.name == recipe]) != 1:
            raise SeretoValueError(f"no converter found with name {recipe!r}")
        run_recipe = res[0]

    finding_file: Path = finding.path / f"{finding.path_name}{version.path_suffix}.{finding.format.value}"

    for tool_name in run_recipe.tools:
        tool = [t for t in render.tools if t.name == tool_name][0]
        tool.run(
            cwd=finding.path,
            replacements={
                "%DOC%": str(finding_file.resolve().with_suffix("")),
                "%DOC_EXT%": str(finding_file.resolve()),
                "%DOCFILE%": finding_file.resolve().stem,
                "%DOCFILE_EXT%": finding_file.resolve().name,
                "%DIR%": str(finding.path.resolve()),
                "%TEMPLATES%": str(templates),
            },
        )
