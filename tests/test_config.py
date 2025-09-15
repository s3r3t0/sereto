import pytest

from sereto.config import VersionConfig
from sereto.models.date import Date, DateRange, DateType, SeretoDate
from sereto.models.version import ProjectVersion

# --------------- VersionConfig.report_sent_date property tests ---------------


def make_version_config(dates: list[Date]) -> VersionConfig:
    return VersionConfig(
        version=ProjectVersion.from_str("v1.0"),
        id="PRJ",
        name="Project",
        version_description="Desc",
        risk_due_dates={},  # not needed for report_sent_date property
        targets=[],
        dates=dates,
        people=[],
    )


def test_report_sent_date_no_dates():
    vc = make_version_config([])
    assert vc.report_sent_date is None


def test_report_sent_date_only_review():
    d = Date(type=DateType.review, date=SeretoDate("10-Jan-2024"))
    vc = make_version_config([d])
    assert vc.report_sent_date == SeretoDate("10-Jan-2024")


def test_report_sent_date_only_report_sent():
    d = Date(type=DateType.report_sent, date=SeretoDate("15-Feb-2024"))
    vc = make_version_config([d])
    assert vc.report_sent_date == SeretoDate("15-Feb-2024")


def test_report_sent_date_only_pentest_ongoing_range():
    r = Date(
        type=DateType.pentest_ongoing,
        date=DateRange(start=SeretoDate("01-Mar-2024"), end=SeretoDate("05-Mar-2024")),
    )
    vc = make_version_config([r])
    # For a range the end date should be used
    assert vc.report_sent_date == SeretoDate("05-Mar-2024")


def test_report_sent_date_review_after_pentest_range():
    pentest = Date(
        type=DateType.pentest_ongoing,
        date=DateRange(start=SeretoDate("01-Apr-2024"), end=SeretoDate("05-Apr-2024")),
    )
    review = Date(type=DateType.review, date=SeretoDate("07-Apr-2024"))
    vc = make_version_config([pentest, review])
    assert vc.report_sent_date == SeretoDate("07-Apr-2024")


def test_report_sent_date_report_sent_after_review_and_pentest():
    pentest = Date(
        type=DateType.pentest_ongoing,
        date=DateRange(start=SeretoDate("01-May-2024"), end=SeretoDate("03-May-2024")),
    )
    review = Date(type=DateType.review, date=SeretoDate("04-May-2024"))
    report_sent = Date(type=DateType.report_sent, date=SeretoDate("06-May-2024"))
    vc = make_version_config([pentest, review, report_sent])
    assert vc.report_sent_date == SeretoDate("06-May-2024")


def test_report_sent_date_multiple_reviews_picks_latest():
    review1 = Date(type=DateType.review, date=SeretoDate("10-Jun-2024"))
    review2 = Date(type=DateType.review, date=SeretoDate("12-Jun-2024"))
    vc = make_version_config([review1, review2])
    assert vc.report_sent_date == SeretoDate("12-Jun-2024")


def test_report_sent_date_multiple_pentest_ranges_picks_latest_end():
    p1 = Date(
        type=DateType.pentest_ongoing,
        date=DateRange(start=SeretoDate("01-Jul-2024"), end=SeretoDate("05-Jul-2024")),
    )
    p2 = Date(
        type=DateType.pentest_ongoing,
        date=DateRange(start=SeretoDate("10-Jul-2024"), end=SeretoDate("15-Jul-2024")),
    )
    vc = make_version_config([p1, p2])
    assert vc.report_sent_date == SeretoDate("15-Jul-2024")


def test_report_sent_date_ignores_other_types_and_finds_latest_relevant():
    sow_sent = Date(type=DateType.sow_sent, date=SeretoDate("20-Aug-2024"))
    sow_sent_2 = Date(type=DateType.sow_sent, date=SeretoDate("18-Aug-2024"))
    report_sent = Date(type=DateType.report_sent, date=SeretoDate("22-Aug-2024"))
    vc = make_version_config([sow_sent_2, sow_sent, report_sent])
    assert vc.report_sent_date == SeretoDate("22-Aug-2024")


def test_report_sent_date_no_relevant_date():
    sow_sent = Date(type=DateType.sow_sent, date=SeretoDate("20-Aug-2024"))
    sow_sent_2 = Date(type=DateType.sow_sent, date=SeretoDate("18-Aug-2024"))
    vc = make_version_config([sow_sent_2, sow_sent])
    assert vc.report_sent_date is None


def test_report_sent_date_unsorted_input():
    # Provide dates in random order to ensure chronological selection
    d1 = Date(type=DateType.review, date=SeretoDate("05-Sep-2024"))
    d2 = Date(type=DateType.report_sent, date=SeretoDate("07-Sep-2024"))
    d3 = Date(
        type=DateType.pentest_ongoing, date=DateRange(start=SeretoDate("01-Sep-2024"), end=SeretoDate("03-Sep-2024"))
    )
    vc = make_version_config([d1, d3, d2])
    assert vc.report_sent_date == SeretoDate("07-Sep-2024")


def test_report_sent_date_all_three_types_mixed():
    pentest = Date(
        type=DateType.pentest_ongoing,
        date=DateRange(start=SeretoDate("01-Nov-2024"), end=SeretoDate("04-Nov-2024")),
    )
    review = Date(type=DateType.review, date=SeretoDate("06-Nov-2024"))
    report_sent = Date(type=DateType.report_sent, date=SeretoDate("08-Nov-2024"))
    vc = make_version_config([review, pentest, report_sent])
    assert vc.report_sent_date == SeretoDate("08-Nov-2024")


def test_report_sent_is_not_last_date():
    pentest = Date(
        type=DateType.pentest_ongoing,
        date=DateRange(start=SeretoDate("01-Nov-2024"), end=SeretoDate("07-Nov-2024")),
    )
    review = Date(type=DateType.review, date=SeretoDate("05-Nov-2024"))
    report_sent = Date(type=DateType.report_sent, date=SeretoDate("05-Nov-2024"))
    vc = make_version_config([review, pentest, report_sent])
    assert vc.report_sent_date == SeretoDate("05-Nov-2024")


@pytest.mark.parametrize(
    "dates,expected",
    [
        ([], None),
        ([Date(type=DateType.review, date=SeretoDate("01-Dec-2024"))], SeretoDate("01-Dec-2024")),
        (
            [
                Date(type=DateType.review, date=SeretoDate("01-Dec-2024")),
                Date(type=DateType.report_sent, date=SeretoDate("05-Dec-2024")),
            ],
            SeretoDate("05-Dec-2024"),
        ),
        (
            [
                Date(
                    type=DateType.pentest_ongoing,
                    date=DateRange(start=SeretoDate("01-Dec-2024"), end=SeretoDate("03-Dec-2024")),
                ),
                Date(type=DateType.review, date=SeretoDate("04-Dec-2024")),
            ],
            SeretoDate("04-Dec-2024"),
        ),
        (
            [
                Date(type=DateType.review, date=SeretoDate("10-Dec-2024")),
                Date(
                    type=DateType.pentest_ongoing,
                    date=DateRange(start=SeretoDate("05-Dec-2024"), end=SeretoDate("12-Dec-2024")),
                ),
            ],
            SeretoDate("12-Dec-2024"),
        ),
    ],
)
def test_report_sent_date_parametrized(dates, expected):
    vc = make_version_config(dates)
    assert vc.report_sent_date == expected


def test_report_sent_date_not_mutated_on_access():
    # Accessing property should not alter underlying dates list
    d1 = Date(type=DateType.review, date=SeretoDate("01-Jan-2025"))
    d2 = Date(type=DateType.report_sent, date=SeretoDate("03-Jan-2025"))
    vc = make_version_config([d1, d2])
    before = list(vc.dates)
    _ = vc.report_sent_date
    after = list(vc.dates)
    assert before == after


def test_report_sent_date_with_many_entries():
    dates = [
        Date(type=DateType.review, date=SeretoDate("01-Feb-2025")),
        Date(type=DateType.review, date=SeretoDate("05-Feb-2025")),
        Date(
            type=DateType.pentest_ongoing,
            date=DateRange(start=SeretoDate("02-Feb-2025"), end=SeretoDate("06-Feb-2025")),
        ),
        Date(type=DateType.report_sent, date=SeretoDate("07-Feb-2025")),
        Date(
            type=DateType.pentest_ongoing,
            date=DateRange(start=SeretoDate("08-Feb-2025"), end=SeretoDate("10-Feb-2025")),
        ),
    ]
    vc = make_version_config(dates)
    assert vc.report_sent_date == SeretoDate("07-Feb-2025")


# =============== VersionConfig.report_sent_date property tests ===============
