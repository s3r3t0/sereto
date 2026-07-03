import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

import sereto.models.settings as settings_module
from sereto.enums import FileFormat, Risk, TargetExposure
from sereto.models.settings import DEFAULT_RENDER_CONFIG, ConvertRecipe, Render, RenderRecipe, RenderTool, Settings


def _tool(name: str) -> RenderTool:
    return RenderTool(name=name, command=name, args=[])


def _render(**overrides) -> Render:
    data = {
        "report_recipes": [RenderRecipe(name="report", tools=["report-tool"], intermediate_format=FileFormat.tex)],
        "finding_group_recipes": [
            RenderRecipe(name="finding", tools=["finding-tool"], intermediate_format=FileFormat.tex)
        ],
        "sow_recipes": [RenderRecipe(name="sow", tools=["sow-tool"], intermediate_format=FileFormat.tex)],
        "target_recipes": [RenderRecipe(name="target", tools=["target-tool"], intermediate_format=FileFormat.tex)],
        "convert_recipes": [
            ConvertRecipe(
                name="convert",
                tools=["convert-tool"],
                input_format=FileFormat.md,
                output_format=FileFormat.tex,
            )
        ],
        "tools": [
            _tool("report-tool"),
            _tool("finding-tool"),
            _tool("sow-tool"),
            _tool("target-tool"),
            _tool("convert-tool"),
        ],
    }
    data.update(overrides)
    return Render(**data)


def test_default_render_config_is_valid():
    assert DEFAULT_RENDER_CONFIG.tools


def test_render_tool_run_prepends_current_python_bin_to_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("PATH", "/usr/bin")
    captured: dict[str, object] = {}

    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    python_link = venv_bin / "python"
    python_link.symlink_to(Path(sys.executable))
    monkeypatch.setattr(settings_module.sys, "executable", str(python_link))

    def fake_run(command, cwd=None, input=None, capture_output=None, env=None):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["input"] = input
        captured["capture_output"] = capture_output
        captured["env"] = env
        return subprocess.CompletedProcess(args=command, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    tool = RenderTool(name="pandoc", command="pandoc", args=["--version"])
    tool.run()

    env = captured["env"]
    assert isinstance(env, dict)
    assert env["PATH"].split(os.pathsep)[0] == str(venv_bin)


def test_render_rejects_duplicate_tool_names():
    with pytest.raises(ValidationError, match="tools with duplicate name detected"):
        _render(tools=[_tool("duplicate"), _tool("duplicate")])


def test_render_rejects_unknown_tool_in_target_recipe():
    with pytest.raises(ValidationError, match="unknown tools in recipe 'target'"):
        _render(
            target_recipes=[RenderRecipe(name="target", tools=["missing-tool"], intermediate_format=FileFormat.tex)]
        )


def test_render_rejects_unknown_tool_in_convert_recipe():
    with pytest.raises(ValidationError, match="unknown tools in recipe 'convert'"):
        _render(
            convert_recipes=[
                ConvertRecipe(
                    name="convert",
                    tools=["missing-tool"],
                    input_format=FileFormat.md,
                    output_format=FileFormat.tex,
                )
            ]
        )


def test_migrate_risk_due_dates_old_format(tmp_path: Path):
    """Test migration from old flat risk_due_dates format to new nested format."""
    # Old format: flat dict with risk keys
    old_format_data = {
        "projects_path": str(tmp_path / "projects"),
        "templates_path": str(tmp_path / "templates"),
        "risk_due_dates": {
            "critical": "P7D",
            "high": "P14D",
            "medium": "P30D",
            "low": "P90D",
        },
    }

    # Create the directories
    (tmp_path / "projects").mkdir()
    (tmp_path / "templates").mkdir()

    # Should successfully migrate
    settings = Settings(**old_format_data)

    # Verify it was migrated to new format
    assert isinstance(settings.risk_due_dates, dict)
    assert TargetExposure.internal in settings.risk_due_dates
    assert TargetExposure.external in settings.risk_due_dates

    # Both internal and external should have the same values from old format
    assert settings.risk_due_dates[TargetExposure.internal][Risk.critical] == timedelta(days=7)
    assert settings.risk_due_dates[TargetExposure.internal][Risk.high] == timedelta(days=14)
    assert settings.risk_due_dates[TargetExposure.external][Risk.critical] == timedelta(days=7)
    assert settings.risk_due_dates[TargetExposure.external][Risk.high] == timedelta(days=14)


def test_risk_due_dates_new_format_not_modified(tmp_path: Path):
    """Test that new format is not modified by migration."""
    # New format: nested dict with exposure -> risk keys
    new_format_data = {
        "projects_path": str(tmp_path / "projects"),
        "templates_path": str(tmp_path / "templates"),
        "risk_due_dates": {
            "internal": {
                "critical": "P10D",
                "high": "P30D",
                "medium": "P60D",
                "low": "P90D",
            },
            "external": {
                "critical": "P5D",
                "high": "P10D",
                "medium": "P30D",
                "low": "P90D",
            },
        },
    }

    # Create the directories
    (tmp_path / "projects").mkdir()
    (tmp_path / "templates").mkdir()

    # Should work without modification
    settings = Settings(**new_format_data)

    # Verify the values are preserved
    assert settings.risk_due_dates[TargetExposure.internal][Risk.critical] == timedelta(days=10)
    assert settings.risk_due_dates[TargetExposure.internal][Risk.high] == timedelta(days=30)
    assert settings.risk_due_dates[TargetExposure.external][Risk.critical] == timedelta(days=5)
    assert settings.risk_due_dates[TargetExposure.external][Risk.high] == timedelta(days=10)
