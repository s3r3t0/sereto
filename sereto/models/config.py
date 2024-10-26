import re
from collections.abc import Iterable
from copy import deepcopy
from typing import Self

from pydantic import DirectoryPath, Field, FilePath, NewPath, ValidationError, model_validator, validate_call

from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.base import SeretoBaseModel
from sereto.models.date import Date, DateRange, DateType, SeretoDate
from sereto.models.person import Person, PersonType
from sereto.models.target import Target
from sereto.models.version import ReportVersion, SeretoVersion


class VersionConfig(SeretoBaseModel):
    """Model with core attributes for a specific version of the report configuration.

    Attributes:
        id: The ID of the report.
        name: The name of the report.
        report_version: The version of the report.
        targets: List of targets.
        dates: List of dates.
        people: List of people.
    """

    id: str
    name: str
    report_version: ReportVersion
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
    ) -> list[Target]:
        """Filter targets based on specified criteria.

        The regular expressions support the syntax of Python's `re` module.

        Args:
            category: The category of the target. Can be a single category, a list of categories, or None.
            name: Regular expression to match the name of the target.

        Returns:
            A list of targets matching the criteria.
        """
        if isinstance(category, str):
            category = [category]

        return [
            t
            for t in self.targets
            if (category is None or t.category in category) and (name is None or re.search(name, t.name))
        ]

    @validate_call
    def filter_dates(
        self,
        type: str | DateType | Iterable[str] | Iterable[DateType] | None = None,
        start: str | SeretoDate | None = None,
        end: str | SeretoDate | None = None,
    ) -> list[Date]:
        """Filter dates based on specified criteria.

        The start and end dates are inclusive. For date ranges, a date is considered matching if it completely overlaps
        with the specified range.

        Args:
            type: The type of the date. Can be a single type, a list of types, or None.

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

        return [
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

    @validate_call
    def filter_people(
        self,
        type: str | PersonType | Iterable[str] | Iterable[PersonType] | None = None,
        name: str | None = None,
        business_unit: str | None = None,
        email: str | None = None,
        role: str | None = None,
    ) -> list[Person]:
        """Filter people based on specified criteria.

        The regular expressions support the syntax of Python's `re` module.

        Args:
            type: The type of the person. Can be a single type, a list of types, or None.
            name: Regular expression to match the name of the person.
            business_unit: Regular expression to match the business unit of the person.
            email: Regular expression to match the email of the person.
            role: Regular expression to match the role of the person.

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

        return [
            p
            for p in self.people
            if (type is None or p.type in type)
            and (name is None or re.search(name, p.name))  # type: ignore[arg-type]
            and (business_unit is None or re.search(business_unit, p.business_unit))  # type: ignore[arg-type]
            and (email is None or re.search(email, p.email))  # type: ignore[arg-type]
            and (role is None or re.search(role, p.role))  # type: ignore[arg-type]
        ]


class Config(VersionConfig):
    """Model representing the full report configuration.

    Attributes:
        id: The ID of the report.
        name: The name of the report.
        report_version: The version of the report.
        targets: List of targets.
        dates: List of dates.
        people: List of people.
        sereto_version: Version of SeReTo which produced the config.
        updates: List of updates.
    """

    sereto_version: SeretoVersion
    updates: list[VersionConfig] = Field(default=[])

    @model_validator(mode="after")
    def config_validator(self) -> Self:
        # if self.id is None or self.name is None:
        #     raise ValueError("'id' and 'name' variables cannot be None")

        previous: VersionConfig = self

        for update in self.updates:
            # report_version is incremented in subsequent update sections
            if previous.report_version >= update.report_version:
                raise ValueError(f"report_version {update.report_version!r} after {previous.report_version!r}")

            # copy values from previous versions, which are not explicitly stated
            for field in ["id", "name", "targets", "people"]:
                if not getattr(update, field):
                    setattr(update, field, deepcopy(getattr(previous, field)))

            previous = update

        return self

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
        for cfg in [self] + self.updates:
            for target in cfg.targets:
                target.path = project_path / target.uname

        return self

    @validate_call
    def versions(self) -> list[ReportVersion]:
        """Get a sorted list of report versions in ascending order.

        Returns:
            A list of report versions.
        """
        return [self.report_version] + [update.report_version for update in self.updates]

    @validate_call
    def last_version(self) -> ReportVersion:
        """Get the last report version present in the configuration.

        Returns:
            The last report version.
        """
        return self.versions()[-1]

    @validate_call
    def at_version(self, version: str | ReportVersion) -> VersionConfig:
        """Return the configuration at a specific version.

        Args:
            version: Selects which version of the configuration should be returned.

        Returns:
            Configuration for the report at the specified version.

        Raises:
            SeretoValueError: If the specified version is unknown.
        """
        if version is None:
            return self
        if isinstance(version, str):
            version = ReportVersion.from_str(version)

        # For v1.0, we need to convert Config to VersionConfig manually (excluding extra fields)
        if version == ReportVersion("v1.0"):  # type: ignore[arg-type]
            cfg = VersionConfig.model_validate(self.model_dump(exclude={"sereto_version", "updates"}))
            # copy values of the excluded fields
            for t1, t2 in zip(self.targets, cfg.targets, strict=True):
                t2.path = t1.path
            return cfg

        # Otherwise, we need to find the matching update section
        if len(res := [cfg for cfg in self.updates if cfg.report_version == version]) != 1:
            raise SeretoValueError(f"version '{version}' not found")

        return res[0]
