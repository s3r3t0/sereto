import importlib.metadata
from contextlib import suppress
from pathlib import Path

import click
import keyring
from prompt_toolkit import prompt
from pydantic import FilePath, validate_call

from sereto.cli.commands import sereto_ls, sereto_repl
from sereto.cli.config import (
    add_dates_config,
    add_people_config,
    add_targets_config,
    delete_dates_config,
    delete_people_config,
    delete_targets_config,
    edit_config,
    show_config,
    show_dates_config,
    show_people_config,
    show_targets_config,
)
from sereto.cli.utils import AliasedGroup, Console
from sereto.crypto import decrypt_file
from sereto.enums import FileFormat, OutputFormat
from sereto.exceptions import SeretoPathError, SeretoRuntimeError, SeretoValueError, handle_exceptions
from sereto.finding import add_finding, show_findings, update_findings
from sereto.models.project import Project
from sereto.models.settings import Settings
from sereto.models.version import ProjectVersion
from sereto.pdf import render_sow_pdf
from sereto.project import load_project
from sereto.report import (
    copy_skel,
    new_report,
    render_report_j2,
    render_sow_j2,
    # report_cleanup,
    report_create_missing,
    report_pdf,
)
from sereto.retest import add_retest
from sereto.settings import load_settings, load_settings_function
from sereto.source_archive import extract_source_archive, retrieve_source_archive
from sereto.types import TypeProjectId


@click.group(cls=AliasedGroup, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=importlib.metadata.version("sereto"))
def cli() -> None:
    """Security Reporting Tool.

    This tool provides various commands for managing and generating security reports.
    """


@cli.command()
@handle_exceptions
@click.argument("report_id")
@load_settings
def new(settings: Settings, report_id: TypeProjectId) -> None:
    """Create a new report.

    \b
    Example:
        ```sh
        sereto new PT01234
        ```
    \f

    Args:
        settings: The settings object containing the tool's global configuration.
        report_id: The ID of the report to be created.
    """
    Console().print("[cyan]We will ask you a few questions to set up the new report.\n")
    name = prompt("Name of the report: ")
    new_report(settings=settings, id=report_id, name=name)


@cli.command()
@handle_exceptions
@load_settings
def ls(settings: Settings) -> None:
    """List all available reports.\f

    Args:
        settings: The settings object containing the tool's global configuration.
    """
    sereto_ls(settings=settings)


@cli.command()
def repl() -> None:
    """Start an interactive shell (REPL) for SeReTo."""
    sereto_repl(cli=cli)


@cli.command()
@handle_exceptions
@click.option("-f", "--file", required=True, help="Path to the source.sereto file.", type=Path)
@load_settings
@validate_call
def decrypt(settings: Settings, file: FilePath) -> None:
    """Extract the SeReTo project from the encrypted archive."""
    source_tgz = decrypt_file(file=file, keep_original=True)
    extract_source_archive(file=source_tgz, output_dir=settings.reports_path, keep_original=False)


@cli.command()
@handle_exceptions
@click.option("-f", "--file", required=True, help="Path to the PDF file.", type=Path)
@load_settings
@validate_call
def unpack(settings: Settings, file: FilePath) -> None:
    """Unpack the SeReTo project from the report's PDF."""
    attachment: Path | None = None

    with suppress(SeretoValueError):
        attachment = retrieve_source_archive(pdf=file, name="source.sereto")

    if attachment is not None:
        source_tgz = decrypt_file(file=attachment, keep_original=False)
    else:
        source_tgz = retrieve_source_archive(pdf=file, name="source.tgz")

    extract_source_archive(file=source_tgz, output_dir=settings.reports_path, keep_original=False)


# -------------
# sereto config
# -------------


@cli.group(cls=AliasedGroup)
def config() -> None:
    """Report's configuration.

    This group of commands allows you to manage the configuration of a report.
    """


@config.command(name="edit")
@handle_exceptions
@load_settings
def config_edit(settings: Settings) -> None:
    """Launch editor with report's configuration file.\f

    Args:
        settings: The settings object containing the tool's global configuration.
    """
    edit_config(settings=settings)


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
@load_project
def config_show(
    project: Project,
    version: ProjectVersion | None,
    all: bool,
    output_format: OutputFormat,
) -> None:
    """Show the reports's configuration.\f

    Args:
        project: Project's representation.
        version: The specific version of the configuration to show.
        all: Flag to show all versions of the configuration.
        output_format: The output format for displaying the configuration.
    """
    show_config(project=project, output_format=output_format, all=all, version=version)


# -------------------
# sereto config dates
# -------------------


@config.group(cls=AliasedGroup, name="dates")
def config_dates() -> None:
    """Configuration of dates.

    This group of commands allows you to manage the dates configuration of a report.
    """


@config_dates.command(name="add")
@handle_exceptions
@load_project
def config_dates_add(project: Project) -> None:
    """Add date to the report's configuration.\f

    Args:
        project: Project's representation.
    """
    add_dates_config(project=project)


@config_dates.command(name="delete")
@handle_exceptions
@click.option("-i", "--index", required=True, type=int, help="Date index to be deleted.")
@load_project
def config_dates_delete(project: Project, index: int) -> None:
    """Delete date from the report's configuration.\f

    Args:
        project: Project's representation.
        index: The index of the date to be deleted. You can obtain the index by running `sereto config dates show`.
    """
    delete_dates_config(project=project, index=index)


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
@load_project
def config_dates_show(
    project: Project,
    version: ProjectVersion | None,
    all: bool,
    output_format: OutputFormat,
) -> None:
    """Show dates from the report's configuration.\f

    Args:
        project: Project's representation.
        version: The specific version of the configuration to show dates from.
        all: Flag to show dates from all versions of the configuration.
        output_format: The output format for displaying the dates.
    """
    show_dates_config(project=project, output_format=output_format, all=all, version=version)


# --------------------
# sereto config people
# --------------------


@config.group(cls=AliasedGroup, name="people")
def config_people() -> None:
    """Configuration of people.

    This group of commands allows you to manage the people configuration of a report.
    """
    pass


@config_people.command(name="add")
@handle_exceptions
@load_project
def config_people_add(project: Project) -> None:
    """Add person to the report's configuration.\f

    Args:
        project: Project's representation.
    """
    add_people_config(project=project)


@config_people.command(name="delete")
@handle_exceptions
@click.option("-i", "--index", required=True, type=int, help="Person index to be deleted.")
@load_project
def config_people_delete(project: Project, index: int) -> None:
    """Delete person from the report's configuration.\f

    Args:
        project: Project's representation.
        index: The index of the person to be deleted. You can obtain the index by running `sereto config people show`.
    """
    delete_people_config(project=project, index=index)


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
@load_project
def config_people_show(
    project: Project,
    version: ProjectVersion | None,
    all: bool,
    output_format: OutputFormat,
) -> None:
    """Show people from the report's configuration.\f

    Args:
        project: Project's representation.
        version: The specific version of the configuration to show people from.
        all: Flag to show people from all versions of the configuration.
        output_format: The output format for displaying the people.
    """
    show_people_config(project=project, output_format=output_format, all=all, version=version)


# ---------------------
# sereto config targets
# ---------------------


@config.group(cls=AliasedGroup, name="targets")
def config_targets() -> None:
    """Configuration of targets.

    This group of commands allows you to manage the targets configuration of a report.
    """


@config_targets.command(name="add")
@handle_exceptions
@load_project
def config_targets_add(project: Project) -> None:
    """Add targets to the report's configuration.\f

    Args:
        project: Project's representation.
    """
    add_targets_config(project=project)


@config_targets.command(name="delete")
@handle_exceptions
@click.option("-i", "--index", required=True, type=int, help="Target index to be deleted.")
@load_project
def config_targets_delete(project: Project, index: int) -> None:
    """Delete target from the report's configuration.\f

    Args:
        project: Project's representation.
        index: The index of the target to be deleted. You can obtain the index by running `sereto config targets show`.
    """
    delete_targets_config(project=project, index=index, interactive=True)


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
@load_project
def config_targets_show(
    project: Project,
    version: ProjectVersion | None,
    all: bool,
    output_format: OutputFormat,
) -> None:
    """Show targets from the report's configuration.\f

    Args:
        project: Project's representation.
        version: The specific version of the configuration to show targets from.
        all: Flag to show targets from all versions of the configuration.
        output_format: The output format for displaying the targets.
    """
    show_targets_config(project=project, output_format=output_format, all=all, version=version)


# ---------------
# sereto findings
# ---------------


@cli.group(cls=AliasedGroup)
def findings() -> None:
    """Operations with findings.

    This group of commands allows you to manage the findings of a report.
    """


@findings.command(name="add")
@handle_exceptions
@click.option("--target", "-t", type=str, help="Specify target (required for more than one).")
@click.option(
    "--format",
    "-f",
    type=click.Choice([it.value for it in FileFormat]),
    default="md",
    help="Template file format.",
)
@click.argument("name")
@load_project
def finding_add(project: Project, target: str | None, format: str, name: str) -> None:
    """Add finding from template.\f

    Args:
        project: Project's representation.
        target: The target for which the finding is being added.
        format: The file format of the template.
        name: The name of the finding.
    """
    add_finding(
        project=project,
        target_selector=target,
        format=format,
        name=name,
        interactive=True,
    )


@findings.command(name="show")
@handle_exceptions
# @click.option("--target", "-t", type=str, help="Specify target (required for more than one).")
@click.option("-v", "--version", help="Use specific version, e.g. 'v1.0'.")
@load_project
def finding_show(project: Project, version: ProjectVersion | None) -> None:
    """Show findings."""
    if version is None:
        version = project.config.last_version()
    show_findings(config=project.config, version=version)


@findings.command(name="update")
@handle_exceptions
@load_project
def finding_update(project: Project) -> None:
    """Update available findings from templates.

    Only new findings will be added to the findings.yaml file. Existing findings will not be modified.
    \f

    Args:
        project: Project's representation.
    """
    update_findings(project=project)


# -----------
# sereto open
# -----------


@cli.group(cls=AliasedGroup)
def open() -> None:
    """Open report, Statement of Work (SoW), or the report's folder."""


@open.command(name="folder")
@handle_exceptions
@load_project
def open_folder(project: Project) -> None:
    """Open the folder containing the current report.\f

    Args:
        project: project: Project's representation.
    """
    click.launch(str(project.path))


@open.command(name="report")
@handle_exceptions
@click.option("-v", "--version", help="Use specific version, e.g. 'v1.0'.")
@load_project
def open_report(project: Project, version: ProjectVersion | None) -> None:
    """Open the report document in the default PDF viewer.\f

    Args:
        project: project: Project's representation.
        version: The version of the report that is opened. If None, the last version is used.
    """
    if version is None:
        version = project.config.last_version()

    report_path = project.path / f"report{version.path_suffix}.pdf"

    if not report_path.is_file():
        raise SeretoPathError(f"File not found '{report_path}'")

    click.launch(str(report_path))


@open.command(name="sow")
@handle_exceptions
@click.option("-v", "--version", help="Use specific version, e.g. 'v1.0'.")
@load_project
def open_sow(project: Project, version: ProjectVersion | None) -> None:
    """Open the Statement of Work (SoW) document in the default PDF viewer.\f

    Args:
        project: project: Project's representation.
        version: The version of the SoW that is opened. If None, the last version is used.
    """
    if version is None:
        version = project.config.last_version()

    sow_path = project.path / f"sow{version.path_suffix}.pdf"

    if not sow_path.is_file():
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


@pdf.command(name="report")
@handle_exceptions
@click.option("-c", "--convert-recipe", help="Convert finding recipe")
@click.option("-r", "--report-recipe", help="Build TeX report recipe")
@click.option("-t", "--target-recipe", help="Build TeX target recipe")
@click.option("-f", "--finding-recipe", help="Build TeX finding recipe")
@click.option("-v", "--version", help="Use config at specific version, e.g. 'v1.0'.")
@load_project
def pdf_report(
    project: Project,
    report_recipe: str | None,
    target_recipe: str | None,
    finding_recipe: str | None,
    convert_recipe: str | None,
    version: ProjectVersion | None,
) -> None:
    """Generate a PDF report by following build recipes.\f

    Args:
        project: Project's representation.
        report_recipe: The recipe used for generating the report. If None, the default recipe is used.
        target_recipe: The recipe used for generating targets. If None, the default recipe is used.
        convert_recipe: The convert recipe used for file format transformations. If None, the default recipe is used.
        version: The version of the report that is generated. If None, the last version is used.
    """
    if version is None:
        version = project.config.last_version()

    Console().log(f"Rendering report version: '{version}'")
    report_create_missing(project=project, version=version)
    render_report_j2(project=project, version=version, convert_recipe=convert_recipe)
    report_pdf(
        project=project,
        version=version,
        report_recipe=report_recipe,
        target_recipe=target_recipe,
        finding_recipe=finding_recipe,
    )
    # report_cleanup(project=project, version=version)


@pdf.command(name="sow")
@handle_exceptions
@click.option("-r", "--sow-recipe", help="Build TeX recipe")
@click.option("-v", "--version", help="Use config at specific version, e.g. 'v1.0'.")
@load_project
def pdf_sow(
    project: Project,
    sow_recipe: str | None,
    version: ProjectVersion | None,
) -> None:
    """Generate a PDF Statement of Work (SoW) for a given report.\f

    Args:
        project: Project's representation.
        sow_recipe: The recipe used for generating the SoW. If None, the default recipe is used.
        version: The version of the report for which the SoW is generated. If None, the last version is used.
    """
    if version is None:
        version = project.config.last_version()

    Console().log(f"Rendering SoW version: '{version}'")
    report_create_missing(project=project, version=version)
    render_sow_j2(project=project, version=version)
    render_sow_pdf(project=project, version=version, recipe=sow_recipe, keep_original=True)


# -------------
# sereto retest
# -------------


@cli.command(name="retest")
@handle_exceptions
@load_project
def retest(project: Project) -> None:
    add_retest(project=project)


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
    click.echo(keyring.get_password("sereto", "encrypt_attached_archive"))


@password.command(name="set")
@handle_exceptions
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def settings_password_set(password: str) -> None:
    """Set the password for the encryption of attached archives.

    This will store the password in the system's keyring.
    """
    keyring.set_password("sereto", "encrypt_attached_archive", password)


@settings.command(name="show")
@handle_exceptions
@load_settings
def settings_show(settings: Settings) -> None:
    """Display the current settings.

    This function prints the current settings of the tool, including both the set values and the default values for any
    unset settings.
    \f

    Args:
        settings: The settings object containing the tool's global configuration.
    """
    Console().print_json(settings.model_dump_json())


# ----------------
# sereto templates
# ----------------


@cli.group(cls=AliasedGroup)
def templates() -> None:
    """Operations with templates.

    This group of commands allows you to copy report's skeleton from templates.
    """


@templates.group(cls=AliasedGroup)
def skel() -> None:
    """Report template skeleton files."""


@skel.command(name="copy")
@handle_exceptions
@load_project
def templates_skel_copy(project: Project) -> None:
    """Update the report's templates from the skeleton directory.

    This function copies all files from the templates skeleton directory to the report's directory, overwriting any
    existing files.
    \f

    Args:
        project: Project's representation.
    """
    copy_skel(templates=project.settings.templates_path, dst=project.path, overwrite=True)


@templates.group(cls=AliasedGroup)
def target_skel() -> None:
    """Target template skeleton files."""


@target_skel.command(name="copy")
@handle_exceptions
@click.option("--target", "-t", type=str, help="Specify target (required for more than one).")
@load_project
def templates_target_skel_copy(project: Project, target: str | None) -> None:
    """Update the target's templates from the skeleton directory.

    This function copies all files from the templates skeleton directory to the target's directory, overwriting any
    existing files.
    \f

    Args:
        project: Project's representation.
        target: The target for which the templates are being copied.
    """
    selected_target = project.select_target(selector=target)

    if selected_target.path is None:
        raise SeretoRuntimeError("target path is not set")

    copy_skel(
        templates=project.settings.templates_path / "categories" / selected_target.category,
        dst=selected_target.path,
        overwrite=True,
    )
