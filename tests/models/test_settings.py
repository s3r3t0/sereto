import pytest
from pydantic import ValidationError

from sereto.enums import FileFormat
from sereto.models.settings import DEFAULT_RENDER_CONFIG, ConvertRecipe, Render, RenderRecipe, RenderTool


def _tool(name: str) -> RenderTool:
    return RenderTool(name=name, command=name, args=[])


def _render(**overrides) -> Render:
    data = {
        "report_recipes": [RenderRecipe(name="report", tools=["report-tool"], intermediate_format=FileFormat.tex)],
        "finding_group_recipes": [
            RenderRecipe(name="finding", tools=["finding-tool"], intermediate_format=FileFormat.tex)
        ],
        "sow_recipes": [RenderRecipe(name="sow", tools=["sow-tool"], intermediate_format=FileFormat.tex)],
        "target_recipes": [RenderRecipe(name="target", tools=["target-tool"], intermediate_format=FileFormat.tex)],
        "convert_recipes": [
            ConvertRecipe(
                name="convert",
                tools=["convert-tool"],
                input_format=FileFormat.md,
                output_format=FileFormat.tex,
            )
        ],
        "tools": [
            _tool("report-tool"),
            _tool("finding-tool"),
            _tool("sow-tool"),
            _tool("target-tool"),
            _tool("convert-tool"),
        ],
    }
    data.update(overrides)
    return Render(**data)


def test_default_render_config_is_valid():
    assert DEFAULT_RENDER_CONFIG.tools


def test_render_rejects_duplicate_tool_names():
    with pytest.raises(ValidationError, match="tools with duplicate name detected"):
        _render(tools=[_tool("duplicate"), _tool("duplicate")])


def test_render_rejects_unknown_tool_in_target_recipe():
    with pytest.raises(ValidationError, match="unknown tools in recipe 'target'"):
        _render(
            target_recipes=[RenderRecipe(name="target", tools=["missing-tool"], intermediate_format=FileFormat.tex)]
        )


def test_render_rejects_unknown_tool_in_convert_recipe():
    with pytest.raises(ValidationError, match="unknown tools in recipe 'convert'"):
        _render(
            convert_recipes=[
                ConvertRecipe(
                    name="convert",
                    tools=["missing-tool"],
                    input_format=FileFormat.md,
                    output_format=FileFormat.tex,
                )
            ]
        )
