import operator
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import reduce
from typing import Literal, Self, overload

from pydantic import DirectoryPath, FilePath, NonNegativeInt, validate_call

from sereto.exceptions import SeretoValueError
from sereto.models.config import ConfigModel, VersionConfigModel
from sereto.models.date import Date, DateRange, DateType, SeretoDate
from sereto.models.person import Person, PersonType
from sereto.models.target import TargetModel
from sereto.models.version import ProjectVersion, SeretoVersion
from sereto.risk import Risks
from sereto.target import Target


@dataclass
class VersionConfig:
    version: ProjectVersion
    id: str
    name: str
    version_description: str
    targets: list[Target] = field(default_factory=list)
    dates: list[Date] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)

    @validate_call
    def to_model(self) -> VersionConfigModel:
        return VersionConfigModel(
            id=self.id,
            name=self.name,
            version_description=self.version_description,
            targets=[target.to_model() for target in self.targets],
            dates=self.dates,
            people=self.people,
        )

    @classmethod
    @validate_call
    def from_model(
        cls,
        model: VersionConfigModel,
        version: ProjectVersion,
        project_path: DirectoryPath,
        templates: DirectoryPath,
    ) -> Self:
        return cls(
            version=version,
            id=model.id,
            name=model.name,
            version_description=model.version_description,
            targets=[
                Target.load(
                    data=target,
                    path=project_path / (target.uname + version.path_suffix),
                    version=version,
                    templates=templates,
                )
                for target in model.targets
            ],
            dates=model.dates,
            people=model.people,
        )

    @validate_call
    def filter_targets(
        self,
        category: str | Iterable[str] | None = None,
        name: str | None = None,
        inverse: bool = False,
    ) -> list[TargetModel]:
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
            if (category is None or t.data.category in category) and (name is None or re.search(name, t.data.name))
        ]

        if inverse:
            return [t.data for t in self.targets if t not in filtered_targets]
        return [t.data for t in filtered_targets]

    @validate_call
    def select_target(
        self,
        categories: Iterable[str],
        selector: int | str | None = None,
    ) -> Target:
        # only single target present
        if selector is None:
            if len(self.targets) != 1:
                raise SeretoValueError(
                    f"cannot select target; no selector provided and there are {len(self.targets)} targets present"
                )
            return self.targets[0]

        # by index
        if isinstance(selector, int) or selector.isnumeric():
            ix = selector - 1 if isinstance(selector, int) else int(selector) - 1
            if not (0 <= ix <= len(self.targets) - 1):
                raise SeretoValueError("target index out of range")

            return self.targets[ix]

        # by unique category
        if selector in categories:
            filtered_targets = [t for t in self.targets if t.data.category == selector]
            match len(filtered_targets):
                case 0:
                    raise SeretoValueError(f"category {selector!r} does not contain any target")
                case 1:
                    return filtered_targets[0]
                case _:
                    raise SeretoValueError(
                        f"category {selector!r} contains multiple targets, use unique name when querying"
                    )

        # by uname
        filtered_targets = [t for t in self.targets if t.uname == selector]
        if len(filtered_targets) != 1:
            raise SeretoValueError(f"target with uname {selector!r} not found")
        return filtered_targets[0]

    @validate_call
    @overload
    def filter_dates(
        self,
        type: str | DateType | Iterable[str] | Iterable[DateType] | None = ...,
        start: str | SeretoDate | None = ...,
        end: str | SeretoDate | None = ...,
        *,
        first_date: Literal[True],
        last_date: Literal[False] = False,
        inverse: bool = False,
    ) -> SeretoDate | None: ...

    @overload
    def filter_dates(
        self,
        type: str | DateType | Iterable[str] | Iterable[DateType] | None = ...,
        start: str | SeretoDate | None = ...,
        end: str | SeretoDate | None = ...,
        *,
        first_date: Literal[False] = False,
        last_date: Literal[True],
        inverse: bool = False,
    ) -> SeretoDate | None: ...

    @overload
    def filter_dates(
        self,
        type: str | DateType | Iterable[str] | Iterable[DateType] | None = ...,
        start: str | SeretoDate | None = ...,
        end: str | SeretoDate | None = ...,
        *,
        first_date: Literal[False],
        last_date: Literal[False],
        inverse: bool = False,
    ) -> list[Date]: ...

    def filter_dates(
        self,
        type: str | DateType | Iterable[str] | Iterable[DateType] | None = None,
        start: str | SeretoDate | None = None,
        end: str | SeretoDate | None = None,
        *,
        first_date: bool = False,
        last_date: bool = False,
        inverse: bool = False,
    ) -> list[Date] | SeretoDate | None:
        """Filter dates based on specified criteria.

        The start and end dates are inclusive. For date ranges, a date is considered matching if it completely overlaps
        with the specified range.

        Args:
            type: The type of the date. Can be `DateType`, a list of `DateType`s, or None.
            start: Only dates on or after this date will be included.
            end: Only dates on or before this date will be included.
            first_date: If True, return the earliest date matching the criteria. Even for date ranges, only the start
                date  is considered. The type returned is `SeretoDate` or None.
            last_date: If True, return the latest date matching the criteria. Even for date ranges, only the end date
                is considered. The type returned is `SeretoDate` or None.
            inverse: If True, return the inverse of the usual results.

        Returns:
            For first_date or last_date = True, returns SeretoDate or None. Otherwise, returns a list[Date].
        """
        # Check for invalid parameter combinations
        if first_date and last_date:
            raise SeretoValueError("cannot specify both first_date and last_date")
        if (first_date or last_date) and inverse:
            raise SeretoValueError("cannot specify inverse with first_date or last_date")

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

        if first_date:
            single_dates = [d.date.start if isinstance(d.date, DateRange) else d.date for d in filtered_dates]
            return min(single_dates, default=None)

        if last_date:
            single_dates = [d.date.end if isinstance(d.date, DateRange) else d.date for d in filtered_dates]
            return max(single_dates, default=None)

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

    @property
    def report_sent_date(self) -> SeretoDate | None:
        """Get the report sent date

        It has fallback to the review date and last date of the pentest ongoing.
        """
        return self.filter_dates(
            type=[DateType.report_sent, DateType.review, DateType.pentest_ongoing], last_date=True
        )

    @property
    def total_open_risks(self) -> NonNegativeInt:
        """Get the total number of open risks across all risk levels."""
        return sum(t.findings.risks.sum_open for t in self.targets)

    @property
    def sum_risks(self) -> Risks:
        """Get the sum of risks across all targets."""
        return reduce(operator.add, (t.findings.risks for t in self.targets))


@dataclass
class Config:
    sereto_version: SeretoVersion
    version_configs: dict[ProjectVersion, VersionConfig]
    path: FilePath

    @classmethod
    @validate_call
    def load_from(cls, path: FilePath, templates: DirectoryPath) -> Self:
        config = ConfigModel.load_from(path)

        return cls(
            sereto_version=config.sereto_version,
            version_configs={
                version: VersionConfig.from_model(
                    model=version_config, version=version, project_path=path.parent, templates=templates
                )
                for version, version_config in config.version_configs.items()
            },
            path=path,
        )

    def to_model(self) -> ConfigModel:
        return ConfigModel(
            sereto_version=self.sereto_version,
            version_configs={version: config.to_model() for version, config in self.version_configs.items()},
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

        return self.version_configs[version]

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
    def add_version_config(
        self, version: ProjectVersion, config: VersionConfigModel, templates: DirectoryPath
    ) -> Self:
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

        self.version_configs[version] = VersionConfig.from_model(
            model=config, version=version, project_path=self.path.parent, templates=templates
        )

        return self

    @validate_call
    def replace_version_config(
        self, version: ProjectVersion, config: VersionConfigModel, templates: DirectoryPath
    ) -> Self:
        """Replace an existing version configuration.

        Args:
            version: The version of the configuration to replace.
            config: The new configuration.
            templates: The path to the templates directory.

        Returns:
            The updated configuration.

        Raises:
            SeretoValueError: If the specified version does not exist.
        """
        if version not in self.versions:
            raise SeretoValueError(f"version '{version}' does not exist")

        self.version_configs[version] = VersionConfig.from_model(
            model=config, version=version, project_path=self.path.parent, templates=templates
        )

        return self
