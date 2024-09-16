from typing import Annotated

from pydantic import Field
from pydantic.functional_validators import AfterValidator

__all__ = [
    "TypeReportId",
    "TypePathName",
    "TypeCategories",
    "TypePassword",
    "TypeNonce12B",
    "TypeSalt16B",
]


TypeReportId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9._-]{1,20}$", strict=True)]
"""
Type for report ID.

The value should meet the following requirements:

- It can only contain letters (`a-zA-Z`), numbers (`0-9`), underscore (`_`), dash (`-`), and dot (`.`).
- It should be between 1 and 20 characters long.
"""


TypePathName = Annotated[str, Field(pattern=r"^[a-zA-Z0-9._-]{1,100}$", strict=True)]
"""
Type for path name.

The value should meet the following requirements:

- It can only contain letters (`a-zA-Z`), numbers (`0-9`), underscore (`_`), dash (`-`), and dot (`.`).
- It should be between 1 and 100 characters long.
"""


TypeCategories = set[Annotated[str, Field(pattern=r"^[a-zA-Z0-9._-]{1,20}$", strict=True)]]
"""
Type for categories names.

The values should meet the following requirements:

- It can only contain letters (`a-zA-Z`), numbers (`0-9`), underscore (`_`), dash (`-`), and dot (`.`).
- It should be between 1 and 20 characters long.

Example:
    You can provide values such as `dast`, `sast` (or `DAST`, `SAST`), etc.
"""


TypePassword = Annotated[str, Field(min_length=8, max_length=100, strict=True)]
"""
Type for password.

The value should meet the following requirements:

- It should be between 8 and 100 characters long.
"""


def zero_bytes(value: bytes) -> bytes:
    if all(byte == 0 for byte in value):
        raise ValueError("salt contains only zero bytes")
    return value


TypeNonce12B = Annotated[bytes, AfterValidator(zero_bytes), Field(min_length=12, max_length=12)]
"""
Type for a 12 byte long nonce.

The value must contain at least one non-zero byte. This check is in place to prevent unintentional errors.
"""


TypeSalt16B = Annotated[bytes, AfterValidator(zero_bytes), Field(min_length=16, max_length=16)]
"""
Type for a 16 byte long salt.

The value must contain at least one non-zero byte. This check is in place to prevent unintentional errors.
"""
