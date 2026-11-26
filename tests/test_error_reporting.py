"""Regression tests: errors must reach the user with a readable message instead of a bare exception type."""

import sys
from types import SimpleNamespace
from typing import Any

import pytest
from jinja2 import TemplateSyntaxError

import sereto.build as build_module
import sereto.exceptions as exceptions_module
from sereto.exceptions import SeretoPathError, SeretoRuntimeError, SeretoValueError, handle_exceptions
from sereto.models.settings import RenderTool


def _run_build_with_failing_group(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def failing_build(**_: Any) -> None:
        raise error

    monkeypatch.setattr(build_module, "build_finding_group_dependencies", failing_build)
    target = SimpleNamespace(findings=SimpleNamespace(groups=[SimpleNamespace(uname="finding_group_sqli")]))
    build_module.build_target_dependencies.raw_function(  # type: ignore[attr-defined]
        project=None, target=target, version=None, intermediate_format=None
    )


def test_build_wraps_non_sereto_exception_with_context(monkeypatch: pytest.MonkeyPatch) -> None:
    # TemplateSyntaxError cannot be constructed from a single string; it used to surface as a bare TypeError
    error = TemplateSyntaxError("unexpected end of template", lineno=3)

    with pytest.raises(SeretoRuntimeError) as exc_info:
        _run_build_with_failing_group(monkeypatch, error)

    message = str(exc_info.value)
    assert "finding_group_sqli" in message
    assert "TemplateSyntaxError" in message
    assert "unexpected end of template" in message
    assert exc_info.value.__cause__ is error


def test_build_preserves_sereto_exception_type(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SeretoValueError) as exc_info:
        _run_build_with_failing_group(monkeypatch, SeretoValueError("undefined variable 'images'"))

    assert str(exc_info.value) == "Failed to build finding group 'finding_group_sqli': undefined variable 'images'"


def test_handle_exceptions_shows_message_of_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(exceptions_module.logger, "error", lambda msg, *args: messages.append(msg.format(*args)))

    @handle_exceptions
    def failing() -> None:
        raise ValueError("time data '2026-01-11' does not match format '%d-%b-%Y'")

    with pytest.raises(SystemExit):
        failing()

    assert messages == [
        "Unexpected error occurred: ValueError: time data '2026-01-11' does not match format '%d-%b-%Y'"
    ]


def test_handle_exceptions_without_message_shows_type_only(monkeypatch: pytest.MonkeyPatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(exceptions_module.logger, "error", lambda msg, *args: messages.append(msg.format(*args)))

    @handle_exceptions
    def failing() -> None:
        raise EOFError

    with pytest.raises(SystemExit):
        failing()

    assert messages == ["Unexpected error occurred: EOFError"]


def test_render_tool_missing_command_names_the_command() -> None:
    tool = RenderTool(name="missing", command="sereto-nonexistent-tool-xyz", args=[])

    with pytest.raises(SeretoPathError, match="'sereto-nonexistent-tool-xyz' not found"):
        tool.run()


def test_render_tool_existing_command_still_runs() -> None:
    tool = RenderTool(name="python", command=sys.executable, args=["-c", "print('ok')"])

    assert tool.run().strip() == b"ok"
