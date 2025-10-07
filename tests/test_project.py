import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.project import Project


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    # Minimal project structure
    (tmp_path / ".sereto").write_text("")
    (tmp_path / "config.json").write_text("{}")
    return tmp_path


@pytest.fixture
def project(project_root: Path) -> Project:
    return Project(_project_path=project_root)  # bypass path discovery


@pytest.mark.parametrize("rel", ["", ".", Path(""), Path(".")])
def test_ensure_dir_returns_root_for_empty_and_dot(project: Project, project_root: Path, rel):
    result = project.ensure_dir(rel)
    assert result == project_root
    assert result.is_dir()


def test_ensure_dir_creates_single_level_dir(project: Project, project_root: Path):
    target = "pdf"
    dest = project.ensure_dir(target)
    assert dest == (project_root / target).resolve()
    assert dest.is_dir()
    # idempotent
    again = project.ensure_dir(target)
    assert again == dest
    assert dest.is_dir()


def test_ensure_dir_creates_nested_directories(project: Project, project_root: Path):
    rel = "reports/html/assets"
    dest = project.ensure_dir(rel)
    assert dest == (project_root / rel).resolve()
    assert dest.is_dir()
    # parents created
    assert (project_root / "reports").is_dir()
    assert (project_root / "reports" / "html").is_dir()


def test_ensure_dir_with_path_object(project: Project, project_root: Path):
    rel = Path("data/output")
    dest = project.ensure_dir(rel)
    assert dest == (project_root / rel).resolve()
    assert dest.is_dir()


def test_ensure_dir_absolute_path_rejected(project: Project, tmp_path: Path):
    abs_path = tmp_path / "something"
    with pytest.raises(SeretoValueError, match="relative_path must be relative"):
        project.ensure_dir(abs_path)


@pytest.mark.parametrize("rel", ["../outside", "../../escape", Path("..") / "evil"])
def test_ensure_dir_parent_traversal_outside_root(project: Project, rel):
    with pytest.raises(SeretoValueError, match="points outside the project root"):
        project.ensure_dir(rel)


def test_ensure_dir_parent_traversal_inside_root(project: Project, project_root: Path):
    # Path resolves back to root (creates no directories)
    dest = project.ensure_dir("subdir/..")
    assert dest == project_root
    assert not (project_root / "subdir").exists()


def test_ensure_dir_existing_file_conflict(project: Project, project_root: Path):
    conflict = project_root / "report"
    conflict.write_text("not a dir")
    with pytest.raises(SeretoPathError, match="non-directory object"):
        project.ensure_dir("report")


def test_ensure_dir_existing_directory_no_error(project: Project, project_root: Path):
    d = project_root / "keep"
    d.mkdir()
    before_mtime = d.stat().st_mtime
    result = project.ensure_dir("keep")
    after_mtime = d.stat().st_mtime
    assert result == d
    # Should not recreate (mtime unchanged or very close)
    assert before_mtime == after_mtime


def test_ensure_dir_normalizes_dot_segments(project: Project, project_root: Path):
    dest = project.ensure_dir("a/./b/../c")
    # a/./b/../c => a/c
    expected = (project_root / "a" / "c").resolve()
    assert dest == expected
    assert expected.is_dir()


def test_ensure_dir_trailing_slash_like_input(project: Project, project_root: Path):
    dest = project.ensure_dir("logs/")
    assert dest == (project_root / "logs").resolve()
    assert dest.is_dir()


def test_ensure_dir_multiple_calls_consistent(project: Project):
    first = project.ensure_dir("alpha/beta")
    second = project.ensure_dir("alpha/beta")
    third = project.ensure_dir(Path("alpha") / "beta")
    assert first == second == third
    assert first.is_dir()


def test_ensure_dir_returns_resolved_absolute_path(project: Project, project_root: Path):
    dest = project.ensure_dir("x/y")
    assert dest.is_absolute()
    assert dest == (project_root / "x" / "y").resolve()


def test_ensure_dir_does_not_create_extra_unrelated_dirs(project: Project, project_root: Path):
    project.ensure_dir("only/this/path")
    existing = {p.relative_to(project_root) for p in project_root.rglob("*")}
    # Ensure no stray sibling of 'only'
    assert Path("only") in existing
    assert all(not str(p).startswith("unexpected") for p in existing)


def test_ensure_dir_validation_error_wrong_type(project: Project):
    with pytest.raises(ValidationError):
        project.ensure_dir(123)  # type: ignore[arg-type]


def test_ensure_dir_unicode_and_spaces(project: Project, project_root: Path):
    rel = "data/Δelta folder/π"
    dest = project.ensure_dir(rel)
    assert dest == (project_root / rel).resolve()
    assert dest.is_dir()


def test_ensure_dir_symlink_in_path(project: Project, project_root: Path):
    # Create a symlink inside project and ensure expansion still stays inside
    real_dir = project_root / "real"
    real_dir.mkdir()
    symlink = project_root / "link"
    symlink.symlink_to(real_dir, target_is_directory=True)
    target = project.ensure_dir("link/subdir")
    assert target == (real_dir / "subdir").resolve()
    assert target.is_dir()


def test_ensure_dir_path_collision_file_then_dir(project: Project, project_root: Path):
    # Create a file at 'temp', expect failure, then remove and succeed
    file_path = project_root / "temp"
    file_path.write_text("collision")
    with pytest.raises(SeretoPathError):
        project.ensure_dir("temp")
    file_path.unlink()
    dest = project.ensure_dir("temp")
    assert dest.is_dir()


def test_ensure_dir_deep_nesting(project: Project, project_root: Path):
    rel = "/".join(f"lvl{i}" for i in range(1, 11))
    dest = project.ensure_dir(rel)
    assert dest == (project_root / rel).resolve()
    assert dest.is_dir()
    # All intermediate dirs exist
    for i in range(1, 11):
        assert (project_root / "/".join(f"lvl{j}" for j in range(1, i + 1))).is_dir()


def test_ensure_dir_does_not_modify_project_root_permissions(project: Project, project_root: Path):
    orig_mode = oct(project_root.stat().st_mode)
    project.ensure_dir("newdir")
    new_mode = oct(project_root.stat().st_mode)
    assert orig_mode == new_mode


def test_ensure_dir_no_side_effect_on_failure(project: Project, project_root: Path):
    before = set(project_root.iterdir())
    with pytest.raises(SeretoValueError):
        project.ensure_dir("../escape_dir")
    after = set(project_root.iterdir())
    assert before == after


def test_ensure_dir_creates_only_last_component_when_parents_exist(project: Project, project_root: Path):
    base = project_root / "base" / "sub"
    base.mkdir(parents=True)
    dest = project.ensure_dir("base/sub/newleaf")
    assert dest == (base / "newleaf").resolve()
    assert dest.is_dir()
    assert base.is_dir()


def test_ensure_dir_handles_repeated_slashes(project: Project, project_root: Path):
    dest = project.ensure_dir("multi///slash///path")
    assert dest == (project_root / "multi" / "slash" / "path").resolve()
    assert dest.is_dir()


def test_ensure_dir_root_not_changed_on_root_requests(project: Project, project_root: Path):
    inode_before = os.stat(project_root).st_ino
    project.ensure_dir("")
    project.ensure_dir(".")
    inode_after = os.stat(project_root).st_ino
    assert inode_before == inode_after
