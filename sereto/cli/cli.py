import importlib.metadata

import click

from sereto.cleanup import render_sow_cleanup
from sereto.cli.commands import sereto_ls, sereto_repl
from sereto.cli.console import Console
from sereto.cli.utils import AliasedGroup, handle_exceptions
from sereto.config import (
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
from sereto.enums import FileFormat, OutputFormat
from sereto.exceptions import SeretoPathError, SeretoRuntimeError
from sereto.finding import add_finding, show_findings, update_findings
from sereto.models.report import Report
from sereto.models.settings import Settings
from sereto.models.version import ReportVersion
from sereto.pdf import render_sow_pdf
from sereto.report import (
    copy_skel,
    load_report,
    new_report,
    render_report_j2,
    render_sow_j2,
    report_cleanup,
    report_create_missing,
    report_pdf,
)
from sereto.retest import add_retest
from sereto.settings import load_settings, load_settings_function
from sereto.types import TypeReportId


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
def new(settings: Settings, report_id: TypeReportId) -> None:
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
    new_report(settings=settings, report_id=report_id)


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
    sereto_repl(cli)


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
@load_settings
@load_report
def config_show(
    report: Report,
    settings: Settings,
    version: ReportVersion | None,
    all: bool,
    output_format: OutputFormat,
) -> None:
    """Show the reports's configuration.\f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
        version: The specific version of the configuration to show.
        all: Flag to show all versions of the configuration.
        output_format: The output format for displaying the configuration.
    """
    show_config(report=report, output_format=output_format, all=all, version=version)


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
@load_settings
@load_report
def config_dates_add(report: Report, settings: Settings) -> None:
    """Add date to the report's configuration.\f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
    """
    add_dates_config(report=report, settings=settings)


@config_dates.command(name="delete")
@handle_exceptions
@click.option("-i", "--index", required=True, type=int, help="Date index to be deleted.")
@load_settings
@load_report
def config_dates_delete(report: Report, settings: Settings, index: int) -> None:
    """Delete date from the report's configuration.\f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
        index: The index of the date to be deleted. You can obtain the index by running `sereto config dates show`.
    """
    delete_dates_config(report=report, settings=settings, index=index)


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
@load_settings
@load_report
def config_dates_show(
    report: Report,
    settings: Settings,
    version: ReportVersion | None,
    all: bool,
    output_format: OutputFormat,
) -> None:
    """Show dates from the report's configuration.\f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
        version: The specific version of the configuration to show dates from.
        all: Flag to show dates from all versions of the configuration.
        output_format: The output format for displaying the dates.
    """
    show_dates_config(report=report, output_format=output_format, all=all, version=version)


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
@load_settings
@load_report
def config_people_add(report: Report, settings: Settings) -> None:
    """Add person to the report's configuration.\f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
    """
    add_people_config(report=report, settings=settings)


@config_people.command(name="delete")
@handle_exceptions
@click.option("-i", "--index", required=True, type=int, help="Person index to be deleted.")
@load_settings
@load_report
def config_people_delete(report: Report, settings: Settings, index: int) -> None:
    """Delete person from the report's configuration.\f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
        index: The index of the person to be deleted. You can obtain the index by running `sereto config people show`.
    """
    delete_people_config(report=report, settings=settings, index=index)


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
@load_settings
@load_report
def config_people_show(
    report: Report,
    settings: Settings,
    version: ReportVersion | None,
    all: bool,
    output_format: OutputFormat,
) -> None:
    """Show people from the report's configuration.\f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
        version: The specific version of the configuration to show people from.
        all: Flag to show people from all versions of the configuration.
        output_format: The output format for displaying the people.
    """
    show_people_config(report=report, output_format=output_format, all=all, version=version)


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
@load_settings
@load_report
def config_targets_add(report: Report, settings: Settings) -> None:
    """Add targets to the report's configuration.\f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
    """
    add_targets_config(report=report, settings=settings)


@config_targets.command(name="delete")
@handle_exceptions
@click.option("-i", "--index", required=True, type=int, help="Target index to be deleted.")
@load_settings
@load_report
def config_targets_delete(report: Report, settings: Settings, index: int) -> None:
    """Delete target from the report's configuration.\f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
        index: The index of the target to be deleted. You can obtain the index by running `sereto config targets show`.
    """
    delete_targets_config(report=report, settings=settings, index=index)


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
@load_settings
@load_report
def config_targets_show(
    report: Report,
    settings: Settings,
    version: ReportVersion | None,
    all: bool,
    output_format: OutputFormat,
) -> None:
    """Show targets from the report's configuration.\f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
        version: The specific version of the configuration to show targets from.
        all: Flag to show targets from all versions of the configuration.
        output_format: The output format for displaying the targets.
    """
    show_targets_config(report=report, output_format=output_format, all=all, version=version)


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
@load_settings
@load_report
def finding_add(report: Report, settings: Settings, target: str | None, format: str, name: str) -> None:
    """Add finding from template.\f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
        target: The target for which the finding is being added.
        format: The file format of the template.
        name: The name of the finding.
    """
    add_finding(
        report=report,
        settings=settings,
        target_selector=target,
        format=format,
        name=name,
    )


@findings.command(name="show")
@handle_exceptions
# @click.option("--target", "-t", type=str, help="Specify target (required for more than one).")
@click.option("-v", "--version", help="Use specific version, e.g. 'v1.0'.")
@load_settings
@load_report
def finding_show(report: Report, settings: Settings, version: ReportVersion | None) -> None:
    """Show findings."""
    if version is None:
        version = report.config.last_version()
    show_findings(config=report.config, version=version)


@findings.command(name="update")
@handle_exceptions
@load_settings
@load_report
def finding_update(report: Report, settings: Settings) -> None:
    """
    Update available findings from templates.

    Only new findings will be added to the findings.yaml file. Existing findings will not be modified.
    \f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
    """
    update_findings(report=report, settings=settings)


# -----------
# sereto open
# -----------


@cli.group(cls=AliasedGroup)
def open() -> None:
    """Open report, Statement of Work (SoW), or the report's folder."""


@open.command(name="folder")
@handle_exceptions
@load_settings
def open_folder(settings: Settings) -> None:
    """
    Open the folder containing the current report.\f

    Args:
        settings: The settings object containing the tool's global configuration.
    """
    click.launch(str(Report.get_path(settings.reports_path)))


@open.command(name="report")
@handle_exceptions
@click.option("-v", "--version", help="Use specific version, e.g. 'v1.0'.")
@load_settings
@load_report
def open_report(report: Report, settings: Settings, version: ReportVersion | None) -> None:
    """
    Open the report document in the default PDF viewer.\f

    Args:
        settings: The settings object containing the tool's global configuration.
    """
    if version is None:
        version = report.config.last_version()

    report_path = Report.get_path(dir_subtree=settings.reports_path) / f"report{version.path_suffix}.pdf"

    if not report_path.is_file():
        raise SeretoPathError(f"File not found '{report_path}'")

    click.launch(str(report_path))


@open.command(name="sow")
@handle_exceptions
@click.option("-v", "--version", help="Use specific version, e.g. 'v1.0'.")
@load_settings
@load_report
def open_sow(report: Report, settings: Settings, version: ReportVersion | None) -> None:
    """Open the Statement of Work (SoW) document in the default PDF viewer.\f

    Args:
        settings: The settings object containing the tool's global configuration.
    """
    if version is None:
        version = report.config.last_version()

    sow_path = Report.get_path(dir_subtree=settings.reports_path) / f"sow{version.path_suffix}.pdf"

    if not sow_path.is_file():
        raise SeretoPathError(f"File not found '{sow_path}'")

    click.launch(str(sow_path))


# ----------
# sereto pdf
# ----------


@cli.group(cls=AliasedGroup)
def pdf() -> None:
    """
    Render PDF documents.

    This group of commands allows you to render a PDF report or Statement of Work.
    """


@pdf.command(name="report")
@handle_exceptions
@click.option("-c", "--convert-recipe", help="Convert finding recipe")
@click.option("-r", "--report-recipe", help="Build TeX report recipe")
@click.option("-t", "--target-recipe", help="Build TeX target recipe")
@click.option("-f", "--finding-recipe", help="Build TeX finding recipe")
@click.option("-v", "--version", help="Use config at specific version, e.g. 'v1.0'.")
@load_settings
@load_report
def pdf_report(
    report: Report,
    settings: Settings,
    report_recipe: str | None,
    target_recipe: str | None,
    finding_recipe: str | None,
    convert_recipe: str | None,
    version: ReportVersion | None,
) -> None:
    """
    Generate a PDF report by following build recipes.\f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
        report_recipe: The recipe used for generating the report. If None, the default recipe is used.
        target_recipe: The recipe used for generating targets. If None, the default recipe is used.
        convert_recipe: The convert recipe used for file format transformations. If None, the default recipe is used.
        version: The version of the report that is generated. If None, the last version is used.
    """
    if version is None:
        version = report.config.last_version()

    Console().log(f"rendering report version: '{version}'")
    report_create_missing(report=report, settings=settings, version=version)
    render_report_j2(report=report, settings=settings, version=version, convert_recipe=convert_recipe)
    report_pdf(
        report=report,
        settings=settings,
        version=version,
        report_recipe=report_recipe,
        target_recipe=target_recipe,
        finding_recipe=finding_recipe,
    )
    report_cleanup(report=report, settings=settings, version=version)


@pdf.command(name="sow")
@handle_exceptions
@click.option("-r", "--sow-recipe", help="Build TeX recipe")
@click.option("-v", "--version", help="Use config at specific version, e.g. 'v1.0'.")
@load_settings
@load_report
def pdf_sow(
    report: Report,
    settings: Settings,
    sow_recipe: str | None,
    version: ReportVersion | None,
) -> None:
    """
    Generate a PDF Statement of Work (SoW) for a given report.\f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
        sow_recipe: The recipe used for generating the SoW. If None, the default recipe is used.
        version: The version of the report for which the SoW is generated. If None, the last version is used.
    """
    if version is None:
        version = report.config.last_version()

    Console().log(f"rendering SoW version: '{version}'")
    report_create_missing(report=report, settings=settings, version=version)
    render_sow_j2(report=report, settings=settings, version=version)
    render_sow_pdf(report=report, settings=settings, version=version, recipe=sow_recipe)
    render_sow_cleanup(report=report, settings=settings, version=version)


# -------------
# sereto retest
# -------------


@cli.command(name="retest")
@handle_exceptions
@load_settings
@load_report
def retest(report: Report, settings: Settings) -> None:
    add_retest(report=report, settings=settings)


# ---------------
# sereto settings
# ---------------


@cli.group(cls=AliasedGroup)
def settings() -> None:
    """
    Manage global settings.

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


@settings.command(name="show")
@handle_exceptions
@load_settings
def settings_show(settings: Settings) -> None:
    """
    Display the current settings.

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
    """
    Operations with templates.

    This group of commands allows you to copy report's skeleton from templates.
    """


@templates.group(cls=AliasedGroup)
def skel() -> None:
    """Report template skeleton files."""


@skel.command(name="copy")
@handle_exceptions
@load_settings
@load_report
def templates_skel_copy(report: Report, settings: Settings) -> None:
    """Update the report's templates from the skeleton directory.

    This function copies all files from the templates skeleton directory to the report's directory, overwriting any
    existing files.
    \f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
    """
    copy_skel(
        templates=settings.templates_path,
        dst=Report.get_path(dir_subtree=settings.reports_path),
        overwrite=True,
    )


@templates.group(cls=AliasedGroup)
def target_skel() -> None:
    """Target template skeleton files."""


@target_skel.command(name="copy")
@handle_exceptions
@click.option("--target", "-t", type=str, help="Specify target (required for more than one).")
@load_settings
@load_report
def templates_target_skel_copy(report: Report, settings: Settings, target: str | None) -> None:
    """Update the target's templates from the skeleton directory.

    This function copies all files from the templates skeleton directory to the target's directory, overwriting any
    existing files.
    \f

    Args:
        report: The report object.
        settings: The settings object containing the tool's global configuration.
        target: The target for which the templates are being copied.
    """
    selected_target = report.select_target(settings=settings, selector=target)

    if selected_target.path is None:
        raise SeretoRuntimeError("target path is not set")

    copy_skel(
        templates=settings.templates_path / "categories" / selected_target.category,
        dst=selected_target.path,
        overwrite=True,
    )
