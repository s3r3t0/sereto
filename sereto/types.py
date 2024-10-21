from typing import Annotated

from annotated_types import Len
from pydantic import Strict, StringConstraints
from pydantic.functional_validators import AfterValidator

__all__ = [
    "TypeProjectId",
    "TypePathName",
    "TypeCategories",
    "TypePassword",
    "TypeNonce12B",
    "TypeSalt16B",
]


TypeProjectId = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9._-]{1,20}$", strict=True)]
"""Type for report ID.

The value should meet the following requirements:

- It can only contain letters (`a-zA-Z`), numbers (`0-9`), underscore (`_`), dash (`-`), and dot (`.`).
- It should be between 1 and 20 characters long.
"""


TypePathName = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9._-]{1,100}$", strict=True)]
"""Type for path name.

The value should meet the following requirements:

- It can only contain letters (`a-zA-Z`), numbers (`0-9`), underscore (`_`), dash (`-`), and dot (`.`).
- It should be between 1 and 100 characters long.
"""


TypeCategories = set[Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9._-]{1,20}$", strict=True)]]
"""Type for categories names.

The values should meet the following requirements:

- It can only contain letters (`a-zA-Z`), numbers (`0-9`), underscore (`_`), dash (`-`), and dot (`.`).
- It should be between 1 and 20 characters long.

Example:
    You can provide values such as `dast`, `sast` (or `DAST`, `SAST`), etc.
"""


TypePassword = Annotated[str, Strict(), Len(8, 100)]
"""Type for password.

The value should meet the following requirements:

- It should be between 8 and 100 characters long.
"""


def zero_bytes(value: bytes) -> bytes:
    if all(byte == 0 for byte in value):
        raise ValueError("salt contains only zero bytes")
    return value


TypeNonce12B = Annotated[bytes, Len(12, 12), Strict(), AfterValidator(zero_bytes)]
"""Type for a 12 byte long nonce.

The value must contain at least one non-zero byte. This check is in place to prevent unintentional errors.
"""


TypeSalt16B = Annotated[bytes, Len(16, 16), Strict(), AfterValidator(zero_bytes)]
"""Type for a 16 byte long salt.

The value must contain at least one non-zero byte. This check is in place to prevent unintentional errors.
"""
