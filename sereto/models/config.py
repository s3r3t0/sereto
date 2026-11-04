import re
from pathlib import Path
from typing import Any, Self, cast

from pydantic import Field, FilePath, ValidationError, ValidationInfo, field_validator, model_validator, validate_call

from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.logging import logger
from sereto.models.base import SeretoBaseModel
from sereto.models.date import Date
from sereto.models.person import Person
from sereto.models.target import (
    TARGET_ID_PATTERN,
    AnyTargetModel,
    TargetModel,
    parse_target_model,
    target_directory_name,
)
from sereto.models.version import ProjectVersion, SeretoVersion
from sereto.utils import lower_alphanum


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
    targets: list[AnyTargetModel] = Field(default_factory=list)
    dates: list[Date] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)

    @field_validator("targets", mode="before")
    @classmethod
    def parse_targets(cls, targets: object, info: ValidationInfo) -> object:
        if not isinstance(targets, list):
            return targets

        target_list = cast(list[TargetModel | dict[str, Any]], targets)
        context = cast(dict[str, Any] | None, info.context)
        return [parse_target_model(target, context=context) for target in target_list]

    @model_validator(mode="after")
    def unique_target_names(self) -> Self:
        names = [lower_alphanum(f"{target.category} {target.name}") for target in self.targets]
        if len(names) != len(set(names)):
            raise ValueError("duplicate target name within same category")
        return self

    @model_validator(mode="after")
    def unique_target_ids(self) -> Self:
        seen: set[str] = set()
        for target in self.targets:
            if target.id in seen:
                raise ValueError(f"duplicate target id: {target.id!r}")
            seen.add(target.id)
        return self


class ConfigModel(SeretoBaseModel):
    """Model representing the full project configuration in config.json file.

    Attributes:
        sereto_version: Version of SeReTo which produced the config.
        version_configs: Configuration for each version of the Project.
    """

    sereto_version: SeretoVersion
    version_configs: dict[ProjectVersion, VersionConfigModel]

    @field_validator("version_configs", mode="before")
    @classmethod
    def adopt_existing_target_directories(cls, value: Any, info: ValidationInfo) -> Any:
        """Adopt existing target directories with legacy naming conventions.

        Preserve IDs with existing target_<id> directories, otherwise adopt normalized
        category/name IDs regardless of any previous ID. Leave missing-ID generation to the target model.
        """
        project_path = info.context.get("project_path") if info.context else None
        if not isinstance(project_path, Path) or not isinstance(value, dict):
            return value

        versions = dict(cast(dict[str | ProjectVersion, Any], value))
        for version, config in versions.items():
            if not isinstance(config, dict) or not isinstance(config.get("targets"), list):
                continue
            config = cast(dict[str, Any], config)
            project_version = version if isinstance(version, ProjectVersion) else ProjectVersion.from_str(version)
            targets: list[Any] = []
            for target in config["targets"]:
                if not isinstance(target, dict):
                    targets.append(target)
                    continue
                target = dict(cast(dict[str, Any], target))
                old_id = target.get("id")
                existing_id_directory = (
                    isinstance(old_id, str)
                    and re.fullmatch(TARGET_ID_PATTERN, old_id) is not None
                    and (project_path / target_directory_name(old_id, project_version)).is_dir()
                )
                if (
                    not existing_id_directory  # Preserve valid existing ID and its directory
                    and isinstance(target.get("category"), str)
                    and isinstance(target.get("name"), str)
                ):
                    legacy_id = lower_alphanum(f"{target['category']}_{target['name']}")
                    legacy_name = target_directory_name(legacy_id, project_version)
                    # Only adopt the legacy ID if the corresponding legacy directory exists
                    if (project_path / legacy_name).is_dir():
                        # Adopt the legacy ID and leave the existing directory untouched
                        target["id"] = legacy_id
                        logger.info(
                            "Adopting target directory '{}' with ID '{}' in {}", legacy_name, legacy_id, version
                        )
                targets.append(target)
            versions[version] = {**config, "targets": targets}
        return versions

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
            return cls.model_validate_json(file.read_bytes(), context={"project_path": file.parent})
        except FileNotFoundError:
            raise SeretoPathError(f"file not found at '{file}'") from None
        except PermissionError:
            raise SeretoPathError(f"permission denied for '{file}'") from None
        except ValidationError as e:
            raise SeretoValueError(f"invalid config\n\n{e}") from e
