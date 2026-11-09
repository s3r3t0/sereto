import sereto.crypto as crypto


def test_encrypt_decrypt_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(crypto, "get_password", lambda service, username: "test-password")
    derive_key = crypto.derive_key_argon2

    def fast_derive_key(password, salt=None):
        return derive_key(password, salt=salt, memory_cost=8, time_cost=1, parallelism=1)

    monkeypatch.setattr(crypto, "derive_key_argon2", fast_derive_key)
    source = tmp_path / "source.tgz"
    source.write_bytes(b"test archive data")
    encrypted = crypto.encrypt_file(source, keep_original=True)
    try:
        decrypted = crypto.decrypt_file(encrypted, keep_original=True)
        try:
            assert decrypted.read_bytes() == source.read_bytes()
        finally:
            decrypted.unlink()
    finally:
        encrypted.unlink()
