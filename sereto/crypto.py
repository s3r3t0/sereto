import os
from pathlib import Path

import click
import keyring
from argon2.low_level import Type as Argon2Type
from argon2.low_level import hash_secret_raw as argon2_hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from humanize import naturalsize
from pydantic import validate_call

from sereto.cli.console import Console
from sereto.exceptions import SeretoValueError
from sereto.types import TypeNonce12B, TypePassword, TypeSalt16B

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
    """
    Derive a key using Argon2id from a password.

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
def encrypt_file(file: Path, keep_file: bool = False) -> None:
    """
    Encrypts a given file using AES-GCM encryption and saves it with a .sereto suffix.

    This function retrieves a password from the system keyring, derives an encryption key using Argon2, and encrypts
    the file content. The encrypted data is then saved with a specific header and the original file is deleted (use
    `keep_file=True` to overwrite deletion).

    Args:
        file: The path to the file to be encrypted.
        keep_file: If True, the original encrypted file is kept. Defaults to False.

    Raises:
        click.Abort: If the file size exceeds 1 GiB and the user chooses not to continue.
    """
    if file.suffix not in [".tgz", ".tar.gz"]:
        Console().log("[yellow]Unsupported file format for encryption (not a .tgz or .tar.gz)\nSkipping encryption...")
        return

    password = keyring.get_password("sereto", "encrypt_attached_archive")

    if not password:
        Console().log("[yellow]No password found for archive encryption\nSkipping encryption...")
        return

    if (file_size := file.stat().st_size) == 0:
        Console().log("[yellow]The attached archive with sources is empty\nSkipping encryption...")
        return

    if file_size > 1_073_741_824:
        click.confirm(
            f"The attached archive with sources has {naturalsize(file_size, binary=True)}, which exceeds threshold of "
            "1 GiB. Do you want to continue?",
            default=False,
            abort=True,
        )

    Console().log("[green]Found password for archive encryption. Encrypting archive")

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
    file.with_suffix(".sereto").write_bytes(header + encrypted_data)

    if not keep_file:
        file.unlink()

    Console().log("[green]Archive successfully encrypted")


@validate_call
def decrypt_file(file: Path, keep_file: bool = False) -> None:
    """
    Decrypts a .sereto file using AES-GCM encryption and saves it with a .tgz suffix.

    This function retrieves a password from the system keyring, derives an encryption key using Argon2, parses the
    header (contains nonce and seed), and decrypts the file content. The decrypted data is then saved with a .tgz
    suffix and the original file is deleted (use `keep_file=True` to overwrite deletion).

    Args:
        file: The path to the encrypted .sereto file.
        keep_file: If True, the original encrypted file is kept. Defaults to False.

    Raises:
        click.Abort: If the file size exceeds 1 GiB and the user chooses not to continue.
        SeretoValueError: If the file is corrupted or not encrypted with SeReTo.
    """

    if file.suffix != ".sereto":
        raise SeretoValueError("Unsupported file format for decryption (not a .sereto)")

    password = keyring.get_password("sereto", "encrypt_attached_archive")

    if not password:
        raise SeretoValueError("No password found for archive decryption")

    Console().log("[green]Found password for archive decryption. Decrypting archive")

    if (file_size := file.stat().st_size) <= 64:
        Console().log(
            f"[yellow]The attached archive with sources is empty or corrupted ({file_size} B)\nSkipping decryption"
        )
        return

    if file_size > 1_073_741_824:
        click.confirm(
            f"The encrypted archive has {naturalsize(file_size, binary=True)}, which exceeds threshold of 1 GiB. "
            "Do you want to continue?",
            default=False,
            abort=True,
        )

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

    # Write the decrypted data back to the file
    file.with_suffix(".tgz").write_bytes(decrypted_data)

    if not keep_file:
        file.unlink()

    Console().log("[green]Archive successfully decrypted")
