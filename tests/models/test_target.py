import pytest
from pydantic import TypeAdapter, ValidationError

from sereto.enums import Environment, TargetExposure
from sereto.models.config import VersionConfigModel
from sereto.models.target import (
    AnyTargetModel,
    TargetDastModel,
    TargetMobileModel,
    TargetModel,
    TargetSastModel,
    parse_target_model,
)

# Test context with categories to avoid loading settings
TEST_CONTEXT = {
    "categories": [
        "dast",
        "sast",
        "mobile",
        "scenario",
        "infrastructure",
        "rd",
        "portal",
        "cicd",
        "kubernetes",
        "generic",
    ]
}


@pytest.mark.parametrize(
    "category,extra,expected",
    [
        ("dast", {"code_origin": "archive"}, TargetDastModel),
        ("sast", {"dst_ips_dynamic": True}, TargetSastModel),
        ("mobile", {"code_origin": "archive"}, TargetMobileModel),
        ("portal", {"plugin_value": {"enabled": True}}, TargetModel),
    ],
)
def test_target_adapter_selects_category_and_preserves_extras(category, extra, expected):
    data = {"category": category, "name": "App", **extra}
    target = TypeAdapter(AnyTargetModel).validate_python(data, context=TEST_CONTEXT)
    assert type(target) is expected
    for key, value in extra.items():
        assert getattr(target, key) == value


def test_target_adapter_normalizes_existing_base_model():
    base = TargetModel.model_validate({"category": "dast", "name": "App", "internal": True}, context=TEST_CONTEXT)
    target = parse_target_model(base, context=TEST_CONTEXT)
    assert type(target) is TargetDastModel
    assert target.exposure == TargetExposure.internal
    assert base.model_extra == {"internal": True}


def test_invalid_target_items_raise_validation_error():
    with pytest.raises(ValidationError):
        VersionConfigModel.model_validate(
            {"id": "PRJ", "name": "Project", "version_description": "Initial", "targets": [1]},
            context=TEST_CONTEXT,
        )


def test_invalid_exposure_with_internal_raises_validation_error():
    with pytest.raises(ValidationError):
        TargetDastModel.model_validate(
            {"category": "dast", "name": "App", "internal": True, "exposure": 1}, context=TEST_CONTEXT
        )


def test_migrate_internal_true_to_exposure():
    """Test that internal=True is migrated to exposure=internal."""
    data = {
        "category": "dast",
        "name": "WebApp",
        "internal": True,
    }
    original = data.copy()
    model = TargetDastModel.model_validate(data, context=TEST_CONTEXT)
    assert model.exposure == TargetExposure.internal
    assert data == original


def test_migrate_internal_false_to_exposure():
    """Test that internal=False is migrated to exposure=external."""
    data = {
        "category": "dast",
        "name": "WebApp",
        "internal": False,
    }
    model = TargetDastModel.model_validate(data, context=TEST_CONTEXT)
    assert model.exposure == TargetExposure.external


def test_exposure_field_takes_precedence_when_consistent():
    """Test that when both fields exist and are consistent, exposure is kept."""
    data = {
        "category": "dast",
        "name": "WebApp",
        "internal": True,
        "exposure": TargetExposure.internal,
    }
    model = TargetDastModel.model_validate(data, context=TEST_CONTEXT)
    assert model.exposure == TargetExposure.internal


def test_exposure_field_without_internal():
    """Test that exposure field works without internal field."""
    data = {
        "category": "dast",
        "name": "WebApp",
        "exposure": TargetExposure.external,
    }
    model = TargetDastModel.model_validate(data, context=TEST_CONTEXT)
    assert model.exposure == TargetExposure.external


def test_conflicting_internal_true_exposure_external_raises_error():
    """Test that conflicting values raise a ValidationError."""
    data = {
        "category": "dast",
        "name": "WebApp",
        "internal": True,
        "exposure": "external",
    }
    with pytest.raises(ValidationError, match="Conflicting values"):
        TargetDastModel.model_validate(data, context=TEST_CONTEXT)


def test_conflicting_internal_false_exposure_internal_raises_error():
    """Test that conflicting values raise a ValidationError."""
    data = {
        "category": "dast",
        "name": "WebApp",
        "internal": False,
        "exposure": "internal",
    }
    with pytest.raises(ValidationError, match="Conflicting values"):
        TargetDastModel.model_validate(data, context=TEST_CONTEXT)


def test_migration_preserves_other_fields():
    """Test that migration doesn't affect other fields."""
    data = {
        "category": "dast",
        "name": "WebApp",
        "internal": True,
        "dst_ips_dynamic": True,
        "ip_filtering": True,
        "authentication": True,
        "waf_present": True,
        "environment": Environment.production,
    }
    model = TargetDastModel.model_validate(data, context=TEST_CONTEXT)
    assert model.exposure == TargetExposure.internal
    assert model.dst_ips_dynamic is True
    assert model.ip_filtering is True
    assert model.authentication is True
    assert model.waf_present is True
    assert model.environment == Environment.production


def test_no_internal_field_uses_default_exposure():
    """Test that without internal field, the default exposure value is used."""
    data = {
        "category": "dast",
        "name": "WebApp",
    }
    model = TargetDastModel.model_validate(data, context=TEST_CONTEXT)
    assert model.exposure == TargetExposure.external  # Default value


def test_model_dict_excludes_internal_field():
    """Test that the internal field is removed after migration."""
    data = {
        "category": "dast",
        "name": "WebApp",
        "internal": True,
    }
    model = TargetDastModel.model_validate(data, context=TEST_CONTEXT)
    # The internal field should not be present in the model
    assert not hasattr(model, "internal")
    # Check that model_dump doesn't include 'internal'
    dumped = model.model_dump()
    assert "internal" not in dumped
    assert dumped["exposure"] == TargetExposure.internal
