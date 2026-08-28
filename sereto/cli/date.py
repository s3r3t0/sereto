from sereto.models.date import TYPES_WITH_ALLOWED_RANGE, DateType


def allows_range(date_type: DateType) -> bool:
    """Check if the date type allows for a range."""
    return date_type in TYPES_WITH_ALLOWED_RANGE
