from typing import Annotated

from annotated_types import Len
from pydantic import SecretBytes, SecretStr, Strict, StringConstraints
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
"""Type for project ID.

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


TypeCategoryName = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9._-]{1,20}$", strict=True)]
"""Type for category name.

The value should meet the following requirements:

- It can only contain letters (`a-zA-Z`), numbers (`0-9`), underscore (`_`), dash (`-`), and dot (`.`).
- It should be between 1 and 20 characters long.
"""


TypeCategories = set[TypeCategoryName]
"""Type for set of categories.

The values should meet the following requirements:

- It can only contain letters (`a-zA-Z`), numbers (`0-9`), underscore (`_`), dash (`-`), and dot (`.`).
- It should be between 1 and 20 characters long.

Example:
    You can provide values such as `dast`, `sast` (or `DAST`, `SAST`), etc.
"""


TypePassword = Annotated[SecretStr, Strict(), Len(8, 100)]
"""Type for password.

Using SecretStr prevents the password from being printed in logs or tracebacks.

The value should meet the following requirements:

- It should be between 8 and 100 characters long.
"""


def zero_bytes(value: SecretBytes) -> SecretBytes:
    if all(byte == 0 for byte in value.get_secret_value()):
        raise ValueError("salt contains only zero bytes")
    return value


TypeNonce12B = Annotated[SecretBytes, Len(12, 12), Strict(), AfterValidator(zero_bytes)]
"""Type for a 12 byte long nonce.

Using SecretBytes prevents the nonce from being printed in logs or tracebacks.

The value must contain at least one non-zero byte. This check is in place to prevent unintentional errors.
"""


TypeSalt16B = Annotated[SecretBytes, Len(16, 16), Strict(), AfterValidator(zero_bytes)]
"""Type for a 16 byte long salt.

Using SecretBytes prevents the salt from being printed in logs or tracebacks.

The value must contain at least one non-zero byte. This check is in place to prevent unintentional errors.
"""
