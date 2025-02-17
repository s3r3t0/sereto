import importlib.metadata
import shutil
from collections.abc import Iterable

import click
from prompt_toolkit.shortcuts import yes_no_dialog
from pydantic import DirectoryPath, TypeAdapter, validate_call
from rich import box
from rich.table import Table

from sereto.cli.date import prompt_user_for_date
from sereto.cli.person import prompt_user_for_person
from sereto.cli.target import prompt_user_for_target
from sereto.cli.utils import Console, load_enum
from sereto.config import Config, VersionConfig
from sereto.enums import OutputFormat
from sereto.models.config import VersionConfigModel
from sereto.models.date import Date, DateRange, DateType, SeretoDate
from sereto.models.person import Person, PersonType
from sereto.models.target import TargetModel
from sereto.models.version import ProjectVersion, SeretoVersion
from sereto.project import Project
from sereto.target import Target

# -------------
# sereto config
# -------------


@validate_call
def edit_config(project: Project) -> None:
    """Edit the configuration file in default CLI editor.

    Args:
        project: Project's representation.
    """
    sereto_ver = importlib.metadata.version("sereto")
    config = project.config_path

    # If the config file does not exist, create it with default values
    if not project.config_path.is_file():
        Config(
            sereto_version=SeretoVersion.from_str(sereto_ver),
            version_configs={
                ProjectVersion.from_str("v1.0"): VersionConfig(
                    version=ProjectVersion.from_str("v1.0"),
                    id="",
                    name="",
                    version_description="Initial",
                ),
            },
            path=project.config_path,
        ).save()

    # Open the config file in the default editor
    click.edit(filename=str(config))


@validate_call
def show_config(
    config: Config, output_format: OutputFormat, all: bool = False, version: ProjectVersion | None = None
) -> None:
    """Display the configuration for a project.

    Args:
        config: Configuration of the project.
        output_format: Format of the output.
        all: Whether to show values from all versions or just the last one.
        version: Show config at specific version, e.g. 'v1.0'.
    """
    if version is None:
        version = config.last_version

    version_config = config.at_version(version)

    match output_format:
        case OutputFormat.table:
            Console().print(f"\n\n[blue]{version_config.id} - {version_config.name}\n", justify="center")
            show_targets_config(config=config, output_format=OutputFormat.table, all=all, version=version)
            show_dates_config(config=config, output_format=OutputFormat.table, all=all, version=version)
            show_people_config(config=config, output_format=OutputFormat.table, all=all, version=version)
        case OutputFormat.json:
            if all:
                Console().print_json(config.to_model().model_dump_json())
            else:
                Console().print_json(version_config.to_model().model_dump_json())


# -------------------
# sereto config dates
# -------------------


@validate_call
def add_dates_config(config: Config, version: ProjectVersion | None = None) -> None:
    """Add date to the configuration.

    Args:
        config: Configuration of the project.
        version: The version of the project. If not provided, the last version is used.
    """
    if version is None:
        version = config.last_version

    # Prompt user for the date
    date_type: DateType = load_enum(enum=DateType, message="Type:")
    new_date = prompt_user_for_date(date_type=date_type)

    # Add the date to the configuration
    config.at_version(version).add_date(Date(type=date_type, date=new_date))

    # Write the configuration
    config.save()


@validate_call
def _get_dates_table(version_config: VersionConfigModel, version: ProjectVersion) -> Table:
    """Get table of dates from specified VersionConfig."""
    table = Table(
        "%",
        "Type",
        "From",
        "To",
        title=f"Dates {version}",
        box=box.MINIMAL,
    )

    for ix, date in enumerate(version_config.dates, start=1):
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

    return table


@validate_call
def show_dates_config(
    config: Config,
    output_format: OutputFormat,
    all: bool,
    version: ProjectVersion | None,
) -> None:
    """Display the configured dates.

    By default, if neither of `version` and `all` arguments are used, dates from the latest version are displayed.

    Args:
        config: Configuration of the project.
        output_format: Select format of the output.
        all: Show dates from all versions.
        version: Show dates from specific version.
    """
    if version is None:
        version = config.last_version

    match output_format:
        case OutputFormat.table:
            for ver in config.versions if all else [version]:
                Console().line()
                table = _get_dates_table(version_config=config.at_version(version=ver).to_model(), version=ver)
                Console().print(table, justify="center")
        case OutputFormat.json:
            DateList: TypeAdapter[list[Date]] = TypeAdapter(list[Date])
            DateAll: TypeAdapter[dict[str, list[Date]]] = TypeAdapter(dict[str, list[Date]])

            if all:
                all_dates = DateAll.validate_python(
                    {str(ver): config.at_version(version=ver).dates for ver in config.versions}
                )
                Console().print_json(DateAll.dump_json(all_dates).decode("utf-8"))
            else:
                dates = DateList.validate_python(config.at_version(version).dates)
                Console().print_json(DateList.dump_json(dates).decode("utf-8"))


# --------------------
# sereto config people
# --------------------


@validate_call
def add_people_config(config: Config, version: ProjectVersion | None = None) -> None:
    """Add person to the configuration.

    Args:
        config: Configuration of the project.
        version: The version of the project. If not provided, the last version is used.
    """
    if version is None:
        version = config.last_version

    # Prompt user for the person
    person_type: PersonType = load_enum(enum=PersonType, message="Type:")
    new_person = prompt_user_for_person(person_type=person_type)

    # Add the person to the configuration
    config.at_version(version).add_person(new_person)

    # Write the configuration
    config.save()


@validate_call
def _get_person_table(version_config: VersionConfigModel, version: ProjectVersion) -> Table:
    """Get table of people from specified VersionConfig."""
    table = Table(
        "%",
        "Type",
        "Name",
        "BU",
        "Email",
        "Role",
        title=f"People {version}",
        box=box.MINIMAL,
    )

    for ix, person in enumerate(version_config.people, start=1):
        table.add_row(
            str(ix),
            person.type,
            person.name if person.name is not None else "[yellow]n/a",
            (person.business_unit if person.business_unit is not None else "[yellow]n/a"),
            person.email if person.email is not None else "[yellow]n/a",
            person.role if person.role is not None else "[yellow]n/a",
        )

    return table


@validate_call
def show_people_config(config: Config, output_format: OutputFormat, all: bool, version: ProjectVersion | None) -> None:
    """Display the configured people.

    By default, if neither of `version` and `all` arguments are used, people from the latest version are displayed.

    Args:
        config: Configuration of the project.
        output_format: Select format of the output.
        all: Show people from all versions.
        version: Show people from specific version.
    """
    if version is None:
        version = config.last_version

    match output_format:
        case OutputFormat.table:
            for ver in config.versions if all else [version]:
                Console().line()
                table = _get_person_table(version_config=config.at_version(version=ver).to_model(), version=ver)
                Console().print(table, justify="center")
        case OutputFormat.json:
            PersonList: TypeAdapter[list[Person]] = TypeAdapter(list[Person])
            PersonAll: TypeAdapter[dict[str, list[Person]]] = TypeAdapter(dict[str, list[Person]])

            if all:
                all_people = PersonAll.validate_python(
                    {str(ver): config.at_version(version=ver).people for ver in config.versions}
                )
                Console().print_json(PersonAll.dump_json(all_people).decode("utf-8"))
            else:
                people = PersonList.validate_python(config.at_version(version).people)
                Console().print_json(PersonList.dump_json(people).decode("utf-8"))


# ---------------------
# sereto config targets
# ---------------------


@validate_call
def add_target(
    project_path: DirectoryPath,
    templates: DirectoryPath,
    config: Config,
    categories: Iterable[str],
    version: ProjectVersion | None = None,
) -> None:
    """Add target to the configuration.

    Args:
        project_path: Path to the project directory.
        templates: Path to the templates directory.
        config: Configuration of the project.
        categories: List of all categories.
        version: The version of the project. If not provided, the last version is used.
    """
    if version is None:
        version = config.last_version

    # Prompt user for the target details
    new_target_model = prompt_user_for_target(categories=categories)

    # Create the target instance, including on the filesystem
    new_target = Target.new(data=new_target_model, project_path=project_path, templates=templates, version=version)

    # Add the target to the configuration
    config.at_version(version).add_target(new_target)

    # Write the configuration
    config.save()


@validate_call
def delete_target(
    config: Config, index: int, version: ProjectVersion | None = None, interactive: bool = False
) -> None:
    """Delete target from the configuration by its index.

    Args:
        config: Configuration of the project.
        index: Index to item which should be deleted. First item is 1.
        version: The version of the project. If not provided, the last version is used.
        interactive: Whether to ask for confirmations.
    """
    if version is None:
        version = config.last_version

    # Extract the filesystem path before deleting the values
    version_config = config.at_version(version)
    target_path = version_config.targets[index - 1].path

    # Delete the date from the configuration
    version_config.delete_target(index=index)

    # Write the configuration
    config.save()

    # Delete target from the filesystem
    if (
        target_path.is_dir()
        and interactive
        and yes_no_dialog(title="Confirm", text=f"Delete '{target_path}' from the filesystem?").run()
    ):
        shutil.rmtree(target_path)


@validate_call
def _get_target_table(version_config: VersionConfigModel, version: ProjectVersion) -> Table:
    """Get table of targets from specified VersionConfig."""
    table = Table(
        "%",
        "Category",
        "Name",
        title=f"Targets {version}",
        box=box.MINIMAL,
    )
    for ix, target in enumerate(version_config.targets, start=1):
        table.add_row(str(ix), target.category, target.name)

    return table


@validate_call
def show_targets_config(
    config: Config, output_format: OutputFormat, all: bool, version: ProjectVersion | None
) -> None:
    """Display the configured targets.

    By default, if neither of `version` and `all` arguments are used, targets from the latest version are displayed.

    Args:
        config: Configuration of the project.
        output_format: Select format of the output.
        all: Show targets from all versions.
        version: Show targets from the specified project's version.
    """
    if version is None:
        version = config.last_version

    match output_format:
        case OutputFormat.table:
            for ver in config.versions if all else [version]:
                Console().line()
                table = _get_target_table(version_config=config.at_version(version=ver).to_model(), version=ver)
                Console().print(table, justify="center")
        case OutputFormat.json:
            TargetList: TypeAdapter[list[TargetModel]] = TypeAdapter(list[TargetModel])
            TargetAll: TypeAdapter[dict[str, list[TargetModel]]] = TypeAdapter(dict[str, list[TargetModel]])

            if all:
                all_targets = TargetAll.validate_python(
                    {
                        str(ver): [t.to_model() for t in config.at_version(version=ver).targets]
                        for ver in config.versions
                    }
                )
                Console().print_json(TargetAll.dump_json(all_targets).decode("utf-8"))
            else:
                target_models = [t.to_model() for t in config.at_version(version).targets]
                targets = TargetList.validate_python(target_models)
                Console().print_json(TargetList.dump_json(targets).decode("utf-8"))
