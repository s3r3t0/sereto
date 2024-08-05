from datetime import date, datetime
from enum import Enum
from functools import total_ordering
from typing import Any

from pydantic import FieldSerializationInfo, RootModel, field_serializer, field_validator, model_validator

from sereto.exceptions import SeretoValueError
from sereto.models.base import SeretoBaseModel


@total_ordering
class SeretoDate(RootModel[date]):
    root: date
    """Date representation for Pydantic with format `%d-%b-%Y`.

    The `%d-%b-%Y` format string specifies the format of the date string as follows:
     - `%d`: Day of the month as a zero-padded decimal number (e.g. 01, 02, ..., 31).
     - `%b`: Month abbreviation in the current locale's abbreviated name (e.g. Jan, Feb, ..., Dec).
     - `%Y`: Year with century as a decimal number (e.g. 2021, 2022, ..., 9999).
    """

    @field_validator("root", mode="before")
    @classmethod
    def convert_date(cls, v: Any) -> date:
        match v:
            case SeretoDate():
                return v.root
            case str():
                return datetime.strptime(v, r"%d-%b-%Y").date()
            case _:
                raise ValueError("invalid type, use string or date")

    @classmethod
    def from_str(cls, v: str) -> "SeretoDate":
        date = datetime.strptime(v, r"%d-%b-%Y").date()
        return cls.model_construct(root=date)

    @field_serializer("root")
    def serialize_root(self, root: date, info: FieldSerializationInfo) -> str:
        return self.__str__()

    def __str__(self) -> str:
        return self.root.strftime(r"%d-%b-%Y")

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, SeretoDate):
            raise SeretoValueError("comparing SeretoDate with unsupported type")
        return self.root < other.root

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, SeretoDate):
            raise SeretoValueError("comparing SeretoDate with unsupported type")
        return self.root == other.root

    def raw(self) -> date:
        return self.root


class DateType(str, Enum):
    """Enum representing the event type for date."""

    sow_sent = "sow_sent"
    pentest_ongoing = "pentest_ongoing"
    review = "review"
    report_sent = "report_sent"


# Date types which we allow to have also range, not only a single date
TYPES_WITH_ALLOWED_RANGE = [DateType.pentest_ongoing]


class DateRange(SeretoBaseModel):
    """Model representing a period of time with start and end date.

    `start` cannot be equal to `end`. In that case you should use `SeretoDate`.

    Attributes:
        start (SeretoDate): Start date of the period.
        end (SeretoDate): End date of the period.
    """

    start: SeretoDate
    end: SeretoDate

    @model_validator(mode="after")
    def chronological_order(self) -> "DateRange":
        if self.start >= self.end:
            raise ValueError("DateRange type forbids start after or equal to end")
        return self


class Date(SeretoBaseModel):
    """Model representing a date with its associated event.

    Attributes:
        type (DateType): Type of the event.
        date (SeretoDate | DateRange): Date or date range.
    """

    type: DateType
    date: SeretoDate | DateRange

    @model_validator(mode="after")
    def range_allowed(self) -> "Date":
        if isinstance(self.date, DateRange) and self.type not in TYPES_WITH_ALLOWED_RANGE:
            raise ValueError(f"type {self.type} does not have allowed date range, only single date")
        return self
