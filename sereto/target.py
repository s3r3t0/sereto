from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from pydantic import DirectoryPath, validate_call

from sereto.cli.utils import Console
from sereto.exceptions import SeretoPathError
from sereto.finding import Findings
from sereto.jinja import render_jinja2
from sereto.models.target import TargetModel
from sereto.models.version import ProjectVersion
from sereto.utils import copy_skel

if TYPE_CHECKING:
    from sereto.config import Config


@dataclass
class Target:
    data: TargetModel
    findings: Findings
    locators: list[str]
    path: DirectoryPath
    version: ProjectVersion

    @classmethod
    @validate_call
    def load(cls, data: TargetModel, path: DirectoryPath, version: ProjectVersion, templates: DirectoryPath) -> Self:
        return cls(
            data=data,
            findings=Findings.load_from(target_dir=path, target_locators=data.locators, templates=templates),
            locators=data.locators,
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


def render_target_to_tex(
    target: Target, config: "Config", version: ProjectVersion, target_ix: int, project_path: DirectoryPath
) -> str:
    """Render selected target (top-level document) to TeX format."""
    # Construct path to target template
    template = project_path / "layouts/target.tex.j2"
    if not template.is_file():
        raise SeretoPathError(f"template not found: '{template}'")

    # Render Jinja2 template
    return render_jinja2(
        templates=[
            project_path / "layouts/generated",
            project_path / "layouts",
            project_path / "includes",
            project_path,
        ],
        file=template,
        vars={
            "target": target,
            "target_index": target_ix,
            "c": config.at_version(version),
            "config": config,
            "version": version,
            "project_path": project_path,
        },
    )
