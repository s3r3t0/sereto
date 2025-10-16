from pydantic import validate_call

from sereto.enums import FileFormat
from sereto.models.settings import Render


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
