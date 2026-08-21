from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

from click.testing import CliRunner

from sereto.cli.cli import finding_validate
from sereto.config import Config
from sereto.project import Project


def test_finding_validate_checks_every_version() -> None:
    first_findings = Mock()
    first_findings.validate_vars.return_value = 1
    second_findings = Mock()
    second_findings.validate_vars.return_value = 2
    config = Mock()
    config.versions = ["v1.0", "v1.1"]
    config.at_version.side_effect = [
        SimpleNamespace(targets=[SimpleNamespace(findings=first_findings)]),
        SimpleNamespace(targets=[SimpleNamespace(findings=second_findings)]),
    ]
    project = Project(_config=cast(Config, config))

    result = CliRunner().invoke(finding_validate, obj=project)

    assert result.exit_code == 0, result.output
    assert "Validated variables for 3 findings." in result.output
    first_findings.validate_vars.assert_called_once_with()
    second_findings.validate_vars.assert_called_once_with()
