from pydantic import validate_call
from rich.prompt import Prompt

from sereto.cli.utils import Console
from sereto.models.date import TYPES_WITH_ALLOWED_RANGE, DateRange, DateType, SeretoDate


@validate_call
def _prompt_date(prompt: str, default: SeretoDate | None = None) -> SeretoDate | None:
    """Interactively prompt the user for a date in the format DD-Mmm-YYYY.

    Returns:
        The data as provided by the user, or None if the input was invalid.
        SeretoDate if correct input was provided, None otherwise
    """
    if default is not None:
        user_input: str = Prompt.ask(prompt, console=Console(), default=str(default))
    else:
        user_input = Prompt.ask(prompt, console=Console())

    try:
        return SeretoDate.from_str(user_input)
    except (ValueError, TypeError):
        return None


@validate_call
def prompt_user_for_date(date_type: DateType) -> SeretoDate | DateRange:
    """Prompt user for a date or date range, depending on the provided date type.

    Date format is DD-Mmm-YYYY.

    Args:
        date_type: The type of date to prompt for.

    Returns:
        The date as provided by the user.
    """
    # Check if the date type allows for a range
    allow_range = date_type in TYPES_WITH_ALLOWED_RANGE

    while True:
        # Prompt user for the start date
        prompt: str = f"Date{' start' if allow_range else ''} (DD-Mmm-YYYY)"
        if (start_date := _prompt_date(prompt)) is None:
            Console().print("[red]Invalid input, try again\n")
            continue

        # Prompt user for the end date, if the date type allows it
        if allow_range:
            if (end_date := _prompt_date("Date end (DD-Mmm-YYYY)", default=start_date)) is None:
                Console().print("[red]Invalid input, try again\n")
                continue
        else:
            end_date = start_date

        return DateRange(start=start_date, end=end_date) if start_date != end_date else start_date
