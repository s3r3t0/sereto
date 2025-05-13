import importlib.metadata
from dataclasses import dataclass
from pathlib import Path
from typing import Self, TypeVar

from pydantic import DirectoryPath, validate_call
from typing_extensions import ParamSpec

from sereto.cli.utils import Console
from sereto.config import Config, VersionConfig
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.person import Person
from sereto.models.settings import Settings
from sereto.models.version import ProjectVersion, SeretoVersion
from sereto.plot import risks_plot
from sereto.settings import load_settings_function
from sereto.target import Target
from sereto.types import TypeProjectId
from sereto.utils import copy_skel

P = ParamSpec("P")
R = TypeVar("R")


@dataclass
class Project:
    _settings: Settings | None = None
    _project_path: DirectoryPath | None = None
    _config: Config | None = None

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = load_settings_function()
        return self._settings

    @property
    def path(self) -> DirectoryPath:
        if self._project_path is None:
            self._project_path = get_project_path_from_dir(dir=Path.cwd(), dir_subtree=self.settings.projects_path)
        return self._project_path

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = Config.load_from(self.path / "config.json", templates=self.settings.templates_path)
        return self._config

    @property
    def config_path(self) -> Path:
        """Get the path to the project configuration file."""
        return self.path / "config.json"

    @classmethod
    def load_from(cls, path: DirectoryPath) -> Self:
        if not is_project_dir(path):
            raise SeretoPathError("not a project directory")
        return cls(_project_path=path)


@validate_call
def is_project_dir(path: Path) -> bool:
    """Check if the provided path is a root directory of a project.

    A project directory contains at least `.sereto` and `config.json` files.

    Args:
        path: The path to examine.

    Returns:
        True if the path is a project directory, False otherwise.
    """
    return path.is_dir() and path.exists() and (path / ".sereto").is_file() and (path / "config.json").is_file()


@validate_call
def get_project_path_from_dir(dir: DirectoryPath | None = None, dir_subtree: DirectoryPath = Path("/")) -> Path:
    """Get the path to the project directory.

    Start the search from the 'dir' directory and go up the directory tree until the project directory is
    found or 'dir_subtree' is reached.

    Args:
        dir: The directory to start the search from. Defaults to the current working directory.
        dir_subtree: The directory to stop the search at. Defaults to the root directory.

    Raises:
        SeretoPathError: If the current working directory is not inside the project's (sub)directory.

    Returns:
        The path to the project directory.
    """
    if dir is None:
        dir = Path.cwd()

    # start from the current working directory and go up the directory tree
    for d in [dir] + list(dir.parents):
        # if the current directory is inside the subtree
        if d.is_relative_to(dir_subtree):
            # if the current directory is a project directory
            if is_project_dir(d):
                return d
        else:
            # stop the search before leaving the subtree
            break

    raise SeretoPathError("not inside project's (sub)directory")


@validate_call
def init_build_dir(
    project_path: DirectoryPath, version_config: VersionConfig | None = None, target: Target | None = None
) -> None:
    """Initialize the build directory."""
    if (version_config is None and target is None) or (version_config is not None and target is not None):
        raise SeretoValueError("either 'version_config' or 'target' must be specified")

    # Create ".build" directory
    if not (build_dir := project_path / ".build").is_dir():
        build_dir.mkdir(parents=True)

    # Create target directories
    targets: list[Target] = [target] if target is not None else version_config.targets  # type: ignore[union-attr]
    for target in targets:
        if not (target_dir := build_dir / target.uname).is_dir():
            target_dir.mkdir(parents=True)


@validate_call
def project_create_missing(project_path: DirectoryPath, version_config: VersionConfig) -> None:
    """Creates missing content in the project.

    Args:
        project_path: The path to the project directory.
        version_config: Configuration for a specific project version.
    """
    # Initialize the build directory
    init_build_dir(project_path=project_path, version_config=version_config)

    # Make sure that "layouts/generated" directory exists
    if not (layouts_generated := project_path / "layouts" / "generated").is_dir():
        layouts_generated.mkdir(parents=True)

    for target in version_config.targets:
        # Generate risks plot for the target
        risks_plot(risks=target.findings.risks, path=project_path / ".build" / target.uname / "risks.png")


@validate_call
def new_project(
    projects_path: DirectoryPath,
    templates_path: DirectoryPath,
    id: TypeProjectId,
    name: str,
    people: list[Person],
) -> None:
    """Generates a new project with the specified ID.

    Args:
        projects_path: The path to the projects directory.
        templates_path: The path to the templates directory.
        id: The ID of the new project. This should be a string that uniquely identifies the project.
        name: The name of the new project.
        people: Initial list of people from global settings.

    Raises:
        SeretoValueError: If a project with the specified ID already exists in the `projects` directory.
    """
    Console().log(f"Generating a new project with ID {id!r}")

    if (new_path := projects_path / id).exists():
        raise SeretoPathError("project with specified ID already exists")
    else:
        new_path.mkdir()

    sereto_ver = importlib.metadata.version("sereto")

    Console().log("Copy project skeleton")
    copy_skel(templates=templates_path, dst=new_path)

    config_path = new_path / "config.json"

    Console().log(f"Writing the config '{config_path}'")
    Config(
        sereto_version=SeretoVersion.from_str(sereto_ver),
        version_configs={
            ProjectVersion.from_str("v1.0"): VersionConfig(
                version=ProjectVersion.from_str("v1.0"),
                id=id,
                name=name,
                version_description="Initial",
                people=people,
            ),
        },
        path=config_path,
    ).save()
