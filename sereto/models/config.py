import re
from collections.abc import Iterable
from typing import Self

from pydantic import DirectoryPath, FilePath, NewPath, ValidationError, model_validator, validate_call

from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.base import SeretoBaseModel
from sereto.models.date import Date, DateRange, DateType, SeretoDate
from sereto.models.person import Person, PersonType
from sereto.models.target import Target
from sereto.models.version import ProjectVersion, SeretoVersion


class VersionConfig(SeretoBaseModel):
    """Model with core attributes for a specific version of the report configuration.

    Attributes:
        id: The ID of the report.
        name: The name of the report.
        targets: List of targets.
        dates: List of dates.
        people: List of people.
    """

    id: str
    name: str
    targets: list[Target] = []
    dates: list[Date] = []
    people: list[Person] = []

    @model_validator(mode="after")
    def unique_target_names(self) -> Self:
        unames = [target.uname for target in self.targets]
        if len(unames) != len(set(unames)):
            raise ValueError("duplicate target uname")
        return self

    @validate_call
    def filter_targets(
        self,
        category: str | Iterable[str] | None = None,
        name: str | None = None,
        inverse: bool = False,
    ) -> list[Target]:
        """Filter targets based on specified criteria.

        The regular expressions support the syntax of Python's `re` module.

        Args:
            category: The category of the target. Can be a single category, a list of categories, or None.
            name: Regular expression to match the name of the target.
            inverse: If True, return the inverse of the usual results.

        Returns:
            A list of targets matching the criteria.
        """
        if isinstance(category, str):
            category = [category]

        filtered_targets = [
            t
            for t in self.targets
            if (category is None or t.category in category) and (name is None or re.search(name, t.name))
        ]

        if inverse:
            return [t for t in self.targets if t not in filtered_targets]
        return filtered_targets

    @validate_call
    def filter_dates(
        self,
        type: str | DateType | Iterable[str] | Iterable[DateType] | None = None,
        start: str | SeretoDate | None = None,
        end: str | SeretoDate | None = None,
        inverse: bool = False,
    ) -> list[Date]:
        """Filter dates based on specified criteria.

        The start and end dates are inclusive. For date ranges, a date is considered matching if it completely overlaps
        with the specified range.

        Args:
            type: The type of the date. Can be a single type, a list of types, or None.
            start: Only dates on or after this date will be included.
            end: Only dates on or before this date will be included.
            inverse: If True, return the inverse of the usual results.

        Returns:
            A list of dates matching the criteria.
        """
        match type:
            case str():
                type = [DateType(type)]
            case Iterable():
                type = [DateType(t) for t in type]
            case None:
                pass

        if isinstance(start, str):
            start = SeretoDate.from_str(start)
        if isinstance(end, str):
            end = SeretoDate.from_str(end)

        filtered_dates = [
            d
            for d in self.dates
            if (type is None or d.type in type)
            and (
                start is None
                or (isinstance(d.date, SeretoDate) and d.date >= start)
                or (isinstance(d.date, DateRange) and d.date.start >= start)
            )
            and (
                end is None
                or (isinstance(d.date, SeretoDate) and d.date <= end)
                or (isinstance(d.date, DateRange) and d.date.end <= end)
            )
        ]

        if inverse:
            return [d for d in self.dates if d not in filtered_dates]
        return filtered_dates

    @validate_call
    def filter_people(
        self,
        type: str | PersonType | Iterable[str] | Iterable[PersonType] | None = None,
        name: str | None = None,
        business_unit: str | None = None,
        email: str | None = None,
        role: str | None = None,
        inverse: bool = False,
    ) -> list[Person]:
        """Filter people based on specified criteria.

        The regular expressions support the syntax of Python's `re` module.

        Args:
            type: The type of the person. Can be a single type, a list of types, or None.
            name: Regular expression to match the name of the person.
            business_unit: Regular expression to match the business unit of the person.
            email: Regular expression to match the email of the person.
            role: Regular expression to match the role of the person.
            inverse: If True, return the inverse of the usual results.

        Returns:
            A list of people matching the criteria.
        """
        match type:
            case str():
                type = [PersonType(type)]
            case Iterable():
                type = [PersonType(t) for t in type]
            case None:
                pass

        filtered_people = [
            p
            for p in self.people
            if (type is None or p.type in type)
            and (name is None or (p.name is not None and re.search(name, p.name)))
            and (business_unit is None or (p.business_unit is not None and re.search(business_unit, p.business_unit)))
            and (email is None or (p.email is not None and re.search(email, p.email)))
            and (role is None or (p.role is not None and re.search(role, p.role)))
        ]

        if inverse:
            return [p for p in self.people if p not in filtered_people]
        return filtered_people

    @validate_call
    def add_target(self, target: Target) -> Self:
        """Add a target to the configuration.

        Args:
            target: The target to add.

        Returns:
            The configuration with the added target.
        """
        self.targets.append(target)
        return self

    @validate_call
    def delete_target(self, index: int) -> Self:
        """Delete a target from the configuration.

        Args:
            index: The index of the target to delete. First item is 1.

        Returns:
            The configuration with the target deleted.
        """
        # Convert to 0-based index
        index -= 1

        # Check if the index is in the allowed range
        if not 0 <= index <= len(self.targets) - 1:
            raise SeretoValueError("index out of range")

        # Delete the target
        del self.targets[index]

        return self

    @validate_call
    def add_date(self, date: Date) -> Self:
        """Add a date to the configuration.

        Args:
            date: The date to add.

        Returns:
            The configuration with the added date.
        """
        self.dates.append(date)
        return self

    @validate_call
    def delete_date(self, index: int) -> Self:
        """Delete a date from the configuration.

        Args:
            index: The index of the date to delete. First item is 1.

        Returns:
            The configuration with the date deleted.
        """
        # Convert to 0-based index
        index -= 1

        # Check if the index is in the allowed range
        if not 0 <= index <= len(self.dates) - 1:
            raise SeretoValueError("index out of range")

        # Delete the date
        del self.dates[index]

        return self

    @validate_call
    def add_person(self, person: Person) -> Self:
        """Add a person to the configuration.

        Args:
            person: The person to add.

        Returns:
            The configuration with the added person.
        """
        self.people.append(person)
        return self

    @validate_call
    def delete_person(self, index: int) -> Self:
        """Delete a person from the configuration.

        Args:
            index: The index of the person to delete. First item is 1.

        Returns:
            The configuration with the person deleted.
        """
        # Convert to 0-based index
        index -= 1

        # Check if the index is in the allowed range
        if not 0 <= index <= len(self.people) - 1:
            raise SeretoValueError("index out of range")

        # Delete the person
        del self.people[index]

        return self


class Config(SeretoBaseModel):
    """Model representing the full report configuration.

    Attributes:
        sereto_version: Version of SeReTo which produced the config.
        version_configs: Configuration for each version of the Project.
    """

    sereto_version: SeretoVersion
    version_configs: dict[ProjectVersion, VersionConfig]

    @classmethod
    @validate_call
    def load_from(cls, file: FilePath) -> Self:
        """Load the configuration from a JSON file.

        Args:
            file: The path to the configuration file.

        Returns:
            The configuration object.

        Raises:
            SeretoPathError: If the file is not found or permission is denied.
            SeretoValueError: If the configuration is invalid.
        """
        try:
            return cls.model_validate_json(file.read_bytes())
        except FileNotFoundError:
            raise SeretoPathError(f"file not found at '{file}'") from None
        except PermissionError:
            raise SeretoPathError(f"permission denied for '{file}'") from None
        except ValidationError as e:
            raise SeretoValueError(f"invalid config\n\n{e}") from e

    @validate_call
    def dump_json(self, file: FilePath | NewPath) -> None:
        """Write report configuration to a JSON file.

        Args:
            file: The path to the configuration file.
        """
        file.write_text(self.model_dump_json(indent=2) + "\n")

    def iter(self) -> Iterable[VersionConfig]:
        """Iterate over all version configurations."""
        for version in self.versions():
            yield self.version_configs[version]

    @validate_call
    def add_config(self, version: ProjectVersion, config: VersionConfig) -> Self:
        """Add a configuration for a specific version.

        Args:
            version: The version of the configuration.
            config: The configuration.

        Returns:
            The configuration with the added version configuration.
        """
        if version in self.version_configs:
            raise SeretoValueError(f"version '{version}' already exists")

        self.version_configs[version] = config
        return self

    def first_config(self) -> VersionConfig:
        """Get the configuration for the first project version.

        Returns:
            The configuration for the last project version.
        """
        return self.at_version(self.first_version())

    def last_config(self) -> VersionConfig:
        """Get the configuration for the last project version.

        Returns:
            The configuration for the last project version.
        """
        return self.at_version(self.last_version())

    @validate_call
    def update_paths(self, project_path: DirectoryPath) -> Self:
        """Update the full paths of the individual config components.

        When the configuration is loaded, it has no knowledge of the project path. This method updates the paths in the
        individual config components.

        Args:
            project_path: The path to the project directory.

        Returns:
            The configuration with updated paths.
        """
        for vc in self.iter():
            for target in vc.targets:
                target.path = project_path / target.uname

        return self

    @validate_call
    def versions(self) -> list[ProjectVersion]:
        """Get a sorted list of report versions in ascending order.

        Returns:
            A list of report versions.
        """
        return sorted(list(self.version_configs.keys()))

    @validate_call
    def first_version(self) -> ProjectVersion:
        """Get the first report version present in the configuration.

        Returns:
            The first report version.
        """
        return self.versions()[0]

    @validate_call
    def last_version(self) -> ProjectVersion:
        """Get the last report version present in the configuration.

        Returns:
            The last report version.
        """
        return self.versions()[-1]

    @validate_call
    def at_version(self, version: str | ProjectVersion) -> VersionConfig:
        """Return the configuration at a specific version.

        Args:
            version: Selects which version of the configuration should be returned.

        Returns:
            Configuration for the report at the specified version.

        Raises:
            SeretoValueError: If the specified version is unknown.
        """
        if isinstance(version, str):
            version = ProjectVersion.from_str(version)

        if version not in self.version_configs:
            raise SeretoValueError(f"version '{version}' not found")

        return self.version_configs[version]
