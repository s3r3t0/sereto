import pytest
from pydantic import ValidationError

from sereto.enums import Environment, TargetExposure
from sereto.models.target import TargetDastModel


def test_migrate_internal_true_to_exposure():
    """Test that internal=True is migrated to exposure=internal."""
    data = {
        "category": "dast",
        "name": "WebApp",
        "internal": True,
    }
    model = TargetDastModel(**data)
    assert model.exposure == TargetExposure.internal


def test_migrate_internal_false_to_exposure():
    """Test that internal=False is migrated to exposure=external."""
    data = {
        "category": "dast",
        "name": "WebApp",
        "internal": False,
    }
    model = TargetDastModel(**data)
    assert model.exposure == TargetExposure.external


def test_exposure_field_takes_precedence_when_consistent():
    """Test that when both fields exist and are consistent, exposure is kept."""
    data = {
        "category": "dast",
        "name": "WebApp",
        "internal": True,
        "exposure": TargetExposure.internal,
    }
    model = TargetDastModel(**data)
    assert model.exposure == TargetExposure.internal


def test_exposure_field_without_internal():
    """Test that exposure field works without internal field."""
    data = {
        "category": "dast",
        "name": "WebApp",
        "exposure": TargetExposure.external,
    }
    model = TargetDastModel(**data)
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
        TargetDastModel(**data)


def test_conflicting_internal_false_exposure_internal_raises_error():
    """Test that conflicting values raise a ValidationError."""
    data = {
        "category": "dast",
        "name": "WebApp",
        "internal": False,
        "exposure": "internal",
    }
    with pytest.raises(ValidationError, match="Conflicting values"):
        TargetDastModel(**data)


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
    model = TargetDastModel(**data)
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
    model = TargetDastModel(**data)
    assert model.exposure == TargetExposure.external  # Default value


def test_model_dict_excludes_internal_field():
    """Test that the internal field is removed after migration."""
    data = {
        "category": "dast",
        "name": "WebApp",
        "internal": True,
    }
    model = TargetDastModel(**data)
    # The internal field should not be present in the model
    assert not hasattr(model, "internal")
    # Check that model_dump doesn't include 'internal'
    dumped = model.model_dump()
    assert "internal" not in dumped
    assert dumped["exposure"] == TargetExposure.internal
