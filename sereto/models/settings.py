import subprocess
import time
from pathlib import Path
from textwrap import dedent
from typing import Annotated, Any, Self

from annotated_types import MinLen
from click import get_app_dir
from pydantic import (
    DirectoryPath,
    Field,
    FilePath,
    ValidationError,
    field_validator,
    model_validator,
    validate_call,
)
from rich.markdown import Markdown

from sereto.cli.utils import Console
from sereto.enums import FileFormat
from sereto.exceptions import SeretoCalledProcessError, SeretoPathError, SeretoValueError
from sereto.models.base import SeretoBaseModel, SeretoBaseSettings
from sereto.types import TypeCategories
from sereto.utils import replace_strings


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
    def run(self, cwd: DirectoryPath, replacements: dict[str, str] | None = None) -> None:
        command = [self.command] + self.args
        if replacements is not None:
            command = replace_strings(text=command, replacements=replacements)
        Console().log(
            Markdown(
                dedent(f"""\
                    Running command:
                    ```bash
                    {' '.join(command)}
                    ```
                """)
            )
        )
        try:
            start_time = time.time()
            subprocess.run(command, cwd=cwd, capture_output=True, check=True)
            end_time = time.time()
            Console().log(f"Command finished in {end_time - start_time:.2f} s")
        except subprocess.CalledProcessError as e:
            Console().log(Markdown(f"Command failed with error: `{e}`"))
            raise SeretoCalledProcessError("command execution failed") from e


class RenderRecipe(SeretoBaseModel):
    """Recipe for rendering and converting files using `RenderTool`s.

    Attributes:
        name: name of the recipe
        tools: list of `RenderTool` names to run
    """

    name: str
    tools: Annotated[list[str], MinLen(1)]


class ConvertRecipe(RenderRecipe):
    """Recipe for converting between file formats using `RenderTool`s.

    Attributes:
        name: name of the recipe
        input_format: input file format
        tools: list of `RenderTool` names to run
    """

    input_format: FileFormat
    output_format: FileFormat

    @field_validator("input_format", "output_format", mode="before")
    @classmethod
    def load_file_format(cls, v: Any) -> FileFormat:
        match v:
            case FileFormat():
                return v
            case str():
                return FileFormat(v)
            case _:
                raise ValueError("invalid type for FileFormat")


class Render(SeretoBaseModel):
    report_recipes: Annotated[list[RenderRecipe], MinLen(1)]
    finding_group_recipes: Annotated[list[RenderRecipe], MinLen(1)]
    sow_recipes: Annotated[list[RenderRecipe], MinLen(1)]
    target_recipes: Annotated[list[RenderRecipe], MinLen(1)]
    convert_recipes: Annotated[list[ConvertRecipe], MinLen(1)]
    tools: Annotated[list[RenderTool], MinLen(1)]

    @model_validator(mode="after")
    def render_validator(self) -> Self:
        for recipe in self.report_recipes + self.finding_group_recipes + self.sow_recipes:
            if not all(tool in [t.name for t in self.tools] for tool in recipe.tools):
                raise ValueError(f"unknown tools in recipe {recipe.name!r}")
        tool_names = [t.name for t in self.tools]
        if len(tool_names) != len(set(tool_names)):
            raise ValueError("tools with duplicate name detected")
        return self

    @validate_call
    def get_report_recipe(self, name: str | None) -> RenderRecipe:
        if name is None:
            return self.report_recipes[0]

        if len(res := [r for r in self.report_recipes if r.name == name]) != 1:
            raise SeretoValueError(f"no report recipe found with name {name!r}")

        return res[0]

    @validate_call
    def get_finding_group_recipe(self, name: str | None) -> RenderRecipe:
        if name is None:
            return self.finding_group_recipes[0]

        if len(res := [r for r in self.finding_group_recipes if r.name == name]) != 1:
            raise SeretoValueError(f"no finding recipe found with name {name!r}")

        return res[0]

    @validate_call
    def get_sow_recipe(self, name: str | None) -> RenderRecipe:
        if name is None:
            return self.sow_recipes[0]

        if len(res := [r for r in self.sow_recipes if r.name == name]) != 1:
            raise SeretoValueError(f"no SoW recipe found with name {name!r}")

        return res[0]

    @validate_call
    def get_target_recipe(self, name: str | None) -> RenderRecipe:
        if name is None:
            return self.target_recipes[0]

        if len(res := [r for r in self.target_recipes if r.name == name]) != 1:
            raise SeretoValueError(f"no target recipe found with name {name!r}")

        return res[0]

    @validate_call
    def get_convert_recipe(
        self, name: str | None, input_format: FileFormat, output_format: FileFormat
    ) -> ConvertRecipe:
        acceptable_recipes = [
            r for r in self.convert_recipes if r.input_format == input_format and r.output_format == output_format
        ]
        if len(acceptable_recipes) == 0:
            raise SeretoValueError(f"no convert recipe found for {input_format.value} -> {output_format.value}")

        if name is None:
            return acceptable_recipes[0]

        if len(res := [r for r in acceptable_recipes if r.name == name]) != 1:
            raise SeretoValueError(
                f"no convert recipe found for {input_format.value} -> {output_format.value} with name {name!r}"
            )

        return res[0]


DEFAULT_RENDER_CONFIG = Render(
    report_recipes=[RenderRecipe(name="default-report", tools=["latexmk"])],
    finding_group_recipes=[RenderRecipe(name="default-finding", tools=["latexmk-finding"])],
    sow_recipes=[RenderRecipe(name="default-sow", tools=["latexmk"])],
    target_recipes=[RenderRecipe(name="default-target", tools=["latexmk-target"])],
    convert_recipes=[
        ConvertRecipe(
            name="convert-md", input_format=FileFormat.md, output_format=FileFormat.tex, tools=["pandoc-md"]
        ),
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
            args=[
                "-xelatex",
                "-interaction=batchmode",
                "-halt-on-error",
                "--shell-escape",
                "-auxdir=.build_artifacts",
                "%DOC%",
            ],
        ),
        RenderTool(
            name="latexmk-target",
            command="latexmk",
            args=[
                "-xelatex",
                "-interaction=batchmode",
                "-halt-on-error",
                "--shell-escape",
                "-auxdir=.build_artifacts",
                "-outdir=%TARGET_DIR%",
                "%DOC%",
            ],
        ),
        RenderTool(
            name="latexmk-finding",
            command="latexmk",
            args=[
                "-xelatex",
                "-interaction=batchmode",
                "-halt-on-error",
                "--shell-escape",
                "-auxdir=.build_artifacts",
                "-outdir=%FINDINGS_DIR%",
                "%DOC%",
            ],
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


class Plugins(SeretoBaseModel):
    """Plugins settings.

    Attributes:
        enabled: whether plugins are enabled
        directory: path to the directory containing plugins (`%TEMPLATES%` will be replaced with the templates path`)
    """

    enabled: bool = False
    directory: str = "%TEMPLATES%/plugins"


class Settings(SeretoBaseSettings):
    """Global settings:

    Attributes:
        reports_path: path to the directory containing all reports
        templates_path: path to the directory containing templates
        render: rendering settings
        categories: supported categories - list of strings (2-20 lower-alpha characters; also dash and underscore is
            possible in all positions except the first and last one)

    Raises:
        SeretoPathError: If the file is not found or permission is denied.
        SeretoValueError: If the JSON file is invalid.
    """

    reports_path: DirectoryPath
    templates_path: DirectoryPath
    render: Render = Field(default=DEFAULT_RENDER_CONFIG)
    categories: TypeCategories = Field(default=DEFAULT_CATEGORIES)
    plugins: Plugins = Field(default_factory=Plugins)

    @staticmethod
    def get_path() -> Path:
        return Path(get_app_dir(app_name="sereto")) / "settings.json"

    @classmethod
    def load_from(cls, file: FilePath) -> Self:
        try:
            return cls.model_validate_json(file.read_bytes())
        except FileNotFoundError:
            raise SeretoPathError(f"file not found at '{file}'") from None
        except PermissionError:
            raise SeretoPathError(f"permission denied for '{file}'") from None
        except ValidationError as e:
            raise SeretoValueError(f"invalid settings\n\n{e}") from e
