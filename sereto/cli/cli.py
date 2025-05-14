import asyncio
import importlib
import importlib.metadata
import importlib.util
from contextlib import suppress
from pathlib import Path

import click
from prompt_toolkit import prompt
from pydantic import FilePath, validate_call

from sereto.cli.commands import sereto_ls, sereto_repl
from sereto.cli.config import (
    add_dates_config,
    add_people_config,
    add_target,
    delete_target,
    edit_config,
    show_config,
    show_dates_config,
    show_people_config,
    show_targets_config,
)
from sereto.cli.finding import show_findings
from sereto.cli.utils import AliasedGroup, Console
from sereto.crypto import decrypt_file
from sereto.enums import OutputFormat
from sereto.exceptions import SeretoException, SeretoPathError, SeretoValueError, handle_exceptions
from sereto.keyring import get_password, set_password
from sereto.models.settings import Settings
from sereto.models.version import ProjectVersion
from sereto.pdf import generate_pdf_finding_group, generate_pdf_report, generate_pdf_sow, generate_pdf_target
from sereto.project import Project, new_project
from sereto.retest import add_retest
from sereto.settings import load_settings_function
from sereto.source_archive import (
    create_source_archive,
    embed_attachment_to_pdf,
    extract_source_archive,
    retrieve_source_archive,
)
from sereto.tui.finding import launch_finding_tui
from sereto.types import TypeProjectId
from sereto.utils import copy_skel, replace_strings


@click.group(cls=AliasedGroup, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=importlib.metadata.version("sereto"))
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Security Reporting Tool.

    This tool provides various commands for managing and generating security reports.
    """
    ctx.obj = Project()


@cli.command()
@handle_exceptions
@click.argument("project_id")
@click.pass_obj
@validate_call
def new(ctx: Project, project_id: TypeProjectId) -> None:
    """Create a new project.

    \b
    Example:
        ```sh
        sereto new PT01234
        ```
    \f

    Args:
        ctx: Project's representation.
        project_id: The ID of the project to be created.
    """
    Console().print("[cyan]We will ask you a few questions to set up the new project.\n")
    name = prompt("Name of the project: ")
    new_project(
        projects_path=ctx.settings.projects_path,
        templates_path=ctx.settings.templates_path,
        id=project_id,
        name=name,
        people=ctx.settings.default_people,
    )


@cli.command()
@handle_exceptions
@click.pass_obj
def ls(ctx: Project) -> None:
    """List all available projects."""
    sereto_ls(settings=ctx.settings)


@cli.command()
def repl() -> None:
    """Start an interactive shell (REPL) for SeReTo."""
    sereto_repl(cli=cli)


@cli.command()
@handle_exceptions
@click.option("-f", "--file", required=True, help="Path to the source.sereto file.", type=Path)
@click.pass_obj
@validate_call
def decrypt(ctx: Project, file: FilePath) -> None:
    """Extract the SeReTo project from the encrypted archive."""
    source_tgz = decrypt_file(file=file, keep_original=True)
    extract_source_archive(file=source_tgz, output_dir=ctx.settings.projects_path, keep_original=False)


@cli.command()
@handle_exceptions
@click.option("-f", "--file", required=True, help="Path to the PDF file.", type=Path)
@click.pass_obj
@validate_call
def unpack(ctx: Project, file: FilePath) -> None:
    """Unpack the SeReTo project from the report's PDF."""
    attachment: Path | None = None

    with suppress(SeretoValueError):
        attachment = retrieve_source_archive(pdf=file, name="source.sereto")

    if attachment is not None:
        source_tgz = decrypt_file(file=attachment, keep_original=False)
    else:
        source_tgz = retrieve_source_archive(pdf=file, name="source.tgz")

    extract_source_archive(file=source_tgz, output_dir=ctx.settings.projects_path, keep_original=False)


# -------------
# sereto config
# -------------


@cli.group(cls=AliasedGroup)
def config() -> None:
    """Project's configuration.

    This group of commands allows you to manage the configuration of a project.
    """


@config.command(name="edit")
@handle_exceptions
@click.pass_obj
def config_edit(ctx: Project) -> None:
    """Launch editor with project's configuration file.\f

    Args:
        ctx: Project's representation.
    """
    edit_config(project=ctx)


@config.command(name="show")
@handle_exceptions
@click.option("-v", "--version", help="Show config at specific version, e.g. 'v1.0'.")
@click.option(
    "-a",
    "--all",
    is_flag=True,
    show_default=True,
    default=False,
    help="Show all versions.",
)
@click.option(
    "-o",
    "--output-format",
    type=click.Choice([of for of in OutputFormat]),
    default=OutputFormat.table,
    help="Output format.",
)
@click.pass_obj
@validate_call
def config_show(ctx: Project, version: ProjectVersion | None, all: bool, output_format: OutputFormat) -> None:
    """Show the projects's configuration.\f

    Args:
        ctx: Project's representation.
        version: The specific version of the configuration to show. If None, the last version is used.
        all: Flag to show all versions of the configuration.
        output_format: The output format for displaying the configuration.
    """
    show_config(config=ctx.config, output_format=output_format, all=all, version=version)


# -------------------
# sereto config dates
# -------------------


@config.group(cls=AliasedGroup, name="dates")
def config_dates() -> None:
    """Configuration of dates.

    This group of commands allows you to manage the dates configuration of a project.
    """


@config_dates.command(name="add")
@handle_exceptions
@click.option("-v", "--version", help="Use specific version, e.g. 'v1.0'.")
@click.pass_obj
@validate_call
def config_dates_add(ctx: Project, version: ProjectVersion | None) -> None:
    """Add date to the project's configuration.\f

    Args:
        ctx: Project's representation.
        version: The specific version of the configuration to add the date to. If None, the last version is used.
    """
    add_dates_config(config=ctx.config, version=version)


@config_dates.command(name="delete")
@handle_exceptions
@click.option("-i", "--index", required=True, type=int, help="Date index to be deleted.")
@click.option("-v", "--version", help="Use specific version, e.g. 'v1.0'.")
@click.pass_obj
@validate_call
def config_dates_delete(ctx: Project, index: int, version: ProjectVersion | None) -> None:
    """Delete date from the project's configuration.\f

    Args:
        ctx: Project's representation.
        index: The index of the date to be deleted. You can obtain the index by running `sereto config dates show`.
        version: The specific version of the configuration to delete the date from. If None, the last version is used.
    """
    if version is None:
        version = ctx.config.last_version

    # Delete the date from the configuration
    ctx.config.at_version(version).delete_date(index=index)

    # Write the configuration
    ctx.config.save()


@config_dates.command(name="show")
@handle_exceptions
@click.option("-v", "--version", help="Show dates from specific version, e.g. 'v1.0'.")
@click.option(
    "-a",
    "--all",
    is_flag=True,
    show_default=True,
    default=False,
    help="Show dates from all versions.",
)
@click.option(
    "-o",
    "--output-format",
    type=click.Choice([of for of in OutputFormat]),
    default=OutputFormat.table,
    help="Output format.",
)
@click.pass_obj
@validate_call
def config_dates_show(ctx: Project, version: ProjectVersion | None, all: bool, output_format: OutputFormat) -> None:
    """Show dates from the project's configuration.\f

    Args:
        ctx: Project's representation.
        version: The specific version of the configuration to show dates from. If None, the last version is used.
        all: Flag to show dates from all versions of the configuration.
        output_format: The output format for displaying the dates.
    """
    show_dates_config(config=ctx.config, output_format=output_format, all=all, version=version)


# --------------------
# sereto config people
# --------------------


@config.group(cls=AliasedGroup, name="people")
def config_people() -> None:
    """Configuration of people.

    This group of commands allows you to manage the people configuration of a project.
    """
    pass


@config_people.command(name="add")
@handle_exceptions
@click.option("-v", "--version", help="Use specific version, e.g. 'v1.0'.")
@click.pass_obj
@validate_call
def config_people_add(ctx: Project, version: ProjectVersion | None) -> None:
    """Add person to the project's configuration.\f

    Args:
        ctx: Project's representation.
        version: The specific version of the configuration to add the person to. If None, the last version is used.
    """
    add_people_config(config=ctx.config, version=version)


@config_people.command(name="delete")
@handle_exceptions
@click.option("-i", "--index", required=True, type=int, help="Person index to be deleted.")
@click.option("-v", "--version", help="Use specific version, e.g. 'v1.0'.")
@click.pass_obj
@validate_call
def config_people_delete(ctx: Project, index: int, version: ProjectVersion | None) -> None:
    """Delete person from the project's configuration.\f

    Args:
        ctx: Project's representation.
        index: The index of the person to be deleted. You can obtain the index by running `sereto config people show`.
        version: The specific version of the configuration to delete the person from. If None, the last version is
            used.
    """
    if version is None:
        version = ctx.config.last_version

    # Delete the date from the configuration
    ctx.config.at_version(version).delete_person(index=index)

    # Write the configuration
    ctx.config.save()


@config_people.command(name="show")
@handle_exceptions
@click.option("-v", "--version", help="Show people at specific version, e.g. 'v1.0'.")
@click.option(
    "-a",
    "--all",
    is_flag=True,
    show_default=True,
    default=False,
    help="Show people from all versions.",
)
@click.option(
    "-o",
    "--output-format",
    type=click.Choice([of for of in OutputFormat]),
    default=OutputFormat.table,
    help="Output format.",
)
@click.pass_obj
@validate_call
def config_people_show(ctx: Project, version: ProjectVersion | None, all: bool, output_format: OutputFormat) -> None:
    """Show people from the project's configuration.\f

    Args:
        ctx: Project's representation.
        version: The specific version of the configuration to show people from. If None, the last version is used.
        all: Flag to show people from all versions of the configuration.
        output_format: The output format for displaying the people.
    """
    show_people_config(config=ctx.config, output_format=output_format, all=all, version=version)


# ---------------------
# sereto config targets
# ---------------------


@config.group(cls=AliasedGroup, name="targets")
def config_targets() -> None:
    """Configuration of targets.

    This group of commands allows you to manage the targets configuration of a project.
    """


@config_targets.command(name="add")
@handle_exceptions
@click.option("-v", "--version", help="Use specific version, e.g. 'v1.0'.")
@click.pass_obj
@validate_call
def config_targets_add(ctx: Project, version: ProjectVersion | None) -> None:
    """Add targets to the project's configuration.\f

    Args:
        ctx: Project's representation.
        version: The specific version of the configuration to add the targets to. If None, the last version is used.
    """
    add_target(
        project_path=ctx.path,
        templates=ctx.settings.templates_path,
        config=ctx.config,
        categories=ctx.settings.categories,
        version=version,
    )


@config_targets.command(name="delete")
@handle_exceptions
@click.option("-i", "--index", required=True, type=int, help="Target index to be deleted.")
@click.option("-v", "--version", help="Use specific version, e.g. 'v1.0'.")
@click.pass_obj
@validate_call
def config_targets_delete(ctx: Project, index: int, version: ProjectVersion | None) -> None:
    """Delete target from the project's configuration.\f

    Args:
        ctx: Project's representation.
        index: The index of the target to be deleted. You can obtain the index by running `sereto config targets show`.
        version: The specific version of the configuration to delete the target from. If None, the last version is
            used.
    """
    delete_target(config=ctx.config, index=index, version=version, interactive=True)


@config_targets.command(name="show")
@handle_exceptions
@click.option("-v", "--version", help="Show targets at specific version, e.g. 'v1.0'.")
@click.option(
    "-a",
    "--all",
    is_flag=True,
    show_default=True,
    default=False,
    help="Show targets from all versions.",
)
@click.option(
    "-o",
    "--output-format",
    type=click.Choice([of for of in OutputFormat]),
    default=OutputFormat.table,
    help="Output format.",
)
@click.pass_obj
@validate_call
def config_targets_show(ctx: Project, version: ProjectVersion | None, all: bool, output_format: OutputFormat) -> None:
    """Show targets from the project's configuration.\f

    Args:
        ctx: Project's representation.
        version: The specific version of the configuration to show targets from. If None, the last version is used.
        all: Flag to show targets from all versions of the configuration.
        output_format: The output format for displaying the targets.
    """
    show_targets_config(config=ctx.config, output_format=output_format, all=all, version=version)


# ---------------
# sereto findings
# ---------------


@cli.group(cls=AliasedGroup)
def findings() -> None:
    """Operations with findings.

    This group of commands allows you to manage the findings of a project.
    """


@findings.command(name="add")
@handle_exceptions
@click.pass_obj
@validate_call
def finding_add(ctx: Project) -> None:
    """Launch TUI app for searching and adding findings from templates.\f

    Args:
        ctx: Project's representation.
    """
    asyncio.run(launch_finding_tui())


@findings.command(name="show")
@handle_exceptions
# @click.option("--target", "-t", type=str, help="Specify target (required for more than one).")
@click.option("-v", "--version", help="Use specific version, e.g. 'v1.0'.")
@click.pass_obj
@validate_call
def finding_show(ctx: Project, version: ProjectVersion | None) -> None:
    """Show findings.\f

    Args:
        ctx: Project's representation.
        version: The version of the findings to show. If None, the last version is used.
    """
    if version is None:
        version = ctx.config.last_version
    show_findings(version_config=ctx.config.at_version(version))


# -----------
# sereto open
# -----------


@cli.group(cls=AliasedGroup)
def open() -> None:
    """Open report, Statement of Work (SoW), or the project's folder."""


@open.command(name="folder")
@handle_exceptions
@click.pass_obj
def open_folder(ctx: Project) -> None:
    """Open the folder containing the current project.\f

    Args:
        ctx: Project's representation.
    """
    click.launch(str(ctx.path))


@open.command(name="report")
@handle_exceptions
@click.option("-v", "--version", help="Use specific version, e.g. 'v1.0'.")
@click.pass_obj
@validate_call
def open_report(ctx: Project, version: ProjectVersion | None) -> None:
    """Open the report document in the default PDF viewer.\f

    Args:
        ctx: Project's representation.
        version: The version of the report that is opened. If None, the last version is used.
    """
    if version is None:
        version = ctx.config.last_version

    if not (report_path := ctx.path / "pdf" / f"report{version.path_suffix}.pdf").is_file():
        raise SeretoPathError(f"File not found '{report_path}'")

    click.launch(str(report_path))


@open.command(name="sow")
@handle_exceptions
@click.option("-v", "--version", help="Use specific version, e.g. 'v1.0'.")
@click.pass_obj
@validate_call
def open_sow(ctx: Project, version: ProjectVersion | None) -> None:
    """Open the Statement of Work (SoW) document in the default PDF viewer.\f

    Args:
        ctx: Project's representation.
        version: The version of the SoW that is opened. If None, the last version is used.
    """
    if version is None:
        version = ctx.config.last_version

    if not (sow_path := ctx.path / "pdf" / f"sow{version.path_suffix}.pdf").is_file():
        raise SeretoPathError(f"File not found '{sow_path}'")

    click.launch(str(sow_path))


# ----------
# sereto pdf
# ----------


@cli.group(cls=AliasedGroup)
def pdf() -> None:
    """Render PDF documents.

    This group of commands allows you to render a PDF report or Statement of Work.
    """


@pdf.command(name="finding-group")
@handle_exceptions
@click.option("-ts", "--target-selector", help="Target selector.")
@click.option("-fs", "--finding-group-selector", help="Finding group selector.")
@click.option("-c", "--converter", help="Convert finding recipe")
@click.option("-r", "--renderer", help="Build TeX finding recipe")
@click.option("-v", "--version", help="Use config at specific version, e.g. 'v1.0'.")
@click.pass_obj
@validate_call
def cli_pdf_finding_group(
    ctx: Project,
    target_selector: int | str | None,
    finding_group_selector: int | str | None,
    converter: str | None,
    renderer: str | None,
    version: ProjectVersion | None,
) -> None:
    """Generate a finding group PDF.\f

    Args:
        ctx: Project's representation.
        target_selector: The target for which the finding group is being generated.
        finding_group_selector: The finding group to be generated.
        converter: The recipe for converting the findings.
        renderer: The recipe for building TeX..
        version: The version of the configuration to use. If None, the last version is used.
    """
    generate_pdf_finding_group(
        project=ctx,
        target_selector=target_selector,
        finding_group_selector=finding_group_selector,
        converter=converter,
        renderer=renderer,
        version=version,
    )


@pdf.command(name="target")
@handle_exceptions
@click.option("-ts", "--target-selector", help="Target selector.")
@click.option("-c", "--convert-recipe", help="Convert finding recipe")
@click.option("-r", "--target-recipe", help="Build TeX target recipe")
@click.option("-v", "--version", help="Use config at specific version, e.g. 'v1.0'.")
@click.pass_obj
@validate_call
def cli_pdf_target(
    ctx: Project,
    target_selector: int | str | None,
    target_recipe: str | None,
    convert_recipe: str | None,
    version: ProjectVersion | None,
) -> None:
    """Generate a target PDF.\f

    Args:
        ctx: Project's representation.
        target_selector: The target for which the PDF is being generated.
        target_recipe: The recipe for building the TeX target.
        convert_recipe: The recipe for converting the findings.
        version: The version of the configuration to use. If None, the last version is used.
    """
    generate_pdf_target(
        project=ctx,
        target_selector=target_selector,
        target_recipe=target_recipe,
        convert_recipe=convert_recipe,
        version=version,
    )


@pdf.command(name="report")
@handle_exceptions
@click.option("-c", "--convert-recipe", help="Convert finding recipe.")
@click.option("-r", "--report-recipe", help="Build TeX report recipe.")
@click.option("-t", "--template", default="report", help="Template for the report.")
@click.option("-v", "--version", help="Use config at specific version, e.g. 'v1.0'.")
# @click.option("-l", "--layout", help="Alternative layout for the report.")
@click.pass_obj
@validate_call
def cli_pdf_report(
    ctx: Project,
    convert_recipe: str | None,
    report_recipe: str | None,
    template: str,
    version: ProjectVersion | None,
) -> None:
    """Generate a report PDF.\f

    Args:
        ctx: Project's representation.
        convert_recipe: The recipe for converting the findings.
        report_recipe: The recipe for building the TeX report.
        template: The template for the report.
        version: The version of the configuration to use. If None, the last version is used.
    """
    # Create report PDF
    report_pdf = generate_pdf_report(
        project=ctx, template=template, report_recipe=report_recipe, convert_recipe=convert_recipe, version=version
    )

    # Create and attach source archive
    archive = create_source_archive(project_path=ctx.path, config=ctx.config)
    embed_attachment_to_pdf(attachment=archive, pdf=report_pdf, name=f"source{archive.suffix}", keep_original=False)


@pdf.command(name="sow")
@handle_exceptions
@click.option("-r", "--sow-recipe", help="Build TeX recipe")
@click.option("-v", "--version", help="Use config at specific version, e.g. 'v1.0'.")
@click.pass_obj
@validate_call
def cli_pdf_sow(ctx: Project, sow_recipe: str | None, version: ProjectVersion | None) -> None:
    """Generate a Statement of Work (SoW) PDF.\f

    Args:
        ctx: Project's representation.
        sow_recipe: The recipe for building the TeX SoW.
        version: The version of the configuration to use. If None, the last version is used.
    """
    generate_pdf_sow(project=ctx, sow_recipe=sow_recipe, version=version)


# -------------
# sereto retest
# -------------


@cli.command(name="retest")
@handle_exceptions
@click.pass_obj
def retest(ctx: Project) -> None:
    """Add retest to the project.\f

    Args:
        ctx: Project's representation.
    """
    add_retest(project=ctx)


# ---------------
# sereto settings
# ---------------


@cli.group(cls=AliasedGroup)
def settings() -> None:
    """Manage global settings.

    This group of commands allows you to display and edit the global settings.
    """


@settings.command(name="edit")
@handle_exceptions
def settings_edit() -> None:
    """Edit settings with the configured editor.

    This command opens the global settings configuration file in the default editor.
    If the configuration file does not exist, it will be created first with the default values.
    """
    if not (path := Settings.get_path()).is_file():
        load_settings_function()
    click.edit(filename=str(path))


@settings.group(cls=AliasedGroup)
def password() -> None:
    """Manage password for the encryption of attached archives."""


@password.command(name="get")
@handle_exceptions
def settings_password_get() -> None:
    """Get the password for the encryption of attached archives.

    This will print the password from the system's keyring.
    """
    click.echo(get_password("sereto", "encrypt_attached_archive"))


@password.command(name="set")
@handle_exceptions
@validate_call
@click.option("--password", prompt=True, hide_input=True)
def settings_password_set(password: str) -> None:
    """Set the password for the encryption of attached archives.

    This will store the password in the system's keyring.
    \f

    Args:
        password: The password to be stored.
    """
    set_password("sereto", "encrypt_attached_archive", password)


@settings.command(name="show")
@handle_exceptions
@click.pass_obj
def settings_show(ctx: Project) -> None:
    """Display the current settings.

    This function prints the current settings of the tool, including both the set values and the default values for any
    unset settings.
    \f

    Args:
        ctx: The settings object containing the tool's global configuration.
    """
    Console().print_json(ctx.settings.model_dump_json())


# ----------------
# sereto templates
# ----------------


@cli.group(cls=AliasedGroup)
def templates() -> None:
    """Operations with templates.

    This group of commands allows you to copy project's skeleton from templates.
    """


@templates.group(cls=AliasedGroup)
def skel() -> None:
    """Project template skeleton files."""


@skel.command(name="copy")
@handle_exceptions
@click.pass_obj
def templates_skel_copy(ctx: Project) -> None:
    """Update the project's templates from the skeleton directory.

    This function copies all files from the templates skeleton directory to the project's directory, overwriting any
    existing files.
    \f

    Args:
        ctx: Project's representation.
    """
    copy_skel(templates=ctx.settings.templates_path, dst=ctx.path, overwrite=True)


@templates.group(cls=AliasedGroup)
def target_skel() -> None:
    """Target template skeleton files."""


@target_skel.command(name="copy")
@handle_exceptions
@click.option("--target", "-t", type=str, help="Specify target (required for more than one).")
@click.pass_obj
@validate_call
def templates_target_skel_copy(ctx: Project, target: str | None) -> None:
    """Update the target's templates from the skeleton directory.

    This function copies all files from the templates skeleton directory to the target's directory, overwriting any
    existing files.
    \f

    Args:
        ctx: Project's representation.
        target: Selector of a target for which the templates are being copied.
    """
    selected_target = ctx.config.last_config.select_target(categories=ctx.settings.categories, selector=target)

    copy_skel(
        templates=ctx.settings.templates_path / "categories" / selected_target.data.category,
        dst=selected_target.path,
        overwrite=True,
    )


# -----------
# entry point
# -----------


def load_plugins() -> None:
    """Load plugins from the plugins directory.

    This function loads plugins from the configured directory and registers their commands with the CLI. The plugin
    support needs to be enabled in the settings.
    """
    settings = load_settings_function()

    # Check if plugins are enabled
    if not settings.plugins.enabled:
        return

    # Get plugins directory
    plugins_dir = Path(
        replace_strings(text=settings.plugins.directory, replacements={"%TEMPLATES%": str(settings.templates_path)})
    )
    if not plugins_dir.is_dir():
        raise SeretoPathError(f"Plugins directory not found: '{plugins_dir}'")

    # Load plugins from the directory
    for file in plugins_dir.glob(pattern="*.py"):
        # Skip dunder files like __init__.py
        if file.name.startswith("__"):
            continue

        # Register commands
        module_name = f"plugins.{file.name[:-3]}"
        try:
            # Create a module specification
            spec = importlib.util.spec_from_file_location(module_name, file)
            if spec is None or spec.loader is None:
                Console().log(f"Failed to load plugin: {file.name}")
                continue

            # Create a new module based on the specification
            module = importlib.util.module_from_spec(spec)

            # Execute the module to initialize it
            spec.loader.exec_module(module)
        except ModuleNotFoundError as e:
            Console().log(f"Plugin module '{e.name}' not found: '{file.name}'")
            continue

        # Run the plugin's register_commands function
        if hasattr(module, "register_commands"):
            module.register_commands(cli)
            Console().log(f"Plugin registered: '{file.name}'")


def entry_point() -> None:
    with suppress(SeretoException):
        load_plugins()

    cli()
