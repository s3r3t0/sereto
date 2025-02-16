import importlib.metadata
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from click import get_current_context
from pydantic import DirectoryPath, validate_call
from typing_extensions import ParamSpec

from sereto.cli.utils import Console
from sereto.config import Config, VersionConfig
from sereto.exceptions import SeretoPathError
from sereto.models.project import Project
from sereto.models.version import ProjectVersion, SeretoVersion
from sereto.plot import risks_plot
from sereto.types import TypeProjectId
from sereto.utils import copy_skel

P = ParamSpec("P")
R = TypeVar("R")


def load_project(f: Callable[P, R]) -> Callable[P, R]:
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
    for target in project.config_new.at_version(version=version).targets:
        if not (target_dir := build_dir / target.uname).is_dir():
            target_dir.mkdir(parents=True)


@validate_call
def project_create_missing(project: Project, version: ProjectVersion) -> None:
    """Creates missing content in the project.

    Args:
        project: Project's representation.
        version: The version of the project.
    """
    cfg = project.config_new.at_version(version=version)

    # Initialize the build directory
    init_build_dir(project=project, version=version)

    # Make sure that "layouts/generated" directory exists
    if not (layouts_generated := project.path / "layouts" / "generated").is_dir():
        layouts_generated.mkdir(parents=True)

    for target in cfg.targets:
        # Generate risks plot for the target
        risks_plot(risks=target.findings.risks, path=project.path / ".build" / target.uname / "risks.png")


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
            ),
        },
        path=config_path,
    ).save()
