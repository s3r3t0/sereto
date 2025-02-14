import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Self

from pydantic import FilePath, validate_call

from sereto.exceptions import SeretoValueError
from sereto.models.config import ConfigModel, VersionConfigModel
from sereto.models.date import Date, DateRange, DateType, SeretoDate
from sereto.models.person import Person, PersonType
from sereto.models.target import Target
from sereto.models.version import ProjectVersion, SeretoVersion


@dataclass
class VersionConfig:
    version: ProjectVersion
    config: VersionConfigModel

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
            for t in self.config.targets
            if (category is None or t.category in category) and (name is None or re.search(name, t.name))
        ]

        if inverse:
            return [t for t in self.config.targets if t not in filtered_targets]
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
            for d in self.config.dates
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
            return [d for d in self.config.dates if d not in filtered_dates]
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
            for p in self.config.people
            if (type is None or p.type in type)
            and (name is None or (p.name is not None and re.search(name, p.name)))
            and (business_unit is None or (p.business_unit is not None and re.search(business_unit, p.business_unit)))
            and (email is None or (p.email is not None and re.search(email, p.email)))
            and (role is None or (p.role is not None and re.search(role, p.role)))
        ]

        if inverse:
            return [p for p in self.config.people if p not in filtered_people]
        return filtered_people

    @validate_call
    def add_target(self, target: Target) -> Self:
        """Add a target to the configuration.

        Args:
            target: The target to add.

        Returns:
            The configuration with the added target.
        """
        self.config.targets.append(target)
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
        if not 0 <= index <= len(self.config.targets) - 1:
            raise SeretoValueError("index out of range")

        # Delete the target
        del self.config.targets[index]

        return self

    @validate_call
    def add_date(self, date: Date) -> Self:
        """Add a date to the configuration.

        Args:
            date: The date to add.

        Returns:
            The configuration with the added date.
        """
        self.config.dates.append(date)
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
        if not 0 <= index <= len(self.config.dates) - 1:
            raise SeretoValueError("index out of range")

        # Delete the date
        del self.config.dates[index]

        return self

    @validate_call
    def add_person(self, person: Person) -> Self:
        """Add a person to the configuration.

        Args:
            person: The person to add.

        Returns:
            The configuration with the added person.
        """
        self.config.people.append(person)
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
        if not 0 <= index <= len(self.config.people) - 1:
            raise SeretoValueError("index out of range")

        # Delete the person
        del self.config.people[index]

        return self


@dataclass
class Config:
    sereto_version: SeretoVersion
    version_configs: dict[ProjectVersion, VersionConfig]
    path: FilePath

    @classmethod
    @validate_call
    def load_from(cls, path: FilePath) -> Self:
        config = ConfigModel.load_from(path)

        # TODO remove when not needed anymore
        # update target paths
        for version_config in config.version_configs.values():
            for target in version_config.targets:
                target.path = path.parent / target.uname

        return cls(
            sereto_version=config.sereto_version,
            version_configs={
                version: VersionConfig(version=version, config=config.version_configs[version])
                for version in config.version_configs
            },
            path=path,
        )

    def to_model(self) -> ConfigModel:
        return ConfigModel(
            sereto_version=self.sereto_version,
            version_configs={version: config.config for version, config in self.version_configs.items()},
        )

    def save(self) -> None:
        self.path.write_text(self.to_model().model_dump_json(indent=2) + "\n")

    @property
    def versions(self) -> list[ProjectVersion]:
        """Get a sorted list of project versions in ascending order."""
        return sorted(list(self.version_configs.keys()))

    @validate_call
    def at_version(self, version: str | ProjectVersion) -> VersionConfig:
        """Return the configuration at a specific version.

        Args:
            version: Selects which version of the configuration should be returned.

        Returns:
            Configuration for the project at the specified version.

        Raises:
            SeretoValueError: If the specified version is unknown.
        """
        if isinstance(version, str):
            version = ProjectVersion.from_str(version)

        if version not in self.versions:
            raise SeretoValueError(f"version '{version}' not found")

        return VersionConfig(version=version, config=self.version_configs[version].config)

    @property
    def first_version(self) -> ProjectVersion:
        """Get the first version present in the configuration."""
        return self.versions[0]

    @property
    def last_version(self) -> ProjectVersion:
        """Get the last version present in the configuration."""
        return self.versions[-1]

    @property
    def first_config(self) -> VersionConfig:
        """Get the configuration for the first project version."""
        return self.at_version(self.first_version)

    @property
    def last_config(self) -> VersionConfig:
        """Get the configuration for the last project version."""
        return self.at_version(self.last_version)

    @validate_call
    def add_version_config(self, version: ProjectVersion, config: VersionConfigModel) -> Self:
        """Add a new version configuration to the project.

        Args:
            version: The version of the new configuration.
            config: The configuration to add.

        Returns:
            The updated configuration.

        Raises:
            SeretoValueError: If the specified version already exists.
        """
        if version in self.versions:
            raise SeretoValueError(f"version '{version}' already exists")

        self.version_configs[version].config = config

        return self
