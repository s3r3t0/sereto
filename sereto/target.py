from dataclasses import dataclass
from textwrap import dedent
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
    path: DirectoryPath
    version: ProjectVersion

    @classmethod
    @validate_call
    def load(cls, data: TargetModel, path: DirectoryPath, version: ProjectVersion) -> Self:
        return cls(
            data=data,
            findings=Findings.load_from(path),
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

        # Create "findings.yaml"
        (target_path / "findings.yaml").write_text(
            dedent(
                """
                ############################################################
                #    Select findings you want to include in the report     #
                #----------------------------------------------------------#
                #  report_include:                                         #
                #  - name: "Group Finding"                                 #
                #    findings:                                             #
                #    - "finding_one"                                       #
                #    - "finding_two"                                       #
                #                                                          #
                #  - name: "Standalone Finding"                            #
                #    findings:                                             #
                #    - "standalone_finding"                                #
                ############################################################

                report_include: []
                """
            )
        )

        return cls.load(data=data, path=target_path, version=version)

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
    target: TargetModel, config: "Config", version: ProjectVersion, target_ix: int, project_path: DirectoryPath
) -> str:
    """Render selected target (top-level document) to TeX format."""
    assert target.path is not None

    cfg = config.at_version(version)

    # Construct path to target template
    template = project_path / "layouts/target.tex.j2"
    if not template.is_file():
        raise SeretoPathError(f"template not found: '{template}'")

    # Make shallow dict - values remain objects on which we can call their methods in Jinja
    cfg_model = cfg.to_model()
    cfg_dict = {key: getattr(cfg_model, key) for key in cfg_model.model_dump()}

    # Render Jinja2 template
    target_generator = render_jinja2(
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
            "c": cfg,
            "config": config,
            "version": version,
            "project_path": project_path,
            **cfg_dict,
        },
    )

    return "".join(target_generator)
