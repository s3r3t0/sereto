from pydantic import NonNegativeInt

from sereto.models.base import SeretoBaseModel


class Risk(SeretoBaseModel):
    """Represents a risk with a name, count, and color.

    Attributes:
        name: The name of the risk.
        cnt: How many findings share the same risk level.
        color: The color associated with the risk.
    """

    name: str
    cnt: NonNegativeInt
    color: str


class Risks(SeretoBaseModel):
    """
    A class representing the full spectre of risk severity levels.

    This class contains Risk objects representing different severity levels of risks.
    It provides methods to retrieve the names, counters, and colors of the risks,
    as well as a method to set the count of each risk.

    Attributes:
        critical: A Risk object representing the critical severity level.
        high: A Risk object representing the high severity level.
        medium: A Risk object representing the medium severity level.
        low: A Risk object representing the low severity level.
        info: A Risk object representing the informational severity level.
    """

    critical: Risk = Risk(name="critical", cnt=0, color="red")
    high: Risk = Risk(name="high", cnt=0, color="orange")
    medium: Risk = Risk(name="medium", cnt=0, color="#f0f000")
    low: Risk = Risk(name="low", cnt=0, color="#33cc33")
    info: Risk = Risk(name="informational", cnt=0, color="#3366ff")

    def names(self) -> tuple[str, str, str, str, str]:
        """
        Return a tuple of the names for each severity.

        The risk names are sorted from the most severe ones to the least severe.

        Returns:
            A tuple containing the names of all the Risk objects.
        """
        return (
            self.critical.name,
            self.high.name,
            self.medium.name,
            self.low.name,
            self.info.name,
        )

    def counts(self) -> tuple[int, int, int, int, int]:
        """Return a tuple of the counters for each severity level.

        The counters are sorted from the most severe risks to the least severe.

        Returns:
            A tuple of per risk counters for each severity level.
        """
        return (self.critical.cnt, self.high.cnt, self.medium.cnt, self.low.cnt, self.info.cnt)

    def colors(self) -> tuple[str, str, str, str, str]:
        """
        Return a tuple of the colors for each severity level.

        The risk colors are sorted by severity, from the most severe ones to the least severe.

        Returns:
            A tuple containing the colors of the Risk objects.
        """
        return (self.critical.color, self.high.color, self.medium.color, self.low.color, self.info.color)

    def set_counts(
        self,
        critical: NonNegativeInt,
        high: NonNegativeInt,
        medium: NonNegativeInt,
        low: NonNegativeInt,
        info: NonNegativeInt,
    ) -> "Risks":
        """Set the count of each Risk object in the Risks object.

        Args:
            critical: An integer representing the count of the critical Risk object.
            high: An integer representing the count of the high Risk object.
            medium: An integer representing the count of the medium Risk object.
            low: An integer representing the count of the low Risk object.
            info: An integer representing the count of the informational Risk object.

        Returns:
            The Risks object with updated counts for each Risk object.
        """
        self.critical.cnt = critical
        self.high.cnt = high
        self.medium.cnt = medium
        self.low.cnt = low
        self.info.cnt = info
        return self
