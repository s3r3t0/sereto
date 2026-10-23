"""Frozen copies of a project, so that long-running operations (rendering) are not affected by concurrent changes."""

import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import Self

from sereto.project import Project

# Not needed for rendering (and potentially large), relative to the project root
_EXCLUDED: frozenset[Path] = frozenset({Path(".git"), Path("pdf")})

# Render outputs which are copied back into the project after the render finishes
_BUILD_DIR = Path(".build")
_GENERATED_LAYOUTS_DIR = Path("layouts/generated")
_PDF_DIR = Path("pdf")


class ProjectSnapshot:
    """Context manager rendering from a temporary copy of a project.

    On enter, the project directory is copied into a temporary directory (excluding `.git` and `pdf`), so any change
    made to the original project while the snapshot is in use does not affect it. On exit, the render outputs are
    propagated back into the original project and the copy is removed:

    - generated PDFs (`pdf/`) are copied, overwriting existing files,
    - the build directory (`.build/`) is merged, so build tools can reuse their auxiliary files next time,
    - newly generated layouts (`layouts/generated/`) are copied, without overwriting existing ones (matching the
      behaviour of a regular render, which never overwrites generated layouts).
    """

    def __init__(self, project: Project) -> None:
        self.original = project
        self._tmp: TemporaryDirectory[str] | None = None  # Temporary directory holding the project copy
        self._project: Project | None = None  # Project's copy
        self._path: Path | None = None  # Path to the temporary copy of the project

    @property
    def project(self) -> Project:
        """The project instance backed by the temporary copy."""
        if self._project is None:
            raise RuntimeError("snapshot is not active")
        return self._project

    @property
    def path(self) -> Path:
        """Root of the temporary copy (remains available after exit, to translate paths of the outputs)."""
        if self._path is None:
            raise RuntimeError("snapshot was not entered")
        return self._path

    def __enter__(self) -> Self:
        self._tmp = TemporaryDirectory(prefix="sereto-render-")
        try:
            # keep the directory name, in case anything derives information from it
            dst = Path(self._tmp.name) / self.original.path.name
            _copy_project(self.original.path, dst)
            self._path = dst
            self._project = Project(_settings=self.original.settings, _project_path=dst)
        except BaseException:
            self._tmp.cleanup()
            self._tmp = None
            raise
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        try:
            # Propagate outputs even on failure
            self._sync_back()
        finally:
            if self._tmp is not None:
                self._tmp.cleanup()
            self._tmp = None
            self._project = None

    def original_path(self, path: Path) -> Path:
        """Translate a path inside the snapshot to the corresponding path in the original project."""
        return self.original.path / path.relative_to(self.path)

    def _sync_back(self) -> None:
        if self._project is None:
            return
        src, dst = self._project.path, self.original.path

        # Update the original project's directories which were affected by the render

        if (pdf_src := src / _PDF_DIR).is_dir():
            for file in (f for f in pdf_src.rglob("*") if f.is_file()):
                target = dst / file.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, target)

        if (build_src := src / _BUILD_DIR).is_dir():
            shutil.copytree(build_src, dst / _BUILD_DIR, symlinks=True, dirs_exist_ok=True)

        if (generated_src := src / _GENERATED_LAYOUTS_DIR).is_dir():
            for file in (f for f in generated_src.rglob("*") if f.is_file()):
                target = dst / file.relative_to(src)
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, target)


def _copy_project(src: Path, dst: Path) -> None:
    """Copy the project directory, preserving symlinks (the source archive skips them, so they must stay links)."""

    def ignore(directory: str, names: list[str]) -> set[str]:
        rel_dir = Path(directory).relative_to(src)
        return {name for name in names if rel_dir / name in _EXCLUDED}

    shutil.copytree(src, dst, symlinks=True, ignore=ignore)

    # Relative symlinks pointing outside of the project would break in the copy; point them to the original target
    src_resolved = src.resolve()
    for link in (p for p in dst.rglob("*") if p.is_symlink()):
        target = Path(os.readlink(link))
        if target.is_absolute():
            continue
        original_target = (src / link.relative_to(dst)).parent / target
        if not original_target.resolve().is_relative_to(src_resolved):
            link.unlink()
            link.symlink_to(original_target.resolve())
