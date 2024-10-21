import importlib.metadata
import shutil

import click
from pydantic import TypeAdapter, validate_call
from rich import box
from rich.prompt import Confirm
from rich.table import Table

from sereto.cli.date import prompt_user_for_date
from sereto.cli.person import prompt_user_for_person
from sereto.cli.target import prompt_user_for_target
from sereto.cli.utils import Console, load_enum
from sereto.enums import OutputFormat
from sereto.exceptions import SeretoValueError
from sereto.models.config import Config
from sereto.models.date import Date, DateRange, DateType, SeretoDate
from sereto.models.person import Person, PersonType
from sereto.models.project import Project, get_config_path
from sereto.models.settings import Settings
from sereto.models.target import Target
from sereto.models.version import ReportVersion, SeretoVersion
from sereto.report import report_create_missing

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
    config = get_config_path(dir_subtree=settings.reports_path)

    # If the config file does not exist, create it with default values
    if not config.is_file():
        Config(
            sereto_version=SeretoVersion.from_str(sereto_ver),
            id="",
            name="",
            report_version=ReportVersion.from_str("v1.0"),
        ).dump_json(file=config)

    # Open the config file in the default editor
    click.edit(filename=str(config))


@validate_call
def show_config(
    project: Project,
    output_format: OutputFormat,
    all: bool = False,
    version: ReportVersion | None = None,
) -> None:
    """Display the configuration for a report.

    Args:
        project: Report's project representation.
        output_format: Format of the output.
        all: Whether to show values from all versions or just the last one.
        version: Show config at specific version, e.g. 'v1.0'.
    """
    if version is None:
        version = project.config.last_version()

    cfg = project.config if all else project.config.at_version(version)

    match output_format:
        case OutputFormat.table:
            Console().print(f"\n\n[blue]{cfg.id} - {cfg.name}\n", justify="center")
            show_targets_config(
                project=project,
                output_format=OutputFormat.table,
                all=all,
                version=version,
            )
            show_dates_config(
                project=project,
                output_format=OutputFormat.table,
                all=all,
                version=version,
            )
            show_people_config(
                project=project,
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
def add_dates_config(project: Project) -> None:
    """Add date to the configuration for a report.

    Args:
        project: Report's project representation.
    """
    cfg = project.config
    dates: list[Date] = cfg.dates if len(cfg.updates) == 0 else cfg.updates[-1].dates

    # Add a new date
    date_type: DateType = load_enum(enum=DateType, prompt="Type")
    new_date = prompt_user_for_date(date_type=date_type)
    dates.append(Date(type=date_type, date=new_date))

    # Write the configuration
    cfg.dump_json(file=project.get_config_path())


@validate_call
def delete_dates_config(project: Project, index: int) -> None:
    """Delete date from the configuration by its index.

    Args:
        project: Report's project representation.
        index: Index to item which should be deleted. First item is 1.
    """
    cfg = project.config
    dates: list[Date] = cfg.dates if len(cfg.updates) == 0 else cfg.updates[-1].dates
    index -= 1
    if not 0 <= index <= len(dates) - 1:
        raise SeretoValueError("invalid index, not in allowed range")
    del dates[index]

    # Write the configuration
    cfg.dump_json(file=project.get_config_path())


@validate_call
def show_dates_config(
    project: Project,
    output_format: OutputFormat,
    all: bool,
    version: ReportVersion | None,
) -> None:
    """Display the configured dates.

    By default, if neither of `version` and `all` arguments are used, dates from the latest version are displayed.

    Args:
        project: Report's project representation.
        output_format: Select format of the output.
        all: Show dates from all versions.
        version: Show dates from specific version.
    """
    if version is None:
        version = project.config.last_version()

    match output_format:
        case OutputFormat.table:
            for report_version in project.config.versions() if all else [version]:
                Console().line()
                table = Table(
                    "%",
                    "Type",
                    "From",
                    "To",
                    title=f"Dates {report_version}",
                    box=box.MINIMAL,
                )

                for ix, date in enumerate(project.config.at_version(version=report_version).dates, start=1):
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
            DateList: TypeAdapter[list[Date]] = TypeAdapter(list[Date])
            DateAll: TypeAdapter[dict[str, list[Date]]] = TypeAdapter(dict[str, list[Date]])

            if all:
                all_dates = DateAll.validate_python(
                    {str(ver): project.config.at_version(version=ver).dates for ver in project.config.versions()}
                )
                Console().print_json(DateAll.dump_json(all_dates).decode("utf-8"))
            else:
                dates = DateList.validate_python(project.config.at_version(version).dates)
                Console().print_json(DateList.dump_json(dates).decode("utf-8"))


# --------------------
# sereto config people
# --------------------


@validate_call
def add_people_config(project: Project) -> None:
    """Add person to the configuration for a report.

    Args:
        project: Report's project representation.
    """
    cfg = project.config
    people: list[Person] = cfg.people if len(cfg.updates) == 0 else cfg.updates[-1].people

    # Add a new person
    person_type: PersonType = load_enum(enum=PersonType, prompt="Type")
    new_person = prompt_user_for_person(person_type=person_type)
    people.append(new_person)

    # Write the configuration
    cfg.dump_json(file=project.get_config_path())


@validate_call
def delete_people_config(project: Project, index: int) -> None:
    """Delete person from the configuration by its index.

    Args:
        project: Report's project representation.
        index: Index to item which should be deleted. First item is 1.
    """
    cfg = project.config
    people: list[Person] = cfg.people if len(cfg.updates) == 0 else cfg.updates[-1].people
    index -= 1
    if not 0 <= index <= len(people) - 1:
        raise SeretoValueError("invalid index, not in allowed range")
    del people[index]

    # Write the configuration
    cfg.dump_json(file=project.get_config_path())


@validate_call
def show_people_config(
    project: Project,
    output_format: OutputFormat,
    all: bool,
    version: ReportVersion | None,
) -> None:
    """Display the configured people.

    By default, if neither of `version` and `all` arguments are used, people from the latest version are displayed.

    Args:
        project: Report's project representation.
        output_format: Select format of the output.
        all: Show people from all versions.
        version: Show people from specific version.
    """
    if version is None:
        version = project.config.last_version()

    match output_format:
        case OutputFormat.table:
            for report_version in project.config.versions() if all else [version]:
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
                for ix, person in enumerate(project.config.at_version(version=report_version).people, start=1):
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
            PersonList: TypeAdapter[list[Person]] = TypeAdapter(list[Person])
            PersonAll: TypeAdapter[dict[str, list[Person]]] = TypeAdapter(dict[str, list[Person]])

            if all:
                all_people = PersonAll.validate_python(
                    {str(ver): project.config.at_version(version=ver).people for ver in project.config.versions()}
                )
                Console().print_json(PersonAll.dump_json(all_people).decode("utf-8"))
            else:
                people = PersonList.validate_python(project.config.at_version(version).people)
                Console().print_json(PersonList.dump_json(people).decode("utf-8"))


# ---------------------
# sereto config targets
# ---------------------


@validate_call
def add_targets_config(project: Project) -> None:
    """Add target to the configuration for a report.

    Args:
        project: Report's project representation.
    """
    cfg = project.config
    targets: list[Target] = cfg.targets if len(cfg.updates) == 0 else cfg.updates[-1].targets

    # Add a new target
    targets.append(prompt_user_for_target(settings=project.settings))

    # Write the configuration
    cfg.dump_json(file=project.get_config_path())

    # Post-process the new target
    project.config.update_paths(project.path)
    report_create_missing(project=project, version=cfg.last_version())


@validate_call
def delete_targets_config(project: Project, index: int) -> None:
    """Delete target from the configuration by its index.

    Args:
        project: Report's project representation.
        index: Index to item which should be deleted. First item is 1.
    """
    cfg = project.config
    targets: list[Target] = cfg.targets if len(cfg.updates) == 0 else cfg.updates[-1].targets
    index -= 1
    if not 0 <= index <= len(targets) - 1:
        raise SeretoValueError("invalid index, not in allowed range")
    del targets[index]

    # Write the configuration
    cfg.dump_json(file=project.get_config_path())

    # Delete the target from the filesystem
    target_path = targets[index].path
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


@validate_call
def show_targets_config(
    project: Project,
    output_format: OutputFormat,
    all: bool,
    version: ReportVersion | None,
) -> None:
    """Display the configured targets.

    By default, if neither of `version` and `all` arguments are used, targets from the latest version are displayed.

    Args:
        project: Report's project representation.
        output_format: Select format of the output.
        all: Show targets from all versions.
        version: Show targets from the specified report's version.
    """
    if version is None:
        version = project.config.last_version()

    match output_format:
        case OutputFormat.table:
            for report_version in project.config.versions() if all else [version]:
                Console().line()
                table = Table(
                    "%",
                    "Category",
                    "Name",
                    title=f"Targets {report_version}",
                    box=box.MINIMAL,
                )
                for ix, target in enumerate(project.config.at_version(version=report_version).targets, start=1):
                    table.add_row(str(ix), target.category, target.name)
                Console().print(table, justify="center")
        case OutputFormat.json:
            TargetList: TypeAdapter[list[Target]] = TypeAdapter(list[Target])
            TargetAll: TypeAdapter[dict[str, list[Target]]] = TypeAdapter(dict[str, list[Target]])

            if all:
                all_targets = TargetAll.validate_python(
                    {str(ver): project.config.at_version(version=ver).targets for ver in project.config.versions()}
                )
                Console().print_json(TargetAll.dump_json(all_targets).decode("utf-8"))
            else:
                targets = TargetList.validate_python(project.config.at_version(version).targets)
                Console().print_json(TargetList.dump_json(targets).decode("utf-8"))
