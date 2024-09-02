import importlib.metadata
import shutil

import click
from pydantic import RootModel, validate_call
from rich import box
from rich.prompt import Confirm
from rich.table import Table

from sereto.cli.console import Console
from sereto.cli.date import prompt_user_for_date
from sereto.cli.person import prompt_user_for_person
from sereto.cli.target import prompt_user_for_target
from sereto.cli.utils import load_enum
from sereto.enums import OutputFormat
from sereto.exceptions import SeretoValueError
from sereto.models.config import Config
from sereto.models.date import Date, DateRange, DateType, SeretoDate
from sereto.models.person import Person, PersonType
from sereto.models.report import Report
from sereto.models.settings import Settings
from sereto.models.target import Target
from sereto.models.version import ReportVersion, SeretoVersion
from sereto.report import report_create_missing


@validate_call
def write_config(config: Config, settings: Settings) -> None:
    """Write report configuration to a file.

    Args:
        config: Report's configuration.
        settings: Global settings.

    Raises:
        SeretoPathError: If the report directory cannot be found.
    """
    config_path = Report.get_config_path(dir_subtree=settings.reports_path)

    with config_path.open("w", encoding="utf-8") as f:
        f.write(config.model_dump_json(indent=2))
        f.write("\n")


# -------------
# sereto config
# -------------


@validate_call
def edit_config(settings: Settings) -> None:
    """Edit the configuration file in default CLI editor.

    Args:
        settings: Global settings.
    """
    sereto_ver = importlib.metadata.version("sereto")

    if not (path := Report.get_config_path(dir_subtree=settings.reports_path)).is_file():
        write_config(
            config=Config(
                sereto_version=SeretoVersion.from_str(sereto_ver),
                id="",
                name="",
                report_version=ReportVersion.from_str("v1.0"),
            ),
            settings=settings,
        )

    click.edit(filename=str(path))
    # is_config_valid(reports_path=settings.reports_path, print=True)


@validate_call
def show_config(
    report: Report,
    output_format: OutputFormat,
    all: bool = False,
    version: ReportVersion | None = None,
) -> None:
    """Display the configuration for a report.

    Args:
        report: Report's representation.
        output_format: Format of the output.
        all: Whether to show values from all versions or just the last one.
        version: Show config at specific version, e.g. 'v1.0'.
    """
    if version is None:
        version = report.config.last_version()

    cfg = report.config if all else report.config.at_version(version)

    match output_format:
        case OutputFormat.table:
            Console().print(f"\n\n[blue]{cfg.id} - {cfg.name}\n", justify="center")
            show_targets_config(
                report=report,
                output_format=OutputFormat.table,
                all=all,
                version=version,
            )
            show_dates_config(
                report=report,
                output_format=OutputFormat.table,
                all=all,
                version=version,
            )
            show_people_config(
                report=report,
                output_format=OutputFormat.table,
                all=all,
                version=version,
            )
        case OutputFormat.json:
            Console().print_json(cfg.model_dump_json())


# -------------------
# sereto config dates
# -------------------


@validate_call
def add_dates_config(report: Report, settings: Settings) -> None:
    """Add date to the configuration for a report.

    Args:
        report: Report's representation.
        settings: Global settings.
    """
    cfg = report.config
    dates: list[Date] = cfg.dates if len(cfg.updates) == 0 else cfg.updates[-1].dates

    date_type: DateType = load_enum(enum=DateType, prompt="Type")
    new_date = prompt_user_for_date(date_type=date_type)
    dates.append(Date(type=date_type, date=new_date))

    write_config(config=report.config, settings=settings)


@validate_call
def delete_dates_config(report: Report, settings: Settings, index: int) -> None:
    """Delete date from the configuration by its index.

    Args:
        report: Report's representation.
        settings: Global settings.
        index: Index to item which should be deleted. First item is 1.
    """
    cfg = report.config
    dates: list[Date] = cfg.dates if len(cfg.updates) == 0 else cfg.updates[-1].dates
    index -= 1
    if not 0 <= index <= len(dates) - 1:
        raise SeretoValueError("invalid index, not in allowed range")
    del dates[index]
    write_config(config=cfg, settings=settings)


DatesList = RootModel[list[Date]]


@validate_call
def show_dates_config(
    report: Report,
    output_format: OutputFormat,
    all: bool,
    version: ReportVersion | None,
) -> None:
    """Display the configured dates.

    By default, if neither of `version` and `all` arguments are used, dates from the latest version are displayed.

    Args:
        report: Report's representation.
        output_format: Select format of the output.
        all: Show dates from all versions.
        version: Show dates from specific version.
    """
    if version is None:
        version = report.config.last_version()

    match output_format:
        case OutputFormat.table:
            for report_version in report.config.versions() if all else [version]:
                Console().line()
                table = Table(
                    "%",
                    "Type",
                    "From",
                    "To",
                    title=f"Dates {report_version}",
                    box=box.MINIMAL,
                )

                for ix, date in enumerate(report.config.at_version(version=report_version).dates, start=1):
                    match date.date:
                        case SeretoDate():
                            table.add_row(str(ix), date.type.value, str(date.date), "[yellow]n/a")
                        case DateRange():
                            table.add_row(
                                str(ix),
                                date.type.value,
                                str(date.date.start),
                                str(date.date.end),
                            )
                Console().print(table, justify="center")
        case OutputFormat.json:
            if all:
                all_dates = RootModel(dict[str, DatesList]).model_validate(
                    {str(ver): report.config.at_version(version=ver).dates for ver in report.config.versions()}
                )
                Console().print_json(all_dates.model_dump_json())
            else:
                Console().print_json(
                    DatesList.model_validate(report.config.at_version(version).dates).model_dump_json()
                )


# --------------------
# sereto config people
# --------------------


@validate_call
def add_people_config(report: Report, settings: Settings) -> None:
    """Add person to the configuration for a report.

    Args:
        report: Report's representation.
        settings: Global settings.
    """
    cfg = report.config
    people: list[Person] = cfg.people if len(cfg.updates) == 0 else cfg.updates[-1].people

    person_type: PersonType = load_enum(enum=PersonType, prompt="Type")
    new_person = prompt_user_for_person(person_type=person_type)
    people.append(new_person)

    write_config(config=report.config, settings=settings)


@validate_call
def delete_people_config(report: Report, settings: Settings, index: int) -> None:
    """Delete person from the configuration by its index.

    Args:
        report: Report's representation.
        settings: Global settings.
        index: Index to item which should be deleted. First item is 1.
    """
    cfg = report.config
    people: list[Person] = cfg.people if len(cfg.updates) == 0 else cfg.updates[-1].people
    index -= 1
    if not 0 <= index <= len(people) - 1:
        raise SeretoValueError("invalid index, not in allowed range")
    del people[index]
    write_config(config=cfg, settings=settings)


PersonList = RootModel[list[Person]]


@validate_call
def show_people_config(
    report: Report,
    output_format: OutputFormat,
    all: bool,
    version: ReportVersion | None,
) -> None:
    """Display the configured people.

    By default, if neither of `version` and `all` arguments are used, people from the latest version are displayed.

    Args:
        report: Report's representation.
        output_format: Select format of the output.
        all: Show people from all versions.
        version: Show people from specific version.
    """
    if version is None:
        version = report.config.last_version()

    match output_format:
        case OutputFormat.table:
            for report_version in report.config.versions() if all else [version]:
                Console().line()
                table = Table(
                    "%",
                    "Type",
                    "Name",
                    "BU",
                    "Email",
                    "Role",
                    title=f"People {report_version}",
                    box=box.MINIMAL,
                )
                for ix, person in enumerate(report.config.at_version(version=report_version).people, start=1):
                    table.add_row(
                        str(ix),
                        person.type,
                        person.name if person.name is not None else "[yellow]n/a",
                        (person.business_unit if person.business_unit is not None else "[yellow]n/a"),
                        person.email if person.email is not None else "[yellow]n/a",
                        person.role if person.role is not None else "[yellow]n/a",
                    )
                Console().print(table, justify="center")
        case OutputFormat.json:
            if all:
                all_people = RootModel(dict[str, PersonList]).model_validate(
                    {str(ver): report.config.at_version(version=ver).people for ver in report.config.versions()}
                )
                Console().print_json(all_people.model_dump_json())
            else:
                Console().print_json(
                    PersonList.model_validate(report.config.at_version(version).people).model_dump_json()
                )


# # ---------------------
# # sereto config targets
# # ---------------------


@validate_call
def add_targets_config(report: Report, settings: Settings) -> None:
    """Add target to the configuration for a report.

    Args:
        report: Report's representation.
        settings: Global settings.
    """
    cfg = report.config
    targets: list[Target] = cfg.targets if len(cfg.updates) == 0 else cfg.updates[-1].targets
    targets.append(prompt_user_for_target(settings=settings))
    write_config(config=cfg, settings=settings)
    report.load_runtime_vars(settings=settings)
    report_create_missing(report=report, settings=settings, version=cfg.last_version())


@validate_call
def delete_targets_config(report: Report, settings: Settings, index: int) -> None:
    """Delete target from the configuration by its index.

    Args:
        report: Report's representation.
        settings: Global settings.
        index: Index to item which should be deleted. First item is 1.
    """
    cfg = report.config
    targets: list[Target] = cfg.targets if len(cfg.updates) == 0 else cfg.updates[-1].targets
    index -= 1
    if not 0 <= index <= len(targets) - 1:
        raise SeretoValueError("invalid index, not in allowed range")
    target_path = targets[index].path
    del targets[index]
    write_config(config=cfg, settings=settings)

    if (
        target_path is not None
        and target_path.is_dir()
        and Confirm.ask(
            f'[yellow]Delete "{target_path}" from the filesystem?',
            console=Console(),
            default=False,
        )
    ):
        shutil.rmtree(target_path)


TargetList = RootModel[list[Target]]


@validate_call
def show_targets_config(
    report: Report,
    output_format: OutputFormat,
    all: bool,
    version: ReportVersion | None,
) -> None:
    """Display the configured targets.

    By default, if neither of `version` and `all` arguments are used, targets from the latest version are displayed.

    Args:
        report: Report's representation.
        output_format: Select format of the output.
        all: Show targets from all versions.
        version: Show targets from the specified report's version.
    """
    if version is None:
        version = report.config.last_version()

    match output_format:
        case OutputFormat.table:
            for report_version in report.config.versions() if all else [version]:
                Console().line()
                table = Table(
                    "%",
                    "Category",
                    "Name",
                    title=f"Targets {report_version}",
                    box=box.MINIMAL,
                )
                for ix, target in enumerate(report.config.at_version(version=report_version).targets, start=1):
                    table.add_row(str(ix), target.category, target.name)
                Console().print(table, justify="center")
        case OutputFormat.json:
            if all:
                all_targets = RootModel(dict[str, TargetList]).model_validate(
                    {str(ver): report.config.at_version(version=ver).targets for ver in report.config.versions()}
                )
                Console().print_json(all_targets.model_dump_json())
            else:
                Console().print_json(
                    TargetList.model_validate(report.config.at_version(version).targets).model_dump_json()
                )
