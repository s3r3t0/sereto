from copy import deepcopy
from typing import Self

from pydantic import DirectoryPath, Field, FilePath, NewPath, ValidationError, model_validator, validate_call

from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.base import SeretoBaseModel
from sereto.models.date import Date
from sereto.models.person import Person
from sereto.models.target import Target
from sereto.models.version import ReportVersion, SeretoVersion


class BaseConfig(SeretoBaseModel):
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


class Config(BaseConfig):
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
    updates: list[BaseConfig] = Field(default=[])

    @model_validator(mode="after")
    def config_validator(self) -> Self:
        # if self.id is None or self.name is None:
        #     raise ValueError("'id' and 'name' variables cannot be None")

        previous: BaseConfig = self

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
    def at_version(self, version: str | ReportVersion) -> BaseConfig:
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

        # For v1.0, we need to convert Config to BaseConfig (excluding extra fields)
        if self.report_version == version:  # v1.0
            cfg = BaseConfig.model_validate(self.model_dump(exclude={"sereto_version", "updates"}))
            # copy values of the excluded fields
            for t1, t2 in zip(self.targets, cfg.targets, strict=True):
                t2.path = t1.path
            return cfg

        # Otherwise, we need to find the matching update section
        if len(res := [cfg for cfg in self.updates if cfg.report_version == version]) != 1:
            raise SeretoValueError(f"version '{version}' not found")

        return res[0]
