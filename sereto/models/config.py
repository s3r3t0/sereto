from copy import deepcopy
from pathlib import Path

from pydantic import model_validator, validate_call

from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.base import SeretoBaseModel
from sereto.models.date import Date
from sereto.models.person import Person
from sereto.models.target import Target
from sereto.models.version import ReportVersion, SeretoVersion


class BaseConfig(SeretoBaseModel):
    """Base class for model representing the config."""

    id: str
    name: str
    report_version: ReportVersion
    targets: list[Target] = []
    dates: list[Date] = []
    people: list[Person] = []

    @model_validator(mode="after")
    def unique_names(self) -> "BaseConfig":
        unames = [target.uname for target in self.targets]
        if len(unames) != len(set(unames)):
            raise ValueError("duplicate target uname")
        return self


class Config(BaseConfig):
    """Model representing a config.

    Attributes:
        sereto_version (SeretoVersion): Version of SeReTo which produced the config.
        updates (list[BaseConfig]): List of updates.
    """

    sereto_version: SeretoVersion
    updates: list[BaseConfig] = []

    @model_validator(mode="after")
    def config_validator(self) -> "Config":
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
    def from_file(cls, filepath: Path) -> "Config":
        try:
            return cls.model_validate_json(filepath.read_bytes())
        except FileNotFoundError:
            raise SeretoPathError(f'file not found at "{filepath}"') from None
        except PermissionError:
            raise SeretoPathError(f'permission denied for "{filepath}"') from None
        except ValueError as e:
            raise SeretoValueError("invalid config") from e

    @validate_call
    def versions(self) -> list[ReportVersion]:
        """Get a list of report versions."""
        return [self.report_version] + [update.report_version for update in self.updates]

    @validate_call
    def last_version(self) -> ReportVersion:
        """Get the last report version."""
        return self.versions()[-1]

    def at_version(self, version: str | ReportVersion | None) -> BaseConfig:
        """Return the configuration at a specific version.

        Args:
            version: A version of the report configuration to return. If None is provided, return the
                whole config with all the updates sections.

        Returns:
            A new Config object representing the configuration for the report at the specified version.

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
