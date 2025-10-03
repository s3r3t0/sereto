import re
import tomllib

import pytest

from sereto.enums import Risk
from sereto.models.finding import SubFindingFrontmatterModel
from sereto.models.locator import IpLocatorModel, UrlLocatorModel

# ------ SubFindingFrontmatterModel.dumps_toml() tests ------


def parse_toml(toml_str: str) -> dict:
    return tomllib.loads(toml_str)


def test_dumps_toml_basic_all_fields():
    model = SubFindingFrontmatterModel(
        name="SQL Injection",
        risk=Risk.high,
        category="dast",
        variables={"param": "id", "count": 3},
        template_path="web/sql_injection.md",
        locators=[
            UrlLocatorModel(type="url", value="http://example.com/"),
            IpLocatorModel(type="ip", value="192.168.1.1"),
        ],
    )
    dumped = model.dumps_toml()
    data = parse_toml(dumped)

    assert data["name"] == "SQL Injection"
    assert data["risk"] == Risk.high
    assert data["category"] == "dast"
    assert data["locators"] == [
        {"type": "url", "value": "http://example.com/"},
        {"type": "ip", "value": "192.168.1.1"},
    ]
    assert data["template_path"] == "web/sql_injection.md"
    assert data["variables"] == {"param": "id", "count": 3}


def test_dumps_toml_filters_none_variables():
    model = SubFindingFrontmatterModel(
        name="Missing Headers",
        risk=Risk.medium,
        category="dast",
        variables={"header": "X-Frame-Options", "present": None, "enabled": True},
        template_path=None,
        locators=[],
    )
    dumped = model.dumps_toml()
    data = parse_toml(dumped)

    assert "template_path" not in data  # not provided
    # None value filtered out
    assert data["variables"] == {"header": "X-Frame-Options", "enabled": True}
    # Ensure the removed key really not serialized
    assert "present" not in dumped


def test_dumps_toml_no_variables_or_template_path_keys_absent_when_empty():
    model = SubFindingFrontmatterModel(
        name="Info Finding",
        risk=Risk.low,
        category="dast",
        variables={},  # empty
        template_path=None,
        locators=[],
    )
    dumped = model.dumps_toml()
    data = parse_toml(dumped)

    assert "variables" not in data
    assert "template_path" not in data
    assert set(data.keys()) == {"name", "risk", "category", "locators"}


def test_dumps_toml_locators_empty_list_always_present():
    model = SubFindingFrontmatterModel(
        name="CSRF",
        risk=Risk.medium,
        category="dast",
        variables={},
        locators=[],
    )
    dumped = model.dumps_toml()
    data = parse_toml(dumped)
    assert "locators" in data and data["locators"] == []


def test_dumps_toml_risk_is_serialized_as_plain_value():
    model = SubFindingFrontmatterModel(
        name="Privilege Escalation",
        risk=Risk.critical,
        category="dast",
        variables={},
        locators=[],
    )
    dumped = model.dumps_toml()
    data = parse_toml(dumped)
    assert data["risk"] == Risk.critical
    # Ensure not quoted twice or transformed unexpectedly
    assert re.search(r"risk\s*=\s*\"critical\"", dumped)


@pytest.mark.parametrize(
    "variables",
    [
        {"a": 1, "b": 2},
        {"flag": True, "text": "value"},
        {"listy": ["x", "y", "z"]},
        {"mixed": ["a", 1, True]},
    ],
)
def test_dumps_toml_variable_types_preserved(variables):
    model = SubFindingFrontmatterModel(
        name="Var Test",
        risk="low",
        category="Generic",
        variables=variables,
        locators=[],
    )
    data = parse_toml(model.dumps_toml())
    if variables:
        assert data["variables"] == variables
    else:
        assert "variables" not in data


def test_dumps_toml_trailing_newline_present():
    model = SubFindingFrontmatterModel(
        name="Trailing",
        risk=Risk.info,
        category="infra",
        variables={},
        locators=[],
    )
    dumped = model.dumps_toml()
    assert dumped.endswith("\n")


def test_dumps_toml_is_idempotent():
    model = SubFindingFrontmatterModel(
        name="Idempotent",
        risk=Risk.high,
        category="sast",
        variables={"k1": "v1", "k2": 2},
        template_path="test/path.md",
        locators=[],
    )
    first = model.dumps_toml()
    second = model.dumps_toml()
    assert parse_toml(first) == parse_toml(second)


def test_dumps_toml_does_not_mutate_instance():
    vars_in = {"k": "v", "n": 1, "none": None}
    model = SubFindingFrontmatterModel(
        name="No Mut",
        risk="medium",
        category="Keep",
        variables=dict(vars_in),
        locators=[],
    )
    _ = model.dumps_toml()
    # Internal variables dict should remain unchanged (including None entry)
    assert model.variables == vars_in


def test_dumps_toml_variable_none_all_removed_results_no_variables_section():
    model = SubFindingFrontmatterModel(
        name="All None",
        risk=Risk.low,
        category="sast",
        variables={"a": None, "b": None},
        locators=[],
    )
    dumped = model.dumps_toml()
    data = parse_toml(dumped)
    assert "variables" not in data


def test_dumps_toml_large_variable_set():
    variables = {f"k{i}": i for i in range(30)}
    model = SubFindingFrontmatterModel(
        name="Large",
        risk=Risk.info,
        category="dast",
        variables=variables,
        locators=[],
    )
    data = parse_toml(model.dumps_toml())
    assert data["variables"] == variables


# ------ end SubFindingFrontmatterModel.dumps_toml() tests ------
