# type: ignore

from unittest.mock import patch

import pytest
from click.testing import CliRunner
from git import Repo
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from sereto.cli.cli import new as sereto_new


@pytest.fixture(scope="session")
def sereto_templates(tmp_path_factory):
    repo_url = "https://github.com/s3r3t0/templates"
    templates_path = tmp_path_factory.mktemp("templates")
    Repo.clone_from(url=repo_url, to_path=templates_path, depth=1)
    return templates_path


@pytest.fixture(autouse=True, scope="function")
def mock_input():
    with create_pipe_input() as pipe_input:
        with create_app_session(input=pipe_input, output=DummyOutput()):
            yield pipe_input


# @patch("sereto.models.settings.Settings.get_path")
# def test_sereto_new(mock_get_path, sereto_templates, tmp_path, mock_input):
#     projects_path = tmp_path / "projects"
#     projects_path.mkdir()

#     settings_path = tmp_path / "settings.json"
#     settings_path.write_text(f'{{"projects_path": "{projects_path}", "templates_path": "{sereto_templates}"}}')
#     mock_get_path.return_value = settings_path

#     runner = CliRunner()
#     mock_input.send_text("Test report\n")
#     result = runner.invoke(sereto_new, ["ABCD01"])
#     assert result.exit_code == 0
#     assert "Copying 'skel' directory" in result.output
