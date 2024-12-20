from pydantic import DirectoryPath, validate_call

from sereto.enums import FileFormat
from sereto.models.finding import Finding
from sereto.models.settings import Render
from sereto.models.version import ProjectVersion


@validate_call
def apply_convertor(
    input: str,
    input_format: FileFormat,
    output_format: FileFormat,
    render: Render,
    recipe: str | None = None,
    replacements: dict[str, str] | None = None,
) -> str:
    if input_format == output_format:
        return input

    # Get the conversion recipe
    convert_recipe = render.get_convert_recipe(name=recipe, input_format=input_format, output_format=output_format)

    # Set the initial content
    content = input.encode("utf-8")

    # Apply the conversion tools
    for tool_name in convert_recipe.tools:
        tool = [t for t in render.tools if t.name == tool_name][0]
        content = tool.run(
            input=content,
            replacements=replacements,
        )

    return content.decode("utf-8")


@validate_call
def convert_finding_to_tex(
    finding: Finding,
    render: Render,
    templates: DirectoryPath,
    version: ProjectVersion,
    recipe: str | None = None,
) -> None:
    """Convert a file to TeX format using the specified finding, render, templates, version, and recipe.

    Args:
        finding: The finding object representing the file to be converted.
        render: The render object containing convert_recipes and tools for the conversion.
        templates: The path to the templates directory.
        version: The project version object.
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

    convert_recipe = render.get_convert_recipe(name=recipe, input_format=finding.format, output_format=FileFormat.tex)
    finding_file = finding.path / f"{finding.path_name}{version.path_suffix}.{finding.format.value}"

    for tool_name in convert_recipe.tools:
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
