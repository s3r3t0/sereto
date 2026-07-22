import importlib.metadata
import json
import shutil
from collections.abc import Iterable

import click
from prompt_toolkit.shortcuts import yes_no_dialog
from pydantic import DirectoryPath, TypeAdapter, ValidationError, validate_call
from rich import box
from rich.table import Table

from sereto.cli.date import allows_range, prompt_user_for_date
from sereto.cli.person import prompt_user_for_person
from sereto.cli.target import prompt_user_for_target
from sereto.cli.utils import Console, load_enum
from sereto.config import Config, VersionConfig
from sereto.enums import OutputFormat
from sereto.exceptions import SeretoValueError
from sereto.models.config import ConfigModel, VersionConfigModel
from sereto.models.date import Date, DateRange, DateType, SeretoDate
from sereto.models.person import Person, PersonType
from sereto.models.target import AnyTargetModel, TargetDastModel, TargetMobileModel, TargetModel, TargetSastModel
from sereto.models.version import ProjectVersion, SeretoVersion
from sereto.project import Project
from sereto.target import Target

# -------------
# sereto config
# -------------


@validate_call
def edit_config(
    project: Project,
    non_interactive: bool = False,
    extra_json: str | None = None,
) -> None:
    """Edit the configuration file in default CLI editor.

    When `non_interactive` is True, the config is updated from `extra_json` without opening an editor.
    Otherwise, the config file is opened in the default editor.

    Args:
        project: Project's representation.
        non_interactive: If True, run non-interactively.
        extra_json: A JSON string with config fields to update.
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
                    risk_due_dates=project.settings.risk_due_dates,
                ),
            },
            path=project.config_path,
            risk_due_dates=project.settings.risk_due_dates,
        ).save()

    if non_interactive:
        if extra_json is None:
            raise SeretoValueError("'--extra' is required in non-interactive mode.")
        try:
            extra = json.loads(extra_json)
        except json.JSONDecodeError as e:
            raise SeretoValueError(f"Invalid JSON in '--extra': {e}") from e

        if not isinstance(extra, dict):
            raise SeretoValueError("Value of '--extra' must be a JSON object")

        version_config = project.config.at_version(project.config.last_version)
        skip_fields = {"version_configs", "targets", "dates", "people"}

        for key, value in extra.items():
            if key in skip_fields:
                continue
            elif key in VersionConfigModel.model_fields:
                setattr(version_config, key, value)
            elif key in ConfigModel.model_fields:
                setattr(project.config, key, value)
            else:
                raise SeretoValueError(f"Unknown config field: '{key}'")

        project.config.save()
    else:
        # Interactive: open the config file in the default editor
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
def add_dates_config(
    config: Config,
    version: ProjectVersion | None = None,
    non_interactive: bool = False,
    date_type: DateType | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    """Add date to the configuration.

    Args:
        config: Configuration of the project.
        version: The version of the project. If not provided, the last version is used.
        non_interactive: If True, run non-interactively; fail if required inputs are missing.
        date_type: The type of the date event.
        start_date: The start date str in DD-Mmm-YYYY format.
        end_date: The end date str in DD-Mmm-YYYY format.
    """
    if version is None:
        version = config.last_version

    if non_interactive:
        new_date = _build_date_from_options(date_type=date_type, start_date=start_date, end_date=end_date)
    else:
        new_date = _prompt_for_date()

    # Add the date to the configuration
    config.at_version(version).add_date(new_date)

    # Write the configuration
    config.save()


def _build_date_from_options(
    date_type: DateType | None,
    start_date: str | None,
    end_date: str | None,
) -> Date:
    """Build a Date from CLI options for the non-interactive flow."""
    if date_type is None or not start_date:
        raise SeretoValueError(
            "Both '--type' and '--date' must be provided. Optionally, '--end' can also be provided for a date range."
        )
    if end_date and not allows_range(date_type):
        raise SeretoValueError("End date is not allowed for date types that do not allow ranges.")

    parsed_start = SeretoDate(start_date)
    parsed_end = SeretoDate(end_date) if end_date else parsed_start
    value: SeretoDate | DateRange = (
        DateRange(start=parsed_start, end=parsed_end)
        if allows_range(date_type) and parsed_start != parsed_end
        else parsed_start
    )
    return Date(type=date_type, date=value)


def _prompt_for_date() -> Date:
    """Prompt the user for a date interactively."""
    date_type = load_enum(enum=DateType, message="Type:")
    return Date(type=date_type, date=prompt_user_for_date(date_type=date_type))


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

    for ix, d in enumerate(version_config.dates, start=1):
        match d.date:
            case DateRange():
                table.add_row(
                    str(ix),
                    d.type.value,
                    str(d.date.start),
                    str(d.date.end),
                )
            case _:
                table.add_row(str(ix), d.type.value, str(d.date), "[yellow]n/a")

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
def add_people_config(
    config: Config,
    version: ProjectVersion | None = None,
    non_interactive: bool = False,
    person_type: PersonType | None = None,
    person_name: str | None = None,
    business_unit: str | None = None,
    email: str | None = None,
    role: str | None = None,
) -> None:
    """Add person to the configuration.

    Args:
        config: Configuration of the project.
        version: The version of the project. If not provided, the last version is used.
        non_interactive: If True, run non-interactively; fail if required inputs are missing.
        person_type: The type of the person.
        person_name: The name of the person.
        business_unit: The business unit of the person.
        email: The email address of the person.
        role: The role of the person.
    """
    if version is None:
        version = config.last_version

    if non_interactive:
        new_person = _build_person_from_options(
            person_type=person_type,
            person_name=person_name,
            business_unit=business_unit,
            email=email,
            role=role,
        )
    else:
        new_person = _prompt_for_person()

    # Add the person to the configuration
    config.at_version(version).add_person(new_person)

    # Write the configuration
    config.save()


def _build_person_from_options(
    person_type: PersonType | None,
    person_name: str | None,
    business_unit: str | None,
    email: str | None,
    role: str | None,
) -> Person:
    """Build a Person from CLI options for the non-interactive flow."""
    if person_type is None:
        raise SeretoValueError("Person type must be provided.")
    return Person(
        type=person_type,
        name=person_name or None,
        business_unit=business_unit or None,
        email=email or None,
        role=role or None,
    )


def _prompt_for_person() -> Person:
    """Prompt the user for a person interactively."""
    person_type = load_enum(enum=PersonType, message="Type:")
    return prompt_user_for_person(person_type=person_type)


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
    non_interactive: bool = False,
    category: str | None = None,
    target_name: str | None = None,
    extra_json: str | None = None,
) -> None:
    """Add target to the configuration.

    Args:
        project_path: Path to the project directory.
        templates: Path to the templates directory.
        config: Configuration of the project.
        categories: List of all categories.
        version: The version of the project. If not provided, the last version is used.
        non_interactive: If True, run non-interactively; fail if required inputs are missing.
        category: Category of the target.
        target_name: Name of the target.
        extra_json: Extra target fields as a JSON string.
    """
    if version is None:
        version = config.last_version

    if non_interactive:
        new_target_model = _build_target_from_options(
            category=category, target_name=target_name, categories=categories, extra_json=extra_json
        )
    else:
        new_target_model = prompt_user_for_target(categories=categories)

    # Create the target instance, including on the filesystem
    new_target = Target.new(data=new_target_model, project_path=project_path, templates=templates, version=version)

    # Add the target to the configuration
    config.at_version(version).add_target(new_target)

    # Write the configuration
    config.save()


def _build_target_from_options(
    category: str | None,
    target_name: str | None,
    categories: Iterable[str],
    extra_json: str | None = None,
) -> TargetModel:
    """Build a TargetModel from CLI options for the non-interactive flow."""

    if not category or not target_name:
        raise SeretoValueError("Both category and target name must be provided when using non-interactive mode.")

    category = category.lower()
    categories = list(categories)

    if category not in categories:
        raise SeretoValueError(f"Invalid category '{category}'. Must be one of: {', '.join(categories)}.")

    try:
        extra = json.loads(extra_json) if extra_json else {}
    except json.JSONDecodeError as e:
        raise SeretoValueError(f"Invalid JSON in '--extra': {e}") from e

    if not isinstance(extra, dict):
        raise SeretoValueError("'--extra' must be a JSON object, e.g. '{\"environment\": \"production\"}'")

    model_class: type[TargetModel]
    match category:
        case "dast":
            model_class = TargetDastModel
        case "sast":
            model_class = TargetSastModel
        case "mobile":
            model_class = TargetMobileModel
        case _:
            model_class = TargetModel

    reserved = {"category", "name"}
    valid_fields = set(model_class.model_fields.keys()) - reserved
    for key in extra:
        if key not in valid_fields:
            raise SeretoValueError(
                f"Unknown field '{key}' for category '{category}'. "
                f"Valid extra fields: {', '.join(sorted(valid_fields)) or 'none'}."
            )

    try:
        data = {"category": category, "name": target_name, **extra}
        return model_class.model_validate(data, strict=False)
    except Exception as e:
        if isinstance(e, ValidationError):
            errors = "; ".join(f"{' -> '.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors())
            raise SeretoValueError(f"Invalid value(s) in '--extra': {errors}") from e
        raise


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
            TargetList: TypeAdapter[list[AnyTargetModel]] = TypeAdapter(list[AnyTargetModel])
            TargetAll: TypeAdapter[dict[str, list[AnyTargetModel]]] = TypeAdapter(dict[str, list[AnyTargetModel]])

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
