import pytest

from sereto.logging import logger
from sereto.utils import replace_strings


def test_replace_strings_empty_text_returns_input():
    text = ""
    result = replace_strings(text=text, replacements={"foo": "bar"})
    assert result == ""


def test_replace_strings_empty_replacements_return_same_items():
    items = ["one", "two"]
    result = replace_strings(text=items, replacements={})
    assert result == items


@pytest.mark.parametrize(
    "text,replacements,expected",
    [
        ("alpha beta gamma", {"alpha": "A", "gamma": "G"}, "A beta G"),
        ("foo foo foo", {"foo": "bar"}, "bar bar bar"),
        ("%A%%B%", {"%A%": "1", "%B%": "2"}, "12"),
    ],
)
def test_replace_strings_replaces_patterns_in_string(text, replacements, expected):
    assert replace_strings(text=text, replacements=replacements) == expected


def test_replace_strings_escapes_regex_metacharacters():
    text = "file.name+copy?"
    replacements = {".": "-", "+": "plus", "?": "Q"}
    assert replace_strings(text=text, replacements=replacements) == "file-namepluscopyQ"


def test_replace_strings_handles_list_input_and_preserves_original():
    values = ["%A%/%B%", "%B%-%A%", "unchanged"]
    expected = ["1/2", "2-1", "unchanged"]
    result = replace_strings(text=values, replacements={"%A%": "1", "%B%": "2"})
    assert result == expected
    assert values == ["%A%/%B%", "%B%-%A%", "unchanged"]


def test_replace_strings_single_pass_no_cascade():
    text = "foo"
    replacements = {"foo": "bar", "bar": "baz"}
    assert replace_strings(text=text, replacements=replacements) == "bar"


def test_replace_strings_emits_logs_for_string_branch():
    messages: list[str] = []
    handler_id = logger.add(messages.append, level="TRACE", format="{level}:{message}")
    try:
        replace_strings(text="foo", replacements={"foo": "bar"})
    finally:
        logger.remove(handler_id)

    assert any("replace_strings applied to string" in message for message in messages)
    assert any(message.startswith("TRACE:") for message in messages)


def test_replace_strings_logs_previews_for_large_payloads():
    large_text = "ABC" * 100
    replacements = {"ABC": "XYZ"}
    messages: list[str] = []
    handler_id = logger.add(messages.append, level="TRACE", format="{level}:{message}")
    try:
        replace_strings(text=large_text, replacements=replacements)
    finally:
        logger.remove(handler_id)

    joined = "\n".join(messages)
    assert "text_preview" in joined
    assert "before_preview" in joined
    assert "after_preview" in joined
    assert "..." in joined  # trimmed preview


def test_replace_strings_logs_replacement_mapping():
    messages: list[str] = []
    handler_id = logger.add(messages.append, level="TRACE", format="{level}:{message}")
    try:
        replace_strings(text="abba", replacements={"ab": "CD", "ba": "EF"})
    finally:
        logger.remove(handler_id)

    assert any("ab->CD" in msg or "ba->EF" in msg for msg in messages)
