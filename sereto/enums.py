from enum import Enum

from sereto.exceptions import SeretoValueError


class Environment(str, Enum):
    """Enum representing the environment of a Target."""

    acceptance = "acceptance"
    development = "development"
    production = "production"
    testing = "testing"


class FileFormat(str, Enum):
    """Enum representing the file format."""

    md = "md"
    tex = "tex"


class OutputFormat(str, Enum):
    """Enum representing the output format."""

    table = "table"
    json = "json"


class Risk(str, Enum):
    """Enum representing the risk level of a finding."""

    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"
    closed = "closed"

    def to_int(self) -> int:
        """Convert risks to a number.

        Usefull for comparison - e.g. `max(risks, key=lambda r: r.to_int())`
        """
        match self:
            case Risk.closed:
                return 0
            case Risk.info:
                return 1
            case Risk.low:
                return 2
            case Risk.medium:
                return 3
            case Risk.high:
                return 4
            case Risk.critical:
                return 5
            case _:
                raise SeretoValueError("unexpected risk value")
