from sereto.models.finding import FindingGroup
from sereto.models.report import Report
from sereto.models.settings import Settings
from sereto.models.target import Target
from sereto.models.version import ReportVersion


def render_sow_cleanup(report: Report, settings: Settings, version: ReportVersion) -> None:
    """
    Removes the 'sow.tex' file associated with the given report.

    Args:
        report: The report object.
        settings: The settings object.
        version: The report version object.

    Returns:
        None
    """
    report_path = Report.get_path(dir_subtree=settings.reports_path)
    sow_tex_path = report_path / f"sow{version.path_suffix}.tex"
    sow_tex_path.unlink()


def render_report_cleanup(report: Report, settings: Settings, version: ReportVersion) -> None:
    """
    Removes the report.tex file associated with the given report.

    Args:
        report: The report object.
        settings: The settings object.
        version: The report version object.

    Returns:
        None
    """
    report_path = Report.get_path(dir_subtree=settings.reports_path)
    report_tex_path = report_path / f"report{version.path_suffix}.tex"
    report_tex_path.unlink()


def render_target_cleanup(target: Target, report: Report, settings: Settings) -> None:
    """
    Cleans up the rendered target by deleting the corresponding .tex file.

    Args:
        target: The target to be cleaned up.
        report: The report containing the target.
        settings: The settings for the cleanup process.

    Returns:
        None
    """
    report_path = Report.get_path(dir_subtree=settings.reports_path)
    target_tex_path = report_path / f"{target.uname}.tex"
    target_tex_path.unlink()


def render_finding_group_cleanup(
    finding_group: FindingGroup, target: Target, report: Report, settings: Settings
) -> None:
    """
    Renders the cleanup for a finding group in the specified report.

    Args:
        finding_group: The finding group to render the cleanup for.
        target: The target associated with the finding group.
        report: The report to render the cleanup in.
        settings: The settings for rendering the report.

    Returns:
        None
    """
    report_path = Report.get_path(dir_subtree=settings.reports_path)
    finding_group_tex_path = report_path / f"{target.uname}_{finding_group.uname}.tex"
    finding_group_tex_path.unlink()
