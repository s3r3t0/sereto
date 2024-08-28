from pathlib import Path

from pydantic import validate_call

from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.base import SeretoBaseModel
from sereto.models.config import Config
from sereto.models.settings import Settings
from sereto.models.target import Target
from sereto.models.version import ReportVersion


class Report(SeretoBaseModel):
    config: Config

    @staticmethod
    @validate_call
    def get_path(dir_subtree: Path = Path("/")) -> Path:
        for dir in [Path.cwd()] + list(Path.cwd().parents):
            if dir.is_relative_to(dir_subtree):
                if Report.is_report_dir(dir):
                    return dir
            else:
                break

        raise SeretoPathError("not inside report's (sub)directory")

    @staticmethod
    @validate_call
    def get_config_path(dir_subtree: Path = Path("/")) -> Path:
        return Report.get_path(dir_subtree=dir_subtree) / "config.json"

    @staticmethod
    @validate_call
    def is_report_dir(path: Path) -> bool:
        """Check if the provided path is a root directory of a report.

        A report directory contains at least `.sereto` and `config.json` files.

        Args:
            path: The path to examine.

        Returns:
            True if the path is a report directory, False otherwise.
        """
        return (path / ".sereto").is_file() and (path / "config.json").is_file()

    @validate_call
    def load_runtime_vars(self, settings: Settings) -> None:
        """Get the config enriched with additional parameters like paths and findings."""
        report_path = self.get_path(dir_subtree=settings.reports_path)

        for cfg in [self.config] + self.config.updates:
            for target in cfg.targets:
                target.path = report_path / target.uname

    @validate_call
    def select_target(
        self,
        settings: Settings,
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
        if selector in settings.categories:
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
