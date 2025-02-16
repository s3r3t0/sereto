from collections.abc import Iterator
from dataclasses import dataclass

from pydantic import NonNegativeInt


@dataclass
class Risks:
    critical: NonNegativeInt = 0
    high: NonNegativeInt = 0
    medium: NonNegativeInt = 0
    low: NonNegativeInt = 0
    info: NonNegativeInt = 0
    closed: NonNegativeInt = 0

    def __add__(self, other: "Risks") -> "Risks":
        return Risks(
            critical=self.critical + other.critical,
            high=self.high + other.high,
            medium=self.medium + other.medium,
            low=self.low + other.low,
            info=self.info + other.info,
            closed=self.closed + other.closed,
        )

    def __radd__(self, other: "Risks") -> "Risks":
        return self + other

    def __iter__(self) -> Iterator[tuple[str, NonNegativeInt]]:
        yield "critical", self.critical
        yield "high", self.high
        yield "medium", self.medium
        yield "low", self.low
        yield "info", self.info

    @property
    def sum_open(self) -> NonNegativeInt:
        return self.critical + self.high + self.medium + self.low + self.info

    @property
    def sum_all(self) -> NonNegativeInt:
        return self.sum_open + self.closed
