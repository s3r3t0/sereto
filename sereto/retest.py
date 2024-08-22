import shutil
from copy import deepcopy

from pydantic import validate_call

from sereto.config import write_config
from sereto.models.finding import FindingsConfig
from sereto.models.report import Report
from sereto.models.settings import Settings
from sereto.utils import YAML


@validate_call
def add_retest(report: Report, settings: Settings) -> None:
    last_cfg = report.config.at_version(version=report.config.last_version())
    report_path = Report.get_path(dir_subtree=settings.reports_path)

    # Copy last version's config to the updates section
    retest_cfg = deepcopy(last_cfg)
    retest_cfg.report_version = last_cfg.report_version.next_major_version()
    report.config.updates.append(retest_cfg)
    write_config(config=report.config, settings=settings)

    old_suffix = last_cfg.report_version.path_suffix
    new_suffix = retest_cfg.report_version.path_suffix

    # Copy files from previous version
    copy_report_files = ["report", "sow"]
    for file in copy_report_files:
        shutil.copy(src=report_path / f"{file}{old_suffix}.tex.j2", dst=report_path / f"{file}{new_suffix}.tex.j2")

    for target in last_cfg.targets:
        assert target.path is not None

        copy_target_files = ["approach", "scope", "target"]

        for file in copy_target_files:
            shutil.copy(src=target.path / f"{file}{old_suffix}.tex.j2", dst=target.path / f"{file}{new_suffix}.tex.j2")

        findings_path = target.path / "findings.yaml"
        findings = YAML.load(findings_path)
        fc = FindingsConfig.from_yaml_file(filepath=target.path / "findings.yaml")

        # Create new version of each included finding
        for finding in fc.included_findings():
            finding_dir = target.path / "findings" / finding.path_name
            shutil.copy(
                src=finding_dir / f"{finding.path_name}{old_suffix}.{finding.format.value}.j2",
                dst=finding_dir / f"{finding.path_name}{new_suffix}.{finding.format.value}.j2",
            )

            # Update findings.yaml
            # select the specific finding
            yaml_finding = [f for f in findings["findings"] if f["path_name"] == finding.path_name]
            assert len(yaml_finding) == 1
            yaml_finding = yaml_finding[0]

            # set risk for the new version same as the last one
            if str(retest_cfg.report_version) not in yaml_finding["risks"]:  # type: ignore[call-overload]
                yaml_finding["risks"][str(retest_cfg.report_version)] = finding.risks[last_cfg.report_version].value  # type: ignore[call-overload]

        # Write updated findings.yaml
        with findings_path.open(mode="w", encoding="utf-8") as f:
            YAML.dump(findings, f)
