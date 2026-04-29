import tarfile
from pathlib import Path
from unittest.mock import patch

from sereto.config import Config, VersionConfig
from sereto.logging import logger
from sereto.models.version import ProjectVersion, SeretoVersion
from sereto.source_archive import GitIgnoreSpec, create_source_archive


def _return_path(path: Path) -> Path:
    return path


def _make_config(project_root: Path) -> Config:
    config_path = project_root / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    version = ProjectVersion.from_str("v1.0")
    version_config = VersionConfig(
        version=version,
        id="PRJ",
        name="Project",
        version_description="Initial",
        risk_due_dates={},
        targets=[],
        dates=[],
        people=[],
    )
    return Config(
        sereto_version=SeretoVersion.from_str("0.7.6"),
        version_configs={version: version_config},
        path=config_path,
        risk_due_dates={},
    )


def test_create_source_archive_respects_seretoignore_and_skips_symlinks(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    (project_root / ".sereto").write_text("", encoding="utf-8")
    (project_root / ".seretoignore").write_text("*.log\nignored_dir/\n", encoding="utf-8")
    (project_root / "keep.txt").write_text("keep", encoding="utf-8")
    (project_root / "skip.log").write_text("skip", encoding="utf-8")
    ignored_dir = project_root / "ignored_dir"
    ignored_dir.mkdir()
    (ignored_dir / "nested.txt").write_text("nested", encoding="utf-8")
    (project_root / "link.txt").symlink_to(project_root / "keep.txt")

    config = _make_config(project_root)

    with patch("sereto.source_archive.encrypt_file", side_effect=_return_path):
        archive_path = create_source_archive(project_path=project_root, config=config)

    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            names = archive.getnames()
    finally:
        archive_path.unlink()

    assert "PRJ/keep.txt" in names
    assert "PRJ/.sereto" in names
    assert "PRJ/config.json" in names
    assert "PRJ/.seretoignore" in names
    assert "PRJ/skip.log" not in names
    assert "PRJ/ignored_dir/nested.txt" not in names
    assert "PRJ/link.txt" not in names
