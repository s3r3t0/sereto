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

# ---------------- VersionConfig.sum_risks property tests ---------------------


class _SumRisksStub:
    """Simple Risks-like object supporting addition for testing VersionConfig.sum_risks."""

    __slots__ = ("critical", "high", "medium", "low", "info", "sum_open")

    def __init__(self, critical=0, high=0, medium=0, low=0, info=0):
        self.critical = critical
        self.high = high
        self.medium = medium
        self.low = low
        self.info = info
        # emulate existing attribute accessed elsewhere (not required here, but consistent)
        self.sum_open = critical + high + medium + low + info

    def __add__(self, other):
        if not isinstance(other, _SumRisksStub):
            return NotImplemented
        return _SumRisksStub(
            self.critical + other.critical,
            self.high + other.high,
            self.medium + other.medium,
            self.low + other.low,
            self.info + other.info,
        )

    def as_tuple(self):
        return (self.critical, self.high, self.medium, self.low, self.info)

    def __repr__(self):
        return f"_SumRisksStub(c={self.critical},h={self.high},m={self.medium},l={self.low},i={self.info})"


class _SumRisksFindingsStub:
    def __init__(self, risks: _SumRisksStub):
        self.risks = risks


class _SumRisksTargetStub:
    """Mimics only the attributes VersionConfig needs (findings.risks)."""

    def __init__(self, risks: _SumRisksStub):
        self.findings = _SumRisksFindingsStub(risks)


def make_version_config_with_risk_objects(risk_objs: list[_SumRisksStub]) -> VersionConfig:
    return VersionConfig(
        version=ProjectVersion.from_str("v1.0"),
        id="PRJ",
        name="Project",
        version_description="Desc",
        risk_due_dates={},
        targets=[_SumRisksTargetStub(r) for r in risk_objs],
        dates=[],
        people=[],
    )


def _aggregate_manual(risk_objs: list[_SumRisksStub]) -> tuple[int, int, int, int, int]:
    return tuple(sum(getattr(r, attr) for r in risk_objs) for attr in ("critical", "high", "medium", "low", "info"))


def test_sum_risks_single_target_identity():
    r = _SumRisksStub(critical=1, high=2, medium=3, low=4, info=5)
    vc = make_version_config_with_risk_objects([r])
    result = vc.sum_risks
    assert result is r  # reduce should return the single element unchanged
    assert result.as_tuple() == (1, 2, 3, 4, 5)


def test_sum_risks_two_targets_addition():
    a = _SumRisksStub(1, 0, 2, 0, 1)
    b = _SumRisksStub(0, 3, 1, 4, 0)
    vc = make_version_config_with_risk_objects([a, b])
    res = vc.sum_risks
    # Should be a new object (since a + b creates new)
    assert res is not a and res is not b
    assert res.as_tuple() == (1, 3, 3, 4, 1)


def test_sum_risks_multiple_targets_order_independent():
    objs = [
        _SumRisksStub(1, 2, 0, 0, 1),
        _SumRisksStub(0, 1, 3, 1, 0),
        _SumRisksStub(2, 0, 1, 4, 2),
    ]
    vc_a = make_version_config_with_risk_objects(list(objs))
    vc_b = make_version_config_with_risk_objects(list(reversed(objs)))
    expected = _aggregate_manual(objs)
    assert vc_a.sum_risks.as_tuple() == expected
    assert vc_b.sum_risks.as_tuple() == expected


def test_sum_risks_large_numbers():
    a = _SumRisksStub(10_000, 20_000, 30_000, 40_000, 50_000)
    b = _SumRisksStub(1, 2, 3, 4, 5)
    c = _SumRisksStub(999_999, 0, 0, 0, 1)
    vc = make_version_config_with_risk_objects([a, b, c])
    res = vc.sum_risks
    assert res.as_tuple() == (
        10_000 + 1 + 999_999,
        20_000 + 2 + 0,
        30_000 + 3 + 0,
        40_000 + 4 + 0,
        50_000 + 5 + 1,
    )


def test_sum_risks_mutation_reflected_on_reaccess():
    a = _SumRisksStub(1, 1, 1, 1, 1)
    b = _SumRisksStub(2, 2, 2, 2, 2)
    vc = make_version_config_with_risk_objects([a, b])
    first = vc.sum_risks.as_tuple()
    assert first == (3, 3, 3, 3, 3)
    # mutate underlying risk object
    a.high = 10
    a.sum_open = a.critical + a.high + a.medium + a.low + a.info
    second = vc.sum_risks.as_tuple()
    assert second == (3, 12, 3, 3, 3)


def test_sum_risks_result_does_not_mutate_underlying_for_multiple():
    a = _SumRisksStub(1, 1, 1, 1, 1)
    b = _SumRisksStub(2, 2, 2, 2, 2)
    vc = make_version_config_with_risk_objects([a, b])
    res = vc.sum_risks
    # modify aggregated result
    res.critical = 999
    # underlying must remain unchanged
    assert a.critical == 1 and b.critical == 2
    # Recompute property -> unaffected by modification to previous aggregated object
    again = vc.sum_risks
    assert again.as_tuple() == (3, 3, 3, 3, 3)


def test_sum_risks_does_not_reorder_targets():
    objs = [
        _SumRisksStub(1, 0, 0, 0, 0),
        _SumRisksStub(0, 1, 0, 0, 0),
        _SumRisksStub(0, 0, 1, 0, 0),
    ]
    vc = make_version_config_with_risk_objects(objs)
    before_ids = [id(t) for t in vc.targets]
    _ = vc.sum_risks
    after_ids = [id(t) for t in vc.targets]
    assert before_ids == after_ids


def test_sum_risks_empty_returns_zero_object():
    vc = make_version_config_with_risk_objects([])
    res = vc.sum_risks  # desired: no exception
    for attr in ("critical", "high", "medium", "low", "info"):
        assert getattr(res, attr) == 0
    assert res.sum_open == 0


def test_sum_risks_empty_mutation_does_not_persist():
    vc = make_version_config_with_risk_objects([])
    first = vc.sum_risks
    # Mutate returned object (should not affect future accesses once implemented)
    if hasattr(first, "critical"):
        first.critical = 999
    second = vc.sum_risks
    # Second access should still yield zeros
    for attr in ("critical", "high", "medium", "low", "info"):
        assert getattr(second, attr) == 0


def test_sum_risks_empty_idempotent():
    vc = make_version_config_with_risk_objects([])
    a = vc.sum_risks
    b = vc.sum_risks
    # Both accesses should yield objects that (a) compare equal via attributes and
    # (b) may or may not be the same identity (implementation choice). We assert attribute equality only.
    for attr in ("critical", "high", "medium", "low", "info"):
        assert getattr(a, attr) == getattr(b, attr) == 0


@pytest.mark.parametrize(
    "risk_sets,expected",
    [
        ([(0, 0, 0, 0, 0)], (0, 0, 0, 0, 0)),
        ([(1, 2, 3, 4, 5)], (1, 2, 3, 4, 5)),
        ([(1, 0, 0, 0, 0), (0, 1, 2, 0, 3)], (1, 1, 2, 0, 3)),
        ([(2, 2, 2, 2, 2), (3, 1, 0, 4, 0), (0, 5, 1, 0, 6)], (5, 8, 3, 6, 8)),
    ],
)
def test_sum_risks_parametrized(risk_sets, expected):
    objs = [_SumRisksStub(*vals) for vals in risk_sets]
    vc = make_version_config_with_risk_objects(objs)
    assert vc.sum_risks.as_tuple() == expected


def test_sum_risks_many_targets_scaling():
    objs = [_SumRisksStub(i % 3, i % 5, i % 7, i % 11, i % 13) for i in range(1, 51)]
    vc = make_version_config_with_risk_objects(objs)
    res = vc.sum_risks.as_tuple()
    manual = _aggregate_manual(objs)
    assert res == manual


# ------------------ end sum_risks property tests ------------------

# --------------------- VersionConfig.report_name property tests ---------------------


def _make_vc_from_id_ver(proj_id: str, version_str: str) -> VersionConfig:
    return VersionConfig(
        version=ProjectVersion.from_str(version_str),
        id=proj_id,
        name="Some Name",
        version_description="Desc",
        risk_due_dates={},
        targets=[],
        dates=[],
        people=[],
    )


def test_report_name_initial_version_no_suffix():
    vc = _make_vc_from_id_ver("PRJ", "v1.0")
    assert vc.report_name == "PRJ - Report.pdf"


def test_report_name_minor_version_included():
    vc = _make_vc_from_id_ver("PRJ", "v1.1")
    assert vc.report_name == "PRJ - Report v1.1.pdf"


def test_report_name_major_version_included():
    vc = _make_vc_from_id_ver("ABC", "v2.0")
    assert vc.report_name == "ABC - Report v2.0.pdf"


def test_report_name_id_with_spaces_and_symbols():
    vc = _make_vc_from_id_ver("My Project-01", "v1.2")
    assert vc.report_name == "My Project-01 - Report v1.2.pdf"


def test_report_name_stability_multiple_access():
    vc = _make_vc_from_id_ver("PRJ", "v1.3")
    first = vc.report_name
    second = vc.report_name
    assert first == second == "PRJ - Report v1.3.pdf"


def test_report_name_updates_when_version_changes():
    vc = _make_vc_from_id_ver("PRJ", "v1.0")
    assert vc.report_name == "PRJ - Report.pdf"
    vc.version = ProjectVersion.from_str("v1.4")
    assert vc.report_name == "PRJ - Report v1.4.pdf"
    vc.version = ProjectVersion.from_str("v1.0")  # revert back to baseline
    assert vc.report_name == "PRJ - Report.pdf"


def test_report_name_no_trailing_or_leading_spaces():
    vc = _make_vc_from_id_ver("PRJ", "v3.0")
    name = vc.report_name
    assert name == name.strip()
    assert "  " not in name


def test_report_name_different_ids_independent():
    vc1 = _make_vc_from_id_ver("PRJ1", "v1.0")
    vc2 = _make_vc_from_id_ver("PRJ2", "v1.5")
    assert vc1.report_name == "PRJ1 - Report.pdf"
    assert vc2.report_name == "PRJ2 - Report v1.5.pdf"


def test_report_name_case_sensitivity_in_id():
    vc = _make_vc_from_id_ver("prj", "v1.2")
    assert vc.report_name == "prj - Report v1.2.pdf"


def test_report_name_large_version_numbers():
    vc = _make_vc_from_id_ver("PRJ", "v10.7")
    assert vc.report_name == "PRJ - Report v10.7.pdf"


def test_report_name_multiple_changes_sequence():
    vc = _make_vc_from_id_ver("SEQ", "v1.0")
    expected = [
        ("v1.0", "SEQ - Report.pdf"),
        ("v1.1", "SEQ - Report v1.1.pdf"),
        ("v2.0", "SEQ - Report v2.0.pdf"),
        ("v1.0", "SEQ - Report.pdf"),
    ]
    for ver, exp in expected:
        vc.version = ProjectVersion.from_str(ver)
        assert vc.report_name == exp


@pytest.mark.parametrize(
    "proj_id,version,expected",
    [
        ("PRJ", "v1.0", "PRJ - Report.pdf"),
        ("PRJ", "v1.1", "PRJ - Report v1.1.pdf"),
        ("ACME", "v2.0", "ACME - Report v2.0.pdf"),
        ("X", "v9.9", "X - Report v9.9.pdf"),
        ("Complex ID_123", "v1.2", "Complex ID_123 - Report v1.2.pdf"),
    ],
)
def test_report_name_parametrized(proj_id, version, expected):
    vc = _make_vc_from_id_ver(proj_id, version)
    assert vc.report_name == expected


def test_report_name_does_not_mutate_state():
    vc = _make_vc_from_id_ver("IMMUT", "v1.2")
    before_id = vc.id
    before_version = vc.version
    _ = vc.report_name
    assert vc.id == before_id
    assert vc.version == before_version


# ------------------- end VersionConfig.report_name property tests -------------------

# --------------------- VersionConfig.sow_name property tests ---------------------


def test_sow_name_initial_version_no_suffix():
    vc = _make_vc_from_id_ver("PRJ", "v1.0")
    assert vc.sow_name == "PRJ - Statement of Work.pdf"


def test_sow_name_minor_version_included():
    vc = _make_vc_from_id_ver("PRJ", "v1.1")
    assert vc.sow_name == "PRJ - Statement of Work v1.1.pdf"


def test_sow_name_major_version_included():
    vc = _make_vc_from_id_ver("ACME", "v2.0")
    assert vc.sow_name == "ACME - Statement of Work v2.0.pdf"


def test_sow_name_id_with_spaces_and_symbols():
    vc = _make_vc_from_id_ver("My Project-01", "v1.2")
    assert vc.sow_name == "My Project-01 - Statement of Work v1.2.pdf"


def test_sow_name_stability_multiple_access():
    vc = _make_vc_from_id_ver("PRJ", "v1.3")
    first = vc.sow_name
    second = vc.sow_name
    assert first == second == "PRJ - Statement of Work v1.3.pdf"


def test_sow_name_updates_when_version_changes():
    vc = _make_vc_from_id_ver("PRJ", "v1.0")
    assert vc.sow_name == "PRJ - Statement of Work.pdf"
    vc.version = ProjectVersion.from_str("v1.4")
    assert vc.sow_name == "PRJ - Statement of Work v1.4.pdf"
    vc.version = ProjectVersion.from_str("v1.0")
    assert vc.sow_name == "PRJ - Statement of Work.pdf"


def test_sow_name_no_trailing_or_leading_spaces():
    vc = _make_vc_from_id_ver("PRJ", "v3.0")
    name = vc.sow_name
    assert name == name.strip()
    assert "  " not in name


def test_sow_name_different_ids_independent():
    vc1 = _make_vc_from_id_ver("PRJ1", "v1.0")
    vc2 = _make_vc_from_id_ver("PRJ2", "v1.5")
    assert vc1.sow_name == "PRJ1 - Statement of Work.pdf"
    assert vc2.sow_name == "PRJ2 - Statement of Work v1.5.pdf"


def test_sow_name_case_sensitivity_in_id():
    vc = _make_vc_from_id_ver("prj", "v1.2")
    assert vc.sow_name == "prj - Statement of Work v1.2.pdf"


def test_sow_name_large_version_numbers():
    vc = _make_vc_from_id_ver("PRJ", "v10.7")
    assert vc.sow_name == "PRJ - Statement of Work v10.7.pdf"


def test_sow_name_multiple_changes_sequence():
    vc = _make_vc_from_id_ver("SEQ", "v1.0")
    expected = [
        ("v1.0", "SEQ - Statement of Work.pdf"),
        ("v1.1", "SEQ - Statement of Work v1.1.pdf"),
        ("v2.0", "SEQ - Statement of Work v2.0.pdf"),
        ("v1.0", "SEQ - Statement of Work.pdf"),
    ]
    for ver, exp in expected:
        vc.version = ProjectVersion.from_str(ver)
        assert vc.sow_name == exp


@pytest.mark.parametrize(
    "proj_id,version,expected",
    [
        ("PRJ", "v1.0", "PRJ - Statement of Work.pdf"),
        ("PRJ", "v1.1", "PRJ - Statement of Work v1.1.pdf"),
        ("ACME", "v2.0", "ACME - Statement of Work v2.0.pdf"),
        ("X", "v9.9", "X - Statement of Work v9.9.pdf"),
        ("Complex ID_123", "v1.2", "Complex ID_123 - Statement of Work v1.2.pdf"),
    ],
)
def test_sow_name_parametrized(proj_id, version, expected):
    vc = _make_vc_from_id_ver(proj_id, version)
    assert vc.sow_name == expected


def test_sow_name_does_not_mutate_state():
    vc = _make_vc_from_id_ver("IMMUT", "v1.2")
    before_id = vc.id
    before_version = vc.version
    _ = vc.sow_name
    assert vc.id == before_id
    assert vc.version == before_version


def test_sow_name_reversion_from_higher_version():
    vc = _make_vc_from_id_ver("REV", "v2.0")
    assert vc.sow_name == "REV - Statement of Work v2.0.pdf"
    vc.version = ProjectVersion.from_str("v1.0")
    assert vc.sow_name == "REV - Statement of Work.pdf"


def test_sow_name_sequential_minor_versions():
    vc = _make_vc_from_id_ver("MINOR", "v1.0")
    for minor in range(1, 6):
        ver = f"v1.{minor}"
        vc.version = ProjectVersion.from_str(ver)
        assert vc.sow_name == f"MINOR - Statement of Work {ver}.pdf"


# ------------------- end VersionConfig.sow_name property tests -------------------
