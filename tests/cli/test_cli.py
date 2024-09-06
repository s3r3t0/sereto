# type: ignore

from unittest.mock import patch

import pytest
from click.testing import CliRunner
from git import Repo

from sereto.cli.cli import new as sereto_new


@pytest.fixture(scope="session")
def sereto_templates(tmp_path_factory):
    repo_url = "https://github.com/s3r3t0/templates"
    templates_path = tmp_path_factory.mktemp("templates")
    Repo.clone_from(url=repo_url, to_path=templates_path, depth=1)
    return templates_path


@patch("sereto.models.settings.Settings.get_path")
def test_sereto_new(mock_get_path, sereto_templates, tmp_path):
    reports_path = tmp_path / "reports"
    reports_path.mkdir()

    settings_path = tmp_path / "settings.json"
    settings_path.write_text(f'{{"reports_path": "{reports_path}", "templates_path": "{sereto_templates}"}}')
    mock_get_path.return_value = settings_path

    runner = CliRunner()
    result = runner.invoke(sereto_new, ["ABCD01"], input="Report name\n")
    assert result.exit_code == 0
    assert "Copying 'skel' directory" in result.output
