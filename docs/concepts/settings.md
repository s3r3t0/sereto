# Settings

[`Settings`](../reference/models/settings.md#sereto.models.settings.Settings) provide a way to customize SeReTo according to your needs.

The **location** where the configuration file is stored is determined by using [`click.get_app_dir`](https://click.palletsprojects.com/en/latest/api/#click.get_app_dir) function, to provide the most appropriate location for the specific operating system. For example, on *Linux*, the configuration file is stored in `~/.config/sereto/settings.json` and on *Windows*, it is likely stored in `C:\Users\<username>\AppData\Local\sereto\settings.json`.

Settings consist of the following fields:

## `reports_path`

The path to the directory where the *reports* are located.

## `templates_path`

The path to the directory where the *templates* are located.

## `render`

Defines *recipes* and *tools* which are used when rendering the TeX files or converting between different formats (e.g. from Markdown to TeX).

The `render` field consists of the following:

### `report_recipes`

List of [`RenderRecipe`](../reference/models/settings.md#sereto.models.settings.RenderRecipe)s, which define the tools used to render a *report*.

Example:

=== "JSON"
    ```json
    {
        "name": "default-report",
        "tools": [
            "latexmk"
        ]
    }
    ```

=== "Python"
    ```py
    RenderRecipe(
        name="default-report",
        tools=[
            "latexmk"
        ]
    )
    ```

### `finding_recipes`

List of [`RenderRecipe`](../reference/models/settings.md#sereto.models.settings.RenderRecipe)s, which define the tools used to render a *finding*.

In addition to the standard variables defined below in the [`tools`](#tools) section, the following variables are available:

 - `%FINDINGS_DIR%`: path to the "findings" directory inside

Example:

=== "JSON"
    ```json
    {
        "name": "default-finding",
        "tools": [
            "latexmk-finding"
        ]
    }
    ```

=== "Python"
    ```py
    RenderRecipe(
        name="default-finding",
        tools=[
            "latexmk-finding"
        ]
    )
    ```

### `sow_recipes`

List of [`RenderRecipe`](../reference/models/settings.md#sereto.models.settings.RenderRecipe)s, which define the tools used to render a *statement-of-work*.

Example:

=== "JSON"
    ```json
    {
        "name": "default-sow",
        "tools": [
            "latexmk"
        ]
    }
    ```

=== "Python"
    ```py
    RenderRecipe(
        name="default-sow",
        tools=[
            "latexmk"
        ]
    )
    ```

### `target_recipes`

List of [`RenderRecipe`](../reference/models/settings.md#sereto.models.settings.RenderRecipe)s, which define the tools used to render a *target*.

In addition to the standard variables defined below in the [`tools`](#tools) section, the following variables are available:

 - `%TARGET_DIR%`: path to the target's directory

Example:

=== "JSON"
    ```json
    {
        "name": "default-target",
        "tools": [
            "latexmk-target"
        ]
    }
    ```

=== "Python"
    ```py
    RenderRecipe(
        name="default-target",
        tools=[
            "latexmk-target"
        ]
    )
    ```

### `convert_recipes`

List of [`ConvertRecipe`](../reference/models/settings.md#sereto.models.settings.ConvertRecipe)s, which define the tools used to convert between different formats.

Example:

=== "JSON"
    ```json
    {
        "name": "convert-md",
        "input_format": "md",
        "tools": [
            "pandoc-md"
        ]
    }
    ```

=== "Python"
    ```py
    ConvertRecipe(
        name="convert-md",
        input_format=FileFormat.md,
        tools=[
            "pandoc-md"
        ]
    )
    ```

### `tools`

List of [`RenderTool`](../reference/models/settings.md#sereto.models.settings.RenderTool)s, which are the commands with their parameters. Tools are referenced in recipes by their name.

The following variables are always available and will be automatically substituted for their value before running the command:

> Other variables may be available, depending on the context. Check the sections above concerning individual recipe types: [`finding_recipes`](#finding_recipes), [`target_recipes`](#target_recipes).

 - `%DOC%`: path to the current file without the extension
 - `%DOC_EXT%`: path to the current file with the extension
 - `%DOCFILE%`: filename without extension
 - `%DOCFILE_EXT%`: filename with extensions
 - `%DIR%`: path to the directory, where the current file is located
 - `%TEMPLATES%`: path to the directory, where the templates are located

Example:

=== "JSON"
    ```json
    {
        "name": "latexmk",
        "command": "latexmk",
        "args": [
            "-xelatex",
            "--shell-escape",
            "-auxdir=.build_artifacts",
            "%DOC%"
        ]
    }
    ```

=== "Python"
    ```py
    RenderTool(
        name="latexmk",
        command="latexmk",
        args=[
            "-xelatex",
            "--shell-escape",
            "-auxdir=.build_artifacts",
            "%DOC%"
        ]
    )
    ```

## `categories`

A list of categories that can be used to group findings.
