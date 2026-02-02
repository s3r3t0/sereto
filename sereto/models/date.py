from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import GetJsonSchemaHandler, model_validator
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

from sereto.models.base import SeretoBaseModel

# Date format used for parsing and serialization: "01-Jan-2024"
SERETO_DATE_FORMAT = r"%d-%b-%Y"


class SeretoDate(date):
    """Date subclass with format `%d-%b-%Y` (e.g., "01-Jan-2024").

    This is a `datetime.date` subclass with:
     - Custom `__new__` that accepts strings in `%d-%b-%Y` format
     - Custom `__str__` that formats as `%d-%b-%Y`
     - All standard date operations (comparison, arithmetic, hashing) work natively

    The format string specifies:
     - `%d`: Day of the month as a zero-padded decimal number (e.g. 01, 02, ..., 31).
     - `%b`: Month abbreviation in the current locale's abbreviated name (e.g. Jan, Feb, ..., Dec).
     - `%Y`: Year with century as a decimal number (e.g. 2021, 2022, ...).
    """

    def __new__(cls, value: Any) -> SeretoDate:
        """Create a SeretoDate from a string or date.

        Args:
            value: Either a string in `%d-%b-%Y` format, a date object, or a SeretoDate.

        Returns:
            A new SeretoDate instance.

        Raises:
            ValueError: If the string format is invalid or type is unsupported.
        """
        match value:
            case SeretoDate():
                return value
            case date():
                return super().__new__(cls, value.year, value.month, value.day)
            case str():
                d = datetime.strptime(value, SERETO_DATE_FORMAT).date()
                return super().__new__(cls, d.year, d.month, d.day)
            case _:
                raise ValueError(f"invalid type for SeretoDate: {type(value).__name__}")

    def __str__(self) -> str:
        return self.strftime(SERETO_DATE_FORMAT)

    def __repr__(self) -> str:
        return f"SeretoDate('{self!s}')"

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: Callable[[Any], core_schema.CoreSchema],
    ) -> core_schema.CoreSchema:
        def validate(value: Any) -> SeretoDate:
            if not isinstance(value, str | date):
                raise ValueError(f"invalid type for SeretoDate: {type(value)}")
            return cls(value)

        def serialize(value: SeretoDate) -> str:
            return str(value)

        return core_schema.json_or_python_schema(
            json_schema=core_schema.chain_schema(
                [
                    core_schema.str_schema(),
                    core_schema.no_info_plain_validator_function(validate),
                ]
            ),
            python_schema=core_schema.union_schema(
                [
                    core_schema.is_instance_schema(cls),
                    core_schema.no_info_plain_validator_function(validate),
                ]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(serialize),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _core_schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return handler(core_schema.str_schema())


class DateType(StrEnum):
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
    def chronological_order(self) -> DateRange:
        if self.start >= self.end:
            raise ValueError("DateRange type forbids start after or equal to end")
        return self

    def __hash__(self) -> int:
        return hash((self.start, self.end))


class Date(SeretoBaseModel):
    """Model representing a date with its associated event.

    Attributes:
        type (DateType): Type of the event.
        date (SeretoDate | DateRange): Date or date range.
    """

    type: DateType
    date: SeretoDate | DateRange

    @model_validator(mode="after")
    def range_allowed(self) -> Date:
        if isinstance(self.date, DateRange) and self.type not in TYPES_WITH_ALLOWED_RANGE:
            raise ValueError(f"type {self.type} does not have allowed date range, only single date")
        return self

    def __str__(self) -> str:
        match self.date:
            case SeretoDate():
                return str(self.date)
            case DateRange():
                return f"{self.date.start} to {self.date.end}"

    def __hash__(self) -> int:
        return hash((self.type, self.date))
