from pydantic import validate_call

from sereto.exceptions import SeretoPathError
from sereto.jinja import render_jinja2
from sereto.models.project import Project
from sereto.models.version import ProjectVersion


@validate_call
def render_sow_to_tex(project: Project, version: ProjectVersion) -> str:
    """Render the SoW (top-level document) to TeX format."""
    cfg = project.config.at_version(version=version)

    # Construct path to SoW template
    template = project.path / "layouts/sow.tex.j2"
    if not template.is_file():
        raise SeretoPathError(f"template not found: '{template}'")

    # Make shallow dict - values remain objects on which we can call their methods in Jinja
    cfg_dict = {key: getattr(cfg, key) for key in cfg.model_dump()}

    # Render the Jinja template
    sow_generator = render_jinja2(
        templates=[
            project.path / "layouts/generated",
            project.path / "layouts",
            project.path / "includes",
            project.path,
        ],
        file=template,
        vars={"c": cfg, "config": project.config, "version": version, "project_path": project.path, **cfg_dict},
    )

    return "".join(sow_generator)