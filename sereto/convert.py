from typing import TYPE_CHECKING

from pydantic import DirectoryPath, validate_call

from sereto.enums import FileFormat
from sereto.models.settings import Render

if TYPE_CHECKING:
    from sereto.finding import SubFinding


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


def convert_subfinding_to_tex(
    sub_finding: "SubFinding",
    render: Render,
    templates: DirectoryPath,
    recipe: str | None = None,
) -> None:
    """Convert a sub-finding to TeX format.

    Args:
        sub_finding: The sub-finding object.
        render: The render object containing convert_recipes and tools for the conversion.
        templates: The path to the templates directory.
        recipe: The name of the recipe to use for conversion. Defaults to None.

    Raises:
        SeretoValueError: If no converter is found for the specified file format or if the specified recipe is not
            found.

    Returns:
        None
    """
    convert_recipe = render.get_convert_recipe(name=recipe, input_format=FileFormat.md, output_format=FileFormat.tex)

    for tool_name in convert_recipe.tools:
        tool = [t for t in render.tools if t.name == tool_name][0]
        tool.run(
            cwd=sub_finding.path,
            replacements={
                "%DOC%": str(sub_finding.path.resolve().with_suffix("")),
                "%DOC_EXT%": str(sub_finding.path.resolve()),
                "%DOCFILE%": sub_finding.path.resolve().stem,
                "%DOCFILE_EXT%": sub_finding.path.resolve().name,
                "%DIR%": str(sub_finding.path.resolve()),
                "%TEMPLATES%": str(templates),
            },
        )
