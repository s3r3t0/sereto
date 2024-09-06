from pathlib import Path
from subprocess import run
from typing import Any

from click import get_app_dir
from pydantic import (
    DirectoryPath,
    Field,
    field_validator,
    model_validator,
    validate_call,
)

from sereto.cli.console import Console
from sereto.enums import FileFormat
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.base import SeretoBaseModel, SeretoBaseSettings
from sereto.types import TypeCategories
from sereto.utils import replace_strings


class RenderRecipe(SeretoBaseModel):
    """Recipe for rendering and converting files using `RenderTool`s.

    Attributes:
        name: name of the recipe
        tools: list of `RenderTool` names to run
    """

    name: str
    tools: list[str] = Field(..., min_length=1)


class ConvertRecipe(RenderRecipe):
    """Recipe for converting between file formats using `RenderTool`s.

    Attributes:
        name: name of the recipe
        input_format: input file format
        tools: list of `RenderTool` names to run
    """

    input_format: FileFormat

    @field_validator("input_format", mode="before")
    @classmethod
    def load_input_format(cls, v: Any) -> FileFormat:
        match v:
            case FileFormat():
                return v
            case str():
                return FileFormat(v)
            case _:
                raise ValueError("invalid type for input_format")


class RenderTool(SeretoBaseModel):
    """Commands used in recipes.

    Attributes:
        name: name of the tool
        command: command to run
        args: list of arguments to pass to the command
    """

    name: str
    command: str
    args: list[str]

    @validate_call
    def run(self, cwd: Path, replacements: dict[str, str] | None = None) -> None:
        command = [self.command] + self.args
        if replacements is not None:
            command = replace_strings(text=command, replacements=replacements)
        Console().log(f"Running command: {' '.join(command)}")
        run(command, cwd=cwd)


class Render(SeretoBaseModel):
    report_recipes: list[RenderRecipe] = Field(..., min_length=1)
    finding_recipes: list[RenderRecipe] = Field(..., min_length=1)
    sow_recipes: list[RenderRecipe] = Field(..., min_length=1)
    target_recipes: list[RenderRecipe] = Field(..., min_length=1)
    convert_recipes: list[ConvertRecipe] = Field(..., min_length=1)
    tools: list[RenderTool] = Field(..., min_length=1)

    @model_validator(mode="after")
    def render_validator(self) -> "Render":
        for recipe in self.report_recipes + self.finding_recipes + self.sow_recipes:
            if not all(tool in [t.name for t in self.tools] for tool in recipe.tools):
                raise ValueError(f"unknown tools in recipe {recipe.name!r}")
        tool_names = [t.name for t in self.tools]
        if len(tool_names) != len(set(tool_names)):
            raise ValueError("tools with duplicate name detected")
        return self


DEFAULT_RENDER_CONFIG = Render(
    report_recipes=[RenderRecipe(name="default-report", tools=["latexmk"])],
    finding_recipes=[RenderRecipe(name="default-finding", tools=["latexmk-finding"])],
    sow_recipes=[RenderRecipe(name="default-sow", tools=["latexmk"])],
    target_recipes=[RenderRecipe(name="default-target", tools=["latexmk-target"])],
    convert_recipes=[
        ConvertRecipe(name="convert-md", input_format=FileFormat.md, tools=["pandoc-md"]),
    ],
    tools=[
        RenderTool(
            name="pandoc-md",
            command="pandoc",
            args=[
                "--from=markdown",
                "--to=latex",
                "--sandbox",
                "--filter=%TEMPLATES%/pandocfilters/acronyms.py",
                "--filter=%TEMPLATES%/pandocfilters/minted.py",
                "--output=%DOC%.tex",
                "%DOC_EXT%",
            ],
        ),
        RenderTool(
            name="latexmk",
            command="latexmk",
            args=["-xelatex", "--shell-escape", "-auxdir=.build_artifacts", "%DOC%"],
        ),
        RenderTool(
            name="latexmk-target",
            command="latexmk",
            args=["-xelatex", "--shell-escape", "-auxdir=.build_artifacts", "-outdir=%TARGET_DIR%", "%DOC%"],
        ),
        RenderTool(
            name="latexmk-finding",
            command="latexmk",
            args=["-xelatex", "--shell-escape", "-auxdir=.build_artifacts", "-outdir=%FINDINGS_DIR%", "%DOC%"],
        ),
    ],
)


DEFAULT_CATEGORIES = {
    "dast",
    "sast",
    "mobile",
    "scenario",
    "infrastructure",
    "rd",
    "portal",
    "cicd",
    "kubernetes",
}


class Settings(SeretoBaseSettings):
    """Global settings:

    Attributes:
        reports_path: path to the directory containing all reports
        templates_path: path to the directory containing templates
        render: rendering settings
        categories: supported categories - list of strings (2-20 lower-alpha characters; also dash and underscore is
            possible in all positions except the first and last one)
    """

    reports_path: DirectoryPath
    templates_path: DirectoryPath
    render: Render = Field(default=DEFAULT_RENDER_CONFIG)
    categories: TypeCategories = Field(default=DEFAULT_CATEGORIES)

    @staticmethod
    def get_path() -> Path:
        return Path(get_app_dir(app_name="sereto")) / "settings.json"

    @classmethod
    def from_file(cls, filepath: Path) -> "Settings":
        try:
            return cls.model_validate_json(filepath.read_bytes())
        except FileNotFoundError:
            raise SeretoPathError(f'file not found at "{filepath}"') from None
        except PermissionError:
            raise SeretoPathError(f'permission denied for "{filepath}"') from None
        except ValueError as e:
            raise SeretoValueError("invalid settings") from e
