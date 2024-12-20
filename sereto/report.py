import importlib.metadata
from pathlib import Path

from pydantic import validate_call

from sereto.cli.utils import Console
from sereto.exceptions import SeretoPathError
from sereto.jinja import render_jinja2
from sereto.models.config import Config, VersionConfig
from sereto.models.project import Project
from sereto.models.settings import Settings
from sereto.models.version import ProjectVersion, SeretoVersion
from sereto.project import copy_skel
from sereto.types import TypeProjectId


@validate_call
def new_report(settings: Settings, id: TypeProjectId, name: str) -> None:
    """Generates a new report with the specified ID.

    Args:
        settings: Global settings.
        id: The ID of the new report. This should be a string that uniquely identifies the report.
        name: The name of the new report.

    Raises:
        SeretoValueError: If a report with the specified ID already exists in the `reports` directory.
    """
    Console().log(f"Generating a new report with ID {id!r}")

    if (new_path := (settings.reports_path / id)).exists():
        raise SeretoPathError("report with specified ID already exists")
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

    Console().log("Copy report skeleton")
    copy_skel(templates=settings.templates_path, dst=new_path)

    config_path: Path = new_path / "config.json"
    Console().log(f"Writing the config '{config_path}'")
    with config_path.open("w", encoding="utf-8") as f:
        f.write(cfg.model_dump_json(indent=2))


@validate_call
def render_report_to_tex(project: Project, version: ProjectVersion) -> str:
    """Render the report (top-level document) to TeX format."""
    cfg = project.config.at_version(version=version)

    # Construct path to report template
    template = project.path / "layouts/report.tex.j2"
    if not template.is_file():
        raise SeretoPathError(f"template not found: '{template}'")

    # Make shallow dict - values remain objects on which we can call their methods in Jinja
    cfg_dict = {key: getattr(cfg, key) for key in cfg.model_dump()}

    # Render Jinja2 template
    report_generator = render_jinja2(
        templates=[
            project.path / "layouts/generated",
            project.path / "layouts",
            project.path / "includes",
            project.path,
        ],
        file=template,
        vars={"c": cfg, "config": project.config, "version": version, "report_path": project.path, **cfg_dict},
    )

    return "".join(report_generator)
