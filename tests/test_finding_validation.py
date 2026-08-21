from pathlib import Path
from typing import Any

import pytest

from sereto.enums import Risk
from sereto.exceptions import SeretoValueError
from sereto.finding import Findings, SubFinding


def write_template(tmp_path: Path, source: str) -> tuple[Path, Path]:
    templates = tmp_path / "templates"
    template = templates / "dast" / "example.md.j2"
    template.parent.mkdir(parents=True)
    template.write_text(source, encoding="utf-8")
    return templates, template


def make_subfinding(template: Path, variables: dict[str, Any]) -> SubFinding:
    return SubFinding(
        name="Example",
        risk=Risk.low,
        vars=variables,
        path=template.parent / "example.md.j2",
        template=template,
    )


def schema_template() -> str:
    return """+++
name = "Example"
risk = "low"

[[variables]]
name = "count"
description = "The count"
required = true
type = "integer"

[[variables]]
name = "enabled"
description = "Whether the finding applies"
type = "boolean"

[[variables]]
name = "labels"
description = "Labels for the finding"
list = true
+++

{{ f.vars.count }}
"""


@pytest.mark.parametrize(
    ("variables", "message"),
    [
        ({}, "missing required variable"),
        ({"count": "one"}, "variable must be an integer value"),
        ({"count": True}, "variable must be an integer value"),
        ({"count": 1, "enabled": "yes"}, "variable must be a boolean value"),
        ({"count": 1, "labels": "label"}, "variable must be a list"),
        ({"count": 1, "labels": ["label", 2]}, "list items must be string values"),
        ({"count": 1, "typo": "value"}, "unknown variable"),
    ],
)
def test_validate_vars_rejects_invalid_schema_values(tmp_path: Path, variables: dict[str, Any], message: str) -> None:
    _, template = write_template(tmp_path, schema_template())

    with pytest.raises(SeretoValueError, match=message):
        make_subfinding(template, variables).validate_vars()


def test_validate_vars_allows_legacy_template_references(tmp_path: Path) -> None:
    _, template = write_template(
        tmp_path,
        """+++
name = "Example"
risk = "low"
+++

{{ f.vars.plugin_generated }}
""",
    )

    make_subfinding(template, {"plugin_generated": True}).validate_vars()


def test_validate_vars_rejects_empty_required_list(tmp_path: Path) -> None:
    _, template = write_template(
        tmp_path,
        """+++
name = "Example"
risk = "low"

[[variables]]
name = "labels"
description = "Labels for the finding"
required = true
list = true
+++
""",
    )

    with pytest.raises(SeretoValueError, match="required list variable must not be empty"):
        make_subfinding(template, {"labels": []}).validate_vars()


def test_load_from_rejects_invalid_persisted_variables(tmp_path: Path) -> None:
    templates, _ = write_template(tmp_path, schema_template())
    finding = tmp_path / "finding.md.j2"
    finding.write_text(
        """+++
name = "Example"
risk = "low"
category = "dast"
template_path = "dast/example.md.j2"

[variables]
count = "one"
+++
""",
        encoding="utf-8",
    )

    with pytest.raises(SeretoValueError, match="variable must be an integer value"):
        SubFinding.load_from(path=finding, templates=templates)


def test_add_from_template_rejects_invalid_values_before_writing(tmp_path: Path) -> None:
    templates, template = write_template(tmp_path, schema_template())
    target_dir = tmp_path / "target"
    findings_dir = target_dir / "findings"
    findings_dir.mkdir(parents=True)
    findings = Findings(groups=[], target_dir=target_dir, target_locators=[])

    with pytest.raises(SeretoValueError, match="unknown variable"):
        findings.add_from_template(
            templates=templates,
            template_path=template,
            category="dast",
            variables={"count": 1, "typo": "value"},
        )

    assert list(findings_dir.iterdir()) == []
