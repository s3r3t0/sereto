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


# -------------------- end report_sent_date property tests --------------------

# --------------- VersionConfig.total_open_risks property tests ---------------


class _StubRisks:
    def __init__(self, sum_open: int):
        self.sum_open = sum_open


class _StubFindings:
    def __init__(self, sum_open: int):
        self.risks = _StubRisks(sum_open)
        # noise attributes that must not affect total_open_risks
        self.sum_closed = 999999  # should be ignored


class _StubTarget:
    def __init__(self, sum_open: int):
        self.findings = _StubFindings(sum_open)


def make_version_config_with_open_risks(open_counts: list[int]) -> VersionConfig:
    return VersionConfig(
        version=ProjectVersion.from_str("v1.0"),
        id="PRJ",
        name="Project",
        version_description="Desc",
        risk_due_dates={},
        targets=[_StubTarget(c) for c in open_counts],
        dates=[],
        people=[],
    )


def test_total_open_risks_no_targets():
    vc = make_version_config_with_open_risks([])
    assert vc.total_open_risks == 0


def test_total_open_risks_single_zero():
    vc = make_version_config_with_open_risks([0])
    assert vc.total_open_risks == 0


def test_total_open_risks_single_nonzero():
    vc = make_version_config_with_open_risks([7])
    assert vc.total_open_risks == 7


def test_total_open_risks_multiple_targets():
    vc = make_version_config_with_open_risks([1, 3, 5, 0, 2])
    assert vc.total_open_risks == 11


def test_total_open_risks_large_numbers():
    counts = [10_000, 250_000, 1_000_000]
    vc = make_version_config_with_open_risks(counts)
    assert vc.total_open_risks == sum(counts)


def test_total_open_risks_mutation_reflected():
    vc = make_version_config_with_open_risks([2, 3])
    assert vc.total_open_risks == 5
    # mutate underlying object
    vc.targets[0].findings.risks.sum_open = 10
    assert vc.total_open_risks == 13
    vc.targets[1].findings.risks.sum_open = 0
    assert vc.total_open_risks == 10


def test_total_open_risks_add_target_manually():
    vc = make_version_config_with_open_risks([4, 6])
    assert vc.total_open_risks == 10
    vc.targets.append(_StubTarget(9))  # bypass add_target to avoid pydantic validation
    assert vc.total_open_risks == 19


def test_total_open_risks_remove_target():
    vc = make_version_config_with_open_risks([5, 8, 1])
    assert vc.total_open_risks == 14
    del vc.targets[1]
    assert vc.total_open_risks == 6


def test_total_open_risks_order_irrelevant():
    counts_a = [4, 1, 7, 3]
    counts_b = list(reversed(counts_a))
    vc_a = make_version_config_with_open_risks(counts_a)
    vc_b = make_version_config_with_open_risks(counts_b)
    assert vc_a.total_open_risks == vc_b.total_open_risks == sum(counts_a)


def test_total_open_risks_ignores_non_sum_open_fields():
    vc = make_version_config_with_open_risks([2])
    # Add misleading attribute at target level
    vc.targets[0].findings.sum_open = 999  # should not be used (property drills to findings.risks.sum_open)
    assert vc.total_open_risks == 2


def test_total_open_risks_not_cached():
    vc = make_version_config_with_open_risks([1])
    first = vc.total_open_risks
    vc.targets[0].findings.risks.sum_open = 5
    second = vc.total_open_risks
    assert first == 1 and second == 5


@pytest.mark.parametrize(
    "counts,expected",
    [
        ([], 0),
        ([0], 0),
        ([1], 1),
        ([0, 0, 0], 0),
        ([1, 2, 3], 6),
        ([10, 0, 5, 5], 20),
    ],
)
def test_total_open_risks_parametrized(counts, expected):
    vc = make_version_config_with_open_risks(counts)
    assert vc.total_open_risks == expected


def test_total_open_risks_does_not_mutate_targets():
    counts = [1, 2, 3]
    vc = make_version_config_with_open_risks(counts)
    before_ids = [id(t) for t in vc.targets]
    _ = vc.total_open_risks
    after_ids = [id(t) for t in vc.targets]
    assert before_ids == after_ids
    assert [t.findings.risks.sum_open for t in vc.targets] == counts


# ------------------ end total_open_risks property tests ------------------
