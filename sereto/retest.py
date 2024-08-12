import shutil
from copy import deepcopy

from pydantic import validate_call

from sereto.config import write_config
from sereto.models.report import Report
from sereto.models.settings import Settings


@validate_call
def add_retest(report: Report, settings: Settings) -> None:
    last_cfg = report.config.at_version(version=report.config.last_version())
    report_path = report.get_path(dir_subtree=settings.reports_path)

    # Copy last version's config to the updates section
    retest_cfg = deepcopy(last_cfg)
    retest_cfg.report_version = last_cfg.report_version.next_major_version()
    report.config.updates.append(retest_cfg)
    write_config(config=report.config, settings=settings)

    # Copy files from previous version
    old_suffix = "" if last_cfg.report_version == report.config.versions()[0] else f"_{last_cfg.report_version}"
    new_suffix = f"_{retest_cfg.report_version}"

    shutil.copy(src=report_path / f"report{old_suffix}.tex.j2", dst=report_path / f"report{new_suffix}.tex.j2")

    for target in last_cfg.targets:
        assert target.path is not None
        shutil.copy(src=target.path / f"approach{old_suffix}.tex.j2", dst=target.path / f"approach{new_suffix}.tex.j2")
        shutil.copy(src=target.path / f"scope{old_suffix}.tex.j2", dst=target.path / f"scope{new_suffix}.tex.j2")
        shutil.copy(src=target.path / f"target{old_suffix}.tex.j2", dst=target.path / f"target{new_suffix}.tex.j2")

        # TODO: Findings
