import keyring
import keyring.errors
from keyrings.alt.file import PlaintextKeyring  # type: ignore[import-untyped]


def get_password(service_name: str, username: str) -> str | None:
    """Retrieve a password from the system keyring with fallback to plaintext file."""
    try:
        return keyring.get_password(service_name=service_name, username=username)
    except keyring.errors.InitError:
        keyring.set_keyring(PlaintextKeyring())
        return keyring.get_password("sereto", "encrypt_attached_archive")


def set_password(service_name: str, username: str, password: str) -> None:
    """Set a password to the system keyring with fallback to plaintext file."""
    try:
        keyring.set_password(service_name=service_name, username=username, password=password)
    except keyring.errors.InitError:
        keyring.set_keyring(PlaintextKeyring())
        keyring.set_password("sereto", "encrypt_attached_archive", password)
