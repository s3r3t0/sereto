import json

import pytest
from semver import Version

from sereto.models.config import ConfigModel, VersionConfigModel
from sereto.models.version import ProjectVersion, SeretoVersion


class TestSeretoVersion:
    @pytest.mark.parametrize("input", ["0.0.1", "1.0.0", "2.3.45"])
    def test_construct_valid_from_str(self, input):
        version = SeretoVersion(input)
        version_from_str = SeretoVersion.from_str(input)
        assert str(version) == str(version_from_str) == input

    def test_construct_valid_from_version(self):
        SeretoVersion(Version(1, 2, 3))

    @pytest.mark.parametrize(
        "input",
        [
            "1.0",
            "1",
            "",
            "v1.0.0",
            "1.0.0-beta",
            "1.2.3-pre.2+build.4",
            "1.0.0+build",
            "-1.0.0",
            None,
            Version(1, 2, 3, "beta"),
        ],
    )
    def test_construct_invalid(self, input):
        with pytest.raises((ValueError, TypeError)):
            SeretoVersion(input)
        if isinstance(input, str):
            with pytest.raises((ValueError, TypeError)):
                SeretoVersion.from_str(input)

    @pytest.mark.parametrize("a,b", [(SeretoVersion("1.0.0"), '"1.0.0"'), (SeretoVersion("2.3.45"), '"2.3.45"')])
    def test_serialize(self, a, b):
        assert a.model_dump_json() == b

    @pytest.mark.parametrize("a,b", [(SeretoVersion("1.0.0"), '"1.0.0"'), (SeretoVersion("2.3.45"), '"2.3.45"')])
    def test_deserialize(self, a, b):
        assert a == SeretoVersion.model_validate_json(b)

    @pytest.mark.parametrize("a,b", [("1.0.0", "2.0.0"), ("1.0.0", "1.1.0"), ("1.0.0", "1.0.1"), ("1.0.9", "1.0.10")])
    def test_lt_gt(self, a, b):
        assert SeretoVersion(a) < SeretoVersion(b)
        assert SeretoVersion(b) > SeretoVersion(a)

    @pytest.mark.parametrize("a,b", [("1.0.0", "1.0.0"), ("3.5.79", "3.5.79")])
    def test_eq(self, a, b):
        assert SeretoVersion(a) == SeretoVersion(b)

    @pytest.mark.parametrize("a,b", [("1.0.0", "1.0.1"), ("2.3.4", "2.3.45")])
    def test_not_eq(self, a, b):
        assert SeretoVersion(a) != SeretoVersion(b)


class TestProjectVersion:
    @pytest.mark.parametrize("input", ["v1.0", "v2.0", "v2.1"])
    def test_construct_valid_from_str(self, input):
        version = ProjectVersion(input)
        version_from_str = ProjectVersion.from_str(input)
        assert str(version) == str(version_from_str) == input

    def test_construct_valid_from_version(self):
        ProjectVersion(Version(2, 1))

    @pytest.mark.parametrize("input", ["1.0.0", "v1.0.0", "v1", "v1.2-beta", "v1.2+build", None, Version(1, 2, 3)])
    def test_construct_invalid(self, input):
        with pytest.raises((ValueError, TypeError)):
            ProjectVersion(input)
        if isinstance(input, str):
            with pytest.raises((ValueError, TypeError)):
                ProjectVersion.from_str(input)

    @pytest.mark.parametrize("a,b", [(ProjectVersion("v1.0"), '"v1.0"'), (ProjectVersion("v2.3"), '"v2.3"')])
    def test_serialize(self, a, b):
        assert a.model_dump_json() == b

    @pytest.mark.parametrize("a,b", [(ProjectVersion("v1.0"), '"v1.0"'), (ProjectVersion("v2.3"), '"v2.3"')])
    def test_deserialize(self, a, b):
        assert a == ProjectVersion.model_validate_json(b)

    @pytest.mark.parametrize("a,b", [("v1.0", "v1.1"), ("v1.0", "v2.0"), ("v1.9", "v1.10")])
    def test_lt_gt(self, a, b):
        assert ProjectVersion(a) < ProjectVersion(b)
        assert ProjectVersion(b) > ProjectVersion(a)

    @pytest.mark.parametrize("a,b", [("v1.0", "v1.0"), ("v2.5", "v2.5")])
    def test_eq(self, a, b):
        assert ProjectVersion(a) == ProjectVersion(b)

    @pytest.mark.parametrize("a,b", [("v1.0", "v1.1"), ("v2.3", "v2.30")])
    def test_not_eq(self, a, b):
        assert ProjectVersion(a) != ProjectVersion(b)


@pytest.mark.parametrize("model", [SeretoVersion, ProjectVersion])
def test_from_str_rejects_semver_objects(model):
    with pytest.raises(TypeError):
        model.from_str(Version(1, 2, 0))


def test_config_version_keys_survive_save_and_load(tmp_path):
    model = ConfigModel(
        sereto_version=SeretoVersion.from_str("0.9.0"),
        version_configs={
            ProjectVersion.from_str(version): VersionConfigModel(
                id="PRJ", name="Project", version_description="Initial"
            )
            for version in ("v1.0", "v2.0")
        },
    )
    path = tmp_path / "config.json"
    path.write_text(model.model_dump_json(), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["sereto_version"] == "0.9.0"
    assert list(data["version_configs"]) == ["v1.0", "v2.0"]
    restored = ConfigModel.load_from(path)
    assert restored == model
    assert restored.version_configs[ProjectVersion.from_str("v2.0")].name == "Project"
