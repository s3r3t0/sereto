"""`sereto settings password set` must only store passwords that archive encryption accepts.

Previously any string was stored; a too-short password was later rejected during `sereto pdf report`, which then
silently embedded the project sources unencrypted.
"""

import pytest
from click.testing import CliRunner

import sereto.cli.cli as cli_module
from sereto.cli.cli import settings_password_set


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    store: dict[tuple[str, str], str] = {}

    def fake_set_password(service_name: str, username: str, password: str) -> None:
        store[(service_name, username)] = password

    monkeypatch.setattr(cli_module, "set_password", fake_set_password)
    return store


@pytest.mark.parametrize("password", ["", "short", "1234567", "x" * 101])
def test_invalid_password_option_is_rejected(stored: dict[tuple[str, str], str], password: str) -> None:
    result = CliRunner().invoke(settings_password_set, ["--password", password])

    assert result.exit_code == 2
    assert "password must be between 8 and 100 characters long" in result.output
    assert stored == {}


@pytest.mark.parametrize("password", ["12345678", "x" * 100, "CorrectHorseBattery42!"])
def test_valid_password_option_is_stored(stored: dict[tuple[str, str], str], password: str) -> None:
    result = CliRunner().invoke(settings_password_set, ["--password", password])

    assert result.exit_code == 0, result.output
    assert stored == {("sereto", "encrypt_attached_archive"): password}


def test_prompt_asks_again_after_invalid_password(stored: dict[tuple[str, str], str]) -> None:
    result = CliRunner().invoke(settings_password_set, input="short\nLongEnoughPass1\nLongEnoughPass1\n")

    assert result.exit_code == 0, result.output
    assert "password must be between 8 and 100 characters long" in result.output
    assert stored == {("sereto", "encrypt_attached_archive"): "LongEnoughPass1"}


def test_prompt_requires_matching_confirmation(stored: dict[tuple[str, str], str]) -> None:
    result = CliRunner().invoke(
        settings_password_set, input="AnotherPass123\nTypoPass123\nAnotherPass123\nAnotherPass123\n"
    )

    assert result.exit_code == 0, result.output
    assert "do not match" in result.output
    assert stored == {("sereto", "encrypt_attached_archive"): "AnotherPass123"}
