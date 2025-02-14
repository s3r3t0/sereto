from pathlib import Path
from typing import Self

from pydantic import DirectoryPath, validate_call

from sereto.config import Config
from sereto.exceptions import SeretoPathError
from sereto.models.base import SeretoBaseModel
from sereto.models.config import ConfigModel
from sereto.models.settings import Settings
from sereto.settings import load_settings_function


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
            if Project.is_project_dir(d):
                return d
        else:
            # stop the search before leaving the subtree
            break

    raise SeretoPathError("not inside project's (sub)directory")


@validate_call
def get_config_path(dir_subtree: DirectoryPath = Path("/")) -> Path:
    """Get the path to the project configuration file.

    Args:
        dir_subtree: The directory to stop the search at. Defaults to the root directory.

    Returns:
        The path to the project configuration file.
    """
    return get_project_path_from_dir(dir_subtree=dir_subtree) / "config.json"


class Project(SeretoBaseModel):
    config: ConfigModel
    config_new: Config
    settings: Settings
    path: DirectoryPath

    @classmethod
    def load_from(cls, path: DirectoryPath | None = None) -> Self:
        """Load the project from the provided path.

        Args:
            path: The path to the project (sub)directory. Defaults to the current working directory.

        Returns:
            The project object.
        """
        settings = load_settings_function()
        project_path = get_project_path_from_dir(
            dir=path if path is not None else Path.cwd(), dir_subtree=settings.projects_path
        )
        config = ConfigModel.load_from(file=project_path / "config.json").update_paths(project_path=project_path)
        config_new = Config.load_from(project_path / "config.json")
        return cls(config=config, config_new=config_new, settings=load_settings_function(), path=project_path)

    @validate_call
    def get_config_path(self) -> Path:
        """Get the path to the project configuration file.

        Returns:
            The path to the project configuration file.
        """
        return self.path / "config.json"

    @staticmethod
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
