# import shutil
# from copy import deepcopy

from pydantic import validate_call

# from sereto.models.finding import FindingsConfigModel
from sereto.project import Project

# from sereto.utils import YAML


@validate_call
def add_retest(project: Project) -> None:
    ...
    # last_version = project.config.last_version
    # retest_version = last_version.next_major_version()

    # # Duplicate last version config
    # last_config = deepcopy(project.config.last_config)
    # last_config.version_description = "Retest"

    # project.config.add_version_config(version=retest_version, config=last_config.to_model()).save()

    # # Update project files
    # old_suffix = last_version.path_suffix
    # new_suffix = retest_version.path_suffix

    # for file in ["report", "sow"]:
    #     shutil.copy(src=project.path / f"{file}{old_suffix}.tex.j2", dst=project.path / f"{file}{new_suffix}.tex.j2")

    # for target in project.config.at_version(last_version).targets:
    #     for file in ["approach", "scope", "target"]:
    #         shutil.copy(src=target.path / f"{file}{old_suffix}.tex.j2",
    #                     dst=target.path / f"{file}{new_suffix}.tex.j2")

    #     findings_path = target.path / "findings.yaml"
    #     findings = YAML.load(findings_path)
    #     fc = FindingsConfigModel.from_yaml(file=target.path / "findings.yaml")

    #     # Create new version of each included finding
    #     for finding in fc.included_findings():
    #         finding_dir = target.path / "findings" / finding.path_name
    #         shutil.copy(
    #             src=finding_dir / f"{finding.path_name}{old_suffix}.{finding.format.value}.j2",
    #             dst=finding_dir / f"{finding.path_name}{new_suffix}.{finding.format.value}.j2",
    #         )

    #         # Update findings.yaml
    #         # select the specific finding
    #         yaml_finding = [f for f in findings["findings"] if f["path_name"] == finding.path_name]
    #         assert len(yaml_finding) == 1
    #         yaml_finding = yaml_finding[0]

    #         # set risk for the new version same as the last one
    #         if str(retest_version) not in yaml_finding["risks"]:  # type: ignore[call-overload]
    #             yaml_finding["risks"][str(retest_version)] = finding.risks[last_version].value

    #     # Write updated findings.yaml
    #     with findings_path.open(mode="w", encoding="utf-8") as f:
    #         YAML.dump(findings, f)
