# Settings

[`Settings`](../reference/models/settings.md#sereto.models.settings.Settings) provide a way to customize SeReTo according to your needs.

The **location** where the configuration file is stored is determined by using [`click.get_app_dir`](https://click.palletsprojects.com/en/latest/api/#click.get_app_dir) function, to provide the most appropriate location for the specific operating system. For example, on *Linux*, the configuration file is stored in `~/.config/sereto/settings.json` and on *Windows*, it is likely stored in `C:\Users\<username>\AppData\Local\sereto\settings.json`.

It is possible to override settings values by using environment variables. Each setting can be mapped to an environment variable by using the following naming convention: `SERETO_<SETTING_NAME>`. For example:

- To override `projects_path`, set the environment variable `SERETO_PROJECTS_PATH`. For example `SERETO_PROJECTS_PATH=/tmp/projects`.
- To override `categories`, set the environment variable `SERETO_CATEGORIES`. For example `SERETO_CATEGORIES='["generic", "dast"]'`.

This behaviour is inherited from Pydantic Settings. Therefore check the [Settings Management](https://docs.pydantic.dev/latest/concepts/pydantic_settings) for more information about how to manage settings.

Settings consist of the following fields:

## `projects_path`

The path to the directory where the *projects* are located.

## `templates_path`

The path to the directory where the *templates* are located.

## `render`

Defines *recipes* and *tools* which are used when rendering Typst or TeX files, or converting between different formats (e.g. from Markdown to Typst or TeX).

The `render` field consists of the following:

### `report_recipes`

List of [`RenderRecipe`](../reference/models/settings.md#sereto.models.settings.RenderRecipe)s, which define the tools used to render a *report*.

Example:

=== "JSON"
    ```json
    {
        "name": "default-report-typ",
        "tools": [
            "typst"
        ],
        "intermediate_format": "typ"
    }
    ```

=== "Python"
    ```py
    RenderRecipe(
        name="default-report-typ",
        tools=[
            "typst"
        ],
        intermediate_format=FileFormat.typ
    )
    ```

### `finding_group_recipes`

List of [`RenderRecipe`](../reference/models/settings.md#sereto.models.settings.RenderRecipe)s, which define the tools used to render a *finding group*.

Example:

=== "JSON"
    ```json
    {
        "name": "default-finding-typ",
        "tools": [
            "typst-partial"
        ],
        "intermediate_format": "typ"
    }
    ```

=== "Python"
    ```py
    RenderRecipe(
        name="default-finding-typ",
        tools=[
            "typst-partial"
        ],
        intermediate_format=FileFormat.typ
    )
    ```

### `sow_recipes`

List of [`RenderRecipe`](../reference/models/settings.md#sereto.models.settings.RenderRecipe)s, which define the tools used to render a *statement-of-work*.

Example:

=== "JSON"
    ```json
    {
        "name": "default-sow-typ",
        "tools": [
            "typst"
        ],
        "intermediate_format": "typ"
    }
    ```

=== "Python"
    ```py
    RenderRecipe(
        name="default-sow-typ",
        tools=[
            "typst"
        ],
        intermediate_format=FileFormat.typ
    )
    ```

### `target_recipes`

List of [`RenderRecipe`](../reference/models/settings.md#sereto.models.settings.RenderRecipe)s, which define the tools used to render a *target*.

Example:

=== "JSON"
    ```json
    {
        "name": "default-target-typ",
        "tools": [
            "typst-partial"
        ],
        "intermediate_format": "typ"
    }
    ```

=== "Python"
    ```py
    RenderRecipe(
        name="default-target-typ",
        tools=[
            "typst-partial"
        ],
        intermediate_format=FileFormat.typ
    )
    ```

### `convert_recipes`

List of [`ConvertRecipe`](../reference/models/settings.md#sereto.models.settings.ConvertRecipe)s, which define the tools used to convert between different formats.

Example:

=== "JSON"
    ```json
    {
        "name": "convert-md-to-typ",
        "input_format": "md",
        "output_format": "typ",
        "tools": [
            "pandoc-md-typ"
        ]
    }
    ```

=== "Python"
    ```py
    ConvertRecipe(
        name="convert-md-to-typ",
        input_format=FileFormat.md,
        output_format=FileFormat.typ,
        tools=[
            "pandoc-md-typ"
        ]
    )
    ```

### `tools`

List of [`RenderTool`](../reference/models/settings.md#sereto.models.settings.RenderTool)s, which are the commands with their parameters. Tools are referenced in recipes by their name.

The following variables are always available and will be automatically substituted for their value before running the command:

 - `%DOC%`: path to the current file without the extension
 - `%DOC_EXT%`: path to the current file with the extension
 - `%DOCFILE%`: filename without extension
 - `%DOCFILE_EXT%`: filename with extensions
 - `%DIR%`: path to the directory, where the current file is located
 - `%TEMPLATES%`: path to the directory, where the templates are located
 - `%PROJECT%`: path to the project directory

Example:

=== "JSON"
    ```json
    {
        "name": "typst-partial",
        "command": "typst",
        "args": [
            "compile",
            "%DOC_EXT%",
            "--root",
            "%DIR%/../..",
            "--font-path",
            "%TEMPLATES%/fonts"
        ]
    }
    ```

=== "Python"
    ```py
    RenderTool(
        name="typst-partial",
        command="typst",
        args=[
            "compile",
            "%DOC_EXT%",
            "--root",
            "%DIR%/../..",
            "--font-path",
            "%TEMPLATES%/fonts"
        ]
    )
    ```

## `categories`

A list of categories that can be used to group findings.
