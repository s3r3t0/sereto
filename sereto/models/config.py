from typing import Self

from pydantic import DirectoryPath, Field, FilePath, ValidationError, model_validator, validate_call

from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.base import SeretoBaseModel
from sereto.models.date import Date
from sereto.models.person import Person
from sereto.models.target import TargetModel
from sereto.models.version import ProjectVersion, SeretoVersion


class VersionConfigModel(SeretoBaseModel):
    """Model with core attributes for a specific version of the project configuration.

    Attributes:
        id: The ID of the project.
        name: The name of the project.
        version_description: The description of the version (e.g. "retest").
        targets: List of targets.
        dates: List of dates.
        people: List of people.
    """

    id: str
    name: str
    version_description: str
    targets: list[TargetModel] = Field(default_factory=list)
    dates: list[Date] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_target_names(self) -> Self:
        unames = [target.uname for target in self.targets]
        if len(unames) != len(set(unames)):
            raise ValueError("duplicate target uname")
        return self


class ConfigModel(SeretoBaseModel):
    """Model representing the full project configuration in config.json file.

    Attributes:
        sereto_version: Version of SeReTo which produced the config.
        version_configs: Configuration for each version of the Project.
    """

    sereto_version: SeretoVersion
    version_configs: dict[ProjectVersion, VersionConfigModel]

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

    # TODO remove
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
        for version_config in self.version_configs.values():
            for target in version_config.targets:
                target.path = project_path / target.uname

        return self
