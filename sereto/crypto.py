import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import keyring
from argon2.low_level import Type as Argon2Type
from argon2.low_level import hash_secret_raw as argon2_hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import FilePath, TypeAdapter, ValidationError, validate_call

from sereto.cli.utils import Console
from sereto.exceptions import SeretoEncryptionError, SeretoPathError, SeretoValueError
from sereto.types import TypeNonce12B, TypePassword, TypeSalt16B
from sereto.utils import assert_file_size_within_range

__all__ = [
    "encrypt_file",
    "decrypt_file",
]


@validate_call
def derive_key_argon2(
    password: TypePassword,
    salt: TypeSalt16B | None = None,
    memory_cost: int = 1_048_576,
    time_cost: int = 4,
    parallelism: int = 8,
) -> tuple[bytes, TypeSalt16B]:
    """Derive a key using Argon2id from a password.

    Args:
        password: Password to derive the key from.
        salt: 16 bytes long salt. If None, a random salt is generated.
        memory_cost: Memory cost in KiB. Defaults to 1 GiB.
        time_cost: Time cost (number of iterations). Defaults to 4.
        parallelism: Parallelism factor. Defaults to 8.

    Returns:
        Derived key and salt.
    """
    # Generate a salt if not provided (16 bytes)
    if salt is None:
        salt = os.urandom(16)

    # Derive a key using Argon2id
    key = argon2_hash_secret_raw(
        secret=password.encode(encoding="utf-8"),
        salt=salt,
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=32,  # Desired key length in bytes (32 bytes = 256 bits for AES-256)
        type=Argon2Type.ID,  # Argon2id variant (mix of Argon2i and Argon2d)
    )

    return key, salt


@validate_call
def encrypt_file(file: FilePath, keep_original: bool = False) -> Path:
    """Encrypts a given file using AES-GCM encryption and saves it with a .sereto suffix.

    This function retrieves a password from the system keyring, derives an encryption key using Argon2, and encrypts
    the file content. The encrypted data is then saved with a specific header and the original file is deleted (use
    `keep_original=True` to overwrite deletion).

    Args:
        file: The path to the file to be encrypted.
        keep_original: If True, the original encrypted file is kept. Defaults to False.

    Returns:
        Path to the encrypted file with suffix `.sereto`.

    Raises:
        SeretoEncryptionError: If the password is not found in the system keyring.
        SeretoPathError: If the provided file does not exist.
        SeretoValueError: If the file size exceeds 1 GiB and the user chooses not to continue.
    """
    if not file.is_file():
        raise SeretoPathError(f"file '{file}' does not exist")

    # Retrieve the password from the system keyring
    password = keyring.get_password("sereto", "encrypt_attached_archive")

    # Validate the password
    try:
        ta: TypeAdapter[TypePassword] = TypeAdapter(TypePassword)  # hack for mypy
        password = ta.validate_python(password)
    except ValidationError as e:
        Console().log(f"[yellow]Invalid password for archive encryption: {e.errors()[0]['msg']}")
        raise SeretoEncryptionError(f"encryption password is invalid: {e.errors()[0]['msg']}") from e

    assert_file_size_within_range(file=file, max_bytes=1_073_741_824, interactive=True)

    Console().log(":locked: Found password for archive encryption.\nEncrypting archive...")

    data = file.read_bytes()

    # Derive the key using Argon2id
    key, salt = derive_key_argon2(password=password)

    # Generate a 12-byte random nonce - IV for AES
    # - NIST recommends a 96-bit IV length for best performance - https://csrc.nist.gov/pubs/sp/800/38/d/final
    nonce: TypeNonce12B = os.urandom(12)

    # Encrypt the data
    encrypted_data = AESGCM(key).encrypt(nonce=nonce, data=data, associated_data=None)

    # Prepare the header (64 bytes long)
    header = b"SeReTo" + nonce + salt
    header = header.ljust(64, b"\x00")

    # Write the encrypted data into a new file
    with NamedTemporaryFile(suffix=".sereto", delete=False) as tmp:
        (encrypted_path := Path(tmp.name)).write_bytes(header + encrypted_data)

    # Delete the original file if `keep_file=False`
    if not keep_original:
        file.unlink()

    Console().log("[green]Archive successfully encrypted")

    # Return the path to the encrypted file
    return encrypted_path


@validate_call
def decrypt_file(file: FilePath, keep_original: bool = True) -> Path:
    """Decrypts a .sereto file using AES-GCM encryption and saves it with a .tgz suffix.

    This function retrieves a password from the system keyring, derives an encryption key using Argon2, parses the
    header (contains nonce and seed), and decrypts the file content. The decrypted data is then saved with a .tgz
    suffix and the original file is deleted (use `keep_original=True` to overwrite deletion).

    Args:
        file: The path to the encrypted .sereto file.
        keep_original: If True, the original encrypted file is kept. Defaults to False.

    Raises:
        click.Abort: If the file size exceeds 1 GiB and the user chooses not to continue.
        SeretoValueError: If the file is corrupted or not encrypted with SeReTo.

    Returns:
        Path to the decrypted file.
    """
    if not file.is_file():
        raise SeretoPathError(f"File '{file}' does not exist")

    if file.suffix != ".sereto":
        raise SeretoValueError("Unsupported file format for decryption (not a .sereto)")

    password = keyring.get_password("sereto", "encrypt_attached_archive")

    if not password:
        raise SeretoValueError("No password found for archive decryption")

    Console().log(":locked: Found password for archive decryption.\nDecrypting archive...")

    assert_file_size_within_range(file=file, min_bytes=65, max_bytes=1_073_741_824, interactive=True)

    data = file.read_bytes()

    # Extract the header, nonce, salt, and encrypted data
    if not data[:6] == b"SeReTo":
        raise SeretoValueError("Encrypted file is corrupted or not encrypted with SeReTo")

    nonce: TypeNonce12B = data[6:18]
    salt: TypeSalt16B = data[18:34]
    encrypted_data = data[64:]

    # Derive the key using Argon2id
    key, _ = derive_key_argon2(password=password, salt=salt)

    # Decrypt the data
    decrypted_data = AESGCM(key).decrypt(nonce=nonce, data=encrypted_data, associated_data=None)

    # Write the decrypted data
    with NamedTemporaryFile(suffix=".tgz", delete=False) as tmp:
        (output := Path(tmp.name)).write_bytes(decrypted_data)

    Console().log(f"[green]+[/green] Decrypted archive to '{output}'")

    if not keep_original:
        file.unlink()
        Console().log(f"[red]-[/red] Deleted encrypted archive: '{file}'")

    return output
