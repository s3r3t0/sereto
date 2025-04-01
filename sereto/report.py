from pydantic import DirectoryPath, validate_call

from sereto.config import Config
from sereto.exceptions import SeretoPathError
from sereto.jinja import render_jinja2
from sereto.models.version import ProjectVersion


@validate_call
def render_report_to_tex(project_path: DirectoryPath, config: Config, version: ProjectVersion) -> str:
    """Render the report (top-level document) to TeX format."""
    # Construct path to report template
    template = project_path / "layouts/report.tex.j2"
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
            "c": config.at_version(version=version),
            "config": config,
            "version": version,
            "project_path": project_path,
        },
    )
