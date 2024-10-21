from pathlib import Path
from typing import Self

from pydantic import DirectoryPath, validate_call

from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.base import SeretoBaseModel
from sereto.models.config import Config
from sereto.models.settings import Settings
from sereto.models.target import Target
from sereto.models.version import ReportVersion
from sereto.settings import load_settings_function


@validate_call
def get_project_path_from_dir(dir: DirectoryPath | None = None, dir_subtree: DirectoryPath = Path("/")) -> Path:
    """Get the path to the report project directory.

    Start the search from the 'dir' directory and go up the directory tree until the report directory is
    found or 'dir_subtree' is reached.

    If you have an instance of the `Project` class, you should use the `get_path_from_dir` method instead.

    Args:
        dir: The directory to start the search from. Defaults to the current working directory.
        dir_subtree: The directory to stop the search at. Defaults to the root directory.

    Raises:
        SeretoPathError: If the current working directory is not inside the report's (sub)directory.

    Returns:
        The path to the report directory.
    """
    if dir is None:
        dir = Path.cwd()

    # start from the current working directory and go up the directory tree
    for d in [dir] + list(dir.parents):
        # if the current directory is inside the subtree
        if d.is_relative_to(dir_subtree):
            # if the current directory is a report directory
            if Project.is_report_dir(d):
                return d
        else:
            # stop the search before leaving the subtree
            break

    raise SeretoPathError("not inside report's (sub)directory")


@validate_call
def get_config_path(dir_subtree: DirectoryPath = Path("/")) -> Path:
    """Get the path to the report configuration file.

    Args:
        dir_subtree: The directory to stop the search at. Defaults to the root directory.

    Returns:
        The path to the report configuration file.
    """
    return get_project_path_from_dir(dir_subtree=dir_subtree) / "config.json"


class Project(SeretoBaseModel):
    config: Config
    settings: Settings

    @validate_call
    def get_path_from_dir(self, dir: DirectoryPath | None = None) -> Path:
        """Get the path to the report directory.

        Start from the 'dir' directory and go up the directory tree until the report directory is found or
        we would leave 'dir_subtree'.

        Args:
            dir: The directory to start the search from. Defaults to the current working directory.

        Raises:
            SeretoPathError: If the current working directory is not inside the report's (sub)directory.

        Returns:
            The path to the report directory.
        """
        return get_project_path_from_dir(
            dir=dir if dir is not None else Path.cwd(), dir_subtree=self.settings.reports_path
        )

    @staticmethod
    def load_from(path: DirectoryPath | None = None) -> "Project":
        """Load the project from the provided path.

        Args:
            path: The path to the report (sub)directory. Defaults to the current working directory.

        Returns:
            The project object.
        """
        settings = load_settings_function()
        project_path = get_project_path_from_dir(
            dir=path if path is not None else Path.cwd(), dir_subtree=settings.reports_path
        )
        config = Config.load_from(file=project_path / "config.json")
        return Project(config=config, settings=load_settings_function()).load_runtime_vars()

    @validate_call
    def get_config_path(self) -> Path:
        """Get the path to the report configuration file.

        Returns:
            The path to the report configuration file.
        """
        return get_config_path(dir_subtree=self.settings.reports_path)

    @staticmethod
    @validate_call
    def is_report_dir(path: DirectoryPath) -> bool:
        """Check if the provided path is a root directory of a report.

        A report directory contains at least `.sereto` and `config.json` files.

        Args:
            path: The path to examine.

        Returns:
            True if the path is a report directory, False otherwise.
        """
        return (path / ".sereto").is_file() and (path / "config.json").is_file()

    @validate_call
    def load_runtime_vars(self) -> Self:
        """Get the config enriched with additional parameters like paths and findings."""
        project_path = self.get_path_from_dir()

        for cfg in [self.config] + self.config.updates:
            for target in cfg.targets:
                target.path = project_path / target.uname

        return self

    @validate_call
    def select_target(
        self,
        version: ReportVersion | None = None,
        selector: int | str | None = None,
    ) -> Target:
        if version is None:
            version = self.config.last_version()

        cfg = self.config.at_version(version)

        # only single target present
        if selector is None:
            if len(cfg.targets) != 1:
                raise SeretoValueError(
                    f"cannot select target; no selector provided and there are {len(cfg.targets)} targets present"
                )
            return cfg.targets[0]

        # by index
        if isinstance(selector, int) or selector.isnumeric():
            ix = selector - 1 if isinstance(selector, int) else int(selector) - 1
            if not (0 <= ix <= len(cfg.targets) - 1):
                raise SeretoValueError("target index out of range")
            return cfg.targets[ix]

        # by category
        if selector in self.settings.categories:
            targets = [t for t in cfg.targets if t.category == selector]
            match len(targets):
                case 0:
                    raise SeretoValueError(f"category {selector!r} does not contain any target")
                case 1:
                    return targets[0]
                case _:
                    raise SeretoValueError(f"category {selector!r} contains multiple targets, use uname when querying")

        # by uname
        targets = [t for t in cfg.targets if t.uname == selector]
        if len(targets) != 1:
            raise SeretoValueError(f"cannot find target with uname {selector!r}")
        return targets[0]