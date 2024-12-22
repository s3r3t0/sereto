import importlib.metadata
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from shutil import copy2, copytree
from typing import TypeVar

from click import get_current_context
from pydantic import DirectoryPath, validate_call
from typing_extensions import ParamSpec

from sereto.cli.utils import Console
from sereto.exceptions import SeretoPathError
from sereto.models.config import Config, VersionConfig
from sereto.models.project import Project
from sereto.models.version import ProjectVersion, SeretoVersion
from sereto.plot import risks_plot
from sereto.target import create_findings_config, get_risks
from sereto.types import TypeProjectId

P = ParamSpec("P")
R = TypeVar("R")


def load_project(f: Callable[..., R]) -> Callable[..., R]:
    """Decorator which loads the `Project` from filesystem."""

    @wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        project = Project.load_from()
        return get_current_context().invoke(f, project, *args, **kwargs)

    return wrapper


@validate_call
def init_build_dir(project: Project, version: ProjectVersion) -> None:
    """Initialize the build directory."""
    # Create ".build" directory
    if not (build_dir := project.path / ".build").is_dir():
        build_dir.mkdir(parents=True)

    # Create target directories
    for target in project.config.at_version(version=version).targets:
        if not (target_dir := build_dir / target.uname).is_dir():
            target_dir.mkdir(parents=True)


@validate_call
def copy_skel(templates: DirectoryPath, dst: DirectoryPath, overwrite: bool = False) -> None:
    """Copy the content of a templates `skel` directory to a destination directory.

    A `skel` directory is a directory that contains a set of files and directories that can be used as a template
    for creating new projects. This function copies the contents of the `skel` directory located at
    the path specified by `templates` to the destination directory specified by `dst`.

    Args:
        templates: The path to the directory containing the `skel` directory.
        dst: The destination directory to copy the `skel` directory contents to.
        overwrite: Whether to allow overwriting of existing files in the destination directory.
            If `True`, existing files will be overwritten. If `False` (default), a `SeretoPathError` will be raised
            if the destination already exists.

    Raises:
        SeretoPathError: If the destination directory already exists and `overwrite` is `False`.
    """
    skel_path: Path = templates / "skel"
    Console().log(f"Copying 'skel' directory: '{skel_path}' -> '{dst}'")

    for item in skel_path.iterdir():
        dst_item: Path = dst / (item.relative_to(skel_path))
        if not overwrite and dst_item.exists():
            raise SeretoPathError("Destination already exists")
        if item.is_file():
            Console().log(f" [green]+[/green] copy file: '{item.relative_to(skel_path)}'")
            copy2(item, dst_item, follow_symlinks=False)
        if item.is_dir():
            Console().log(f" [green]+[/green] copy dir: '{item.relative_to(skel_path)}'")
            copytree(item, dst_item, dirs_exist_ok=overwrite)


@validate_call
def project_create_missing(project: Project, version: ProjectVersion) -> None:
    """Creates missing target directories from config.

    This function creates any missing target directories and populates them with content of the "skel" directory from
    templates.

    Args:
        project: Project's representation.
        version: The version of the project.
    """
    cfg = project.config.at_version(version=version)

    # Initialize the build directory
    init_build_dir(project=project, version=version)

    # Make sure that "layouts/generated" directory exists
    if not (layouts_generated := project.path / "layouts" / "generated").is_dir():
        layouts_generated.mkdir(parents=True)

    for target in cfg.targets:
        assert target.path is not None
        category_templates = project.settings.templates_path / "categories" / target.category

        # Create target directory if missing
        if not target.path.is_dir():
            Console().log(f"Target directory not found, creating: '{target.path}'")
            target.path.mkdir()
            if (category_templates / "skel").is_dir():
                Console().log(f"""Populating new target directory from: '{category_templates / "skel"}'""")
                copy_skel(templates=category_templates, dst=target.path)
            else:
                Console().log(f"No 'skel' directory found: '{category_templates}'")

            # Dynamically compose "findings.yaml"
            create_findings_config(target=target, project=project, templates=category_templates / "findings")

        # Generate risks plot for the target
        risks = get_risks(target=target, version=version)
        risks_plot(risks=risks, path=project.path / ".build" / target.uname / "risks.png")


@validate_call
def new_project(projects_path: DirectoryPath, templates_path: DirectoryPath, id: TypeProjectId, name: str) -> None:
    """Generates a new project with the specified ID.

    Args:
        projects_path: The path to the projects directory.
        templates_path: The path to the templates directory.
        id: The ID of the new project. This should be a string that uniquely identifies the project.
        name: The name of the new project.

    Raises:
        SeretoValueError: If a project with the specified ID already exists in the `projects` directory.
    """
    Console().log(f"Generating a new project with ID {id!r}")

    if (new_path := projects_path / id).exists():
        raise SeretoPathError("project with specified ID already exists")
    else:
        new_path.mkdir()

    sereto_ver = importlib.metadata.version("sereto")

    cfg = Config(
        sereto_version=SeretoVersion.from_str(sereto_ver),
        version_configs={
            ProjectVersion.from_str("v1.0"): VersionConfig(
                id=id,
                name=name,
                version_description="Initial",
            ),
        },
    )

    Console().log("Copy project skeleton")
    copy_skel(templates=templates_path, dst=new_path)

    config_path: Path = new_path / "config.json"
    Console().log(f"Writing the config '{config_path}'")
    with config_path.open("w", encoding="utf-8") as f:
        f.write(cfg.model_dump_json(indent=2))
