from typing import Annotated

from pydantic import Field

TypeReportId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9._-]{1,20}$")]
"""Type for report ID.

The value should meet the following requirements:

- It can only contain letters (`a-zA-Z`), numbers (`0-9`), underscore (`_`), dash (`-`), and dot (`.`).
- It should be between 1 and 20 characters long.
"""


TypePathName = Annotated[str, Field(pattern=r"^[a-zA-Z0-9._-]{1,100}$")]
"""Type for path name.

The value should meet the following requirements:

- It can only contain letters (`a-zA-Z`), numbers (`0-9`), underscore (`_`), dash (`-`), and dot (`.`).
- It should be between 1 and 100 characters long.
"""


TypeCategories = set[Annotated[str, Field(pattern=r"^[a-zA-Z0-9._-]{1,20}$")]]
"""Type for categories names.

The values should meet the following requirements:

- It can only contain letters (`a-zA-Z`), numbers (`0-9`), underscore (`_`), dash (`-`), and dot (`.`).
- It should be between 1 and 20 characters long.

Example:
    You can provide values such as `dast`, `sast` (or `DAST`, `SAST`), etc.
"""
