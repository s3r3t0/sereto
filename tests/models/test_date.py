import pytest

from sereto.models.date import TYPES_WITH_ALLOWED_RANGE, Date, DateRange, DateType, SeretoDate


class TestSeretoDate:
    @pytest.mark.parametrize("input", ["01-Jan-2024", "29-Feb-2024", "31-Dec-2024"])
    def test_construct_valid(self, input):
        date = SeretoDate(input)
        assert str(date) == input

    @pytest.mark.parametrize("input", ["2024-01-01", "20240101", "31-Apr-2024", "29-Feb-2025", 1709840746, "", None])
    def test_construct_invalid(self, input):
        with pytest.raises(ValueError):
            SeretoDate(input)

    @pytest.mark.parametrize(
        "a,b", [("01-Jan-2024", "05-Jan-2024"), ("01-Jan-2024", "01-Feb-2024"), ("01-Jan-2024", "01-Jan-2025")]
    )
    def test_lt_gt(self, a, b):
        assert SeretoDate(a) < SeretoDate(b)
        assert SeretoDate(b) > SeretoDate(a)

    @pytest.mark.parametrize("a,b", [("01-Jan-2024", "01-Jan-2024"), ("18-Jul-2025", "18-Jul-2025")])
    def test_eq(self, a, b):
        assert SeretoDate(a) == SeretoDate(b)

    @pytest.mark.parametrize(
        "a,b", [("01-Jan-2024", "05-Jan-2024"), ("01-Jan-2024", "01-Feb-2024"), ("01-Jan-2024", "01-Jan-2025")]
    )
    def test_not_eq(self, a, b):
        assert SeretoDate(a) != SeretoDate(b)


class TestDateRange:
    @pytest.mark.parametrize(
        "a,b", [("01-Jan-2024", "02-Jan-2024"), ("10-Jul-2025", "17-Aug-2025"), ("11-Feb-2030", "03-Apr-2031")]
    )
    def test_construct_valid(self, a, b):
        DateRange(start=SeretoDate(a), end=SeretoDate(b))

    @pytest.mark.parametrize(
        "a,b", [("01-Jan-2024", "01-Jan-2024"), ("10-Jul-2025", "08-Jul-2025"), ("11-Feb-2031", "03-Apr-2030")]
    )
    def test_construct_invalid(self, a, b):
        with pytest.raises(ValueError):
            DateRange(start=SeretoDate(a), end=SeretoDate(b))


class TestDate:
    @pytest.mark.parametrize("a,b", [("01-Jan-2024", "02-Jan-2024"), ("10-Jul-2025", "17-Aug-2025")])
    def test_construct_valid(self, a, b):
        for type in DateType:
            Date(type=type, date=SeretoDate(a))
            Date(type=type, date=SeretoDate(b))

        for type in TYPES_WITH_ALLOWED_RANGE:
            Date(type=type, date=DateRange(start=SeretoDate(a), end=SeretoDate(b)))

    @pytest.mark.parametrize("a,b", [("01-Jan-2024", "02-Jan-2024"), ("10-Jul-2025", "17-Aug-2025")])
    def test_construct_invalid(self, a, b):
        for type in DateType:
            if type not in TYPES_WITH_ALLOWED_RANGE:
                with pytest.raises(ValueError):
                    Date(type=type, date=DateRange(start=SeretoDate(a), end=SeretoDate(b)))
