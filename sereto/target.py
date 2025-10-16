from collections.abc import Iterable
from dataclasses import dataclass
from typing import Self

from pydantic import DirectoryPath, validate_call

from sereto.cli.utils import Console
from sereto.finding import Findings
from sereto.models.locator import LocatorModel
from sereto.models.target import TargetModel
from sereto.models.version import ProjectVersion
from sereto.utils import copy_skel


@dataclass
class Target:
    data: TargetModel
    findings: Findings
    path: DirectoryPath
    version: ProjectVersion

    @classmethod
    @validate_call
    def load(cls, data: TargetModel, path: DirectoryPath, version: ProjectVersion, templates: DirectoryPath) -> Self:
        return cls(
            data=data,
            findings=Findings.load_from(target_dir=path, target_locators=data.locators, templates=templates),
            path=path,
            version=version,
        )

    @classmethod
    @validate_call
    def new(
        cls, data: TargetModel, project_path: DirectoryPath, templates: DirectoryPath, version: ProjectVersion
    ) -> Self:
        target_path = project_path / (data.uname + version.path_suffix)

        Console().log(f"Creating target directory: '{target_path}'")
        target_path.mkdir()

        category_templates = templates / "categories" / data.category

        if (category_templates / "skel").is_dir():
            Console().log(f"""Populating new target directory from: '{category_templates / "skel"}'""")
            copy_skel(templates=category_templates, dst=target_path)
        else:
            Console().log(f"No 'skel' directory found: '{category_templates}'")

        return cls.load(data=data, path=target_path, version=version, templates=templates)

    @validate_call
    def to_model(self) -> TargetModel:
        return self.data

    @property
    def uname(self) -> str:
        """Unique name for the target instance.

        Returns:
            The unique name of the target.
        """
        return self.data.uname + self.version.path_suffix

    @validate_call
    def filter_locators(self, type: str | Iterable[str]) -> list[LocatorModel]:
        """Filter locators by type.

        Args:
            type: The type of locators to filter by. Can be a single type or an iterable of types.

        Returns:
            A list of locators of the specified type.
        """
        type = [type] if isinstance(type, str) else list(type)
        return [loc for loc in self.data.locators if loc.type in type]
