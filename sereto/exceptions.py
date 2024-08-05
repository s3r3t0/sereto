class SeretoException(Exception):
    """There was an ambiguous exception."""


class SeretoPathError(SeretoException):
    """Path error."""


class SeretoRuntimeError(SeretoException):
    """Runtime error."""


class SeretoTypeError(SeretoException):
    """Type error."""


class SeretoValueError(SeretoException, ValueError):
    """Value error."""
