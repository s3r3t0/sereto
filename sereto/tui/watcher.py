"""File-system watchers used by the TUI to detect changes to the active project and to the projects_path directory.

A [watchdog](https://github.com/gorakhargosh/watchdog) observers runs in a background thread and record changes in
files and directories. The TUI polls [`ProjectWatcher.consume`][sereto.tui.watcher.ProjectWatcher.consume] from its
main loop (every frame).
"""

import contextlib
import os
import threading
import time
from pathlib import Path

from watchdog.events import (
    EVENT_TYPE_CLOSED,
    EVENT_TYPE_CREATED,
    EVENT_TYPE_DELETED,
    EVENT_TYPE_MODIFIED,
    EVENT_TYPE_MOVED,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver, ObservedWatch

# Paths (relative to the project root) whose changes, including anything inside them, must not trigger a reload:
# - SeReTo writes to these while rendering, so every render would otherwise cause a reload,
# - these do not affect the project's data displayed in the TUI.
IGNORED_PATHS: tuple[Path, ...] = (
    Path(".build"),
    Path("pdf"),
    Path("layouts/generated"),
    Path(".git"),
    Path("includes"),
    Path("pictures"),
    Path("outputs"),
    Path("attachment_exclude"),
    Path(".vscode"),
    Path("AGENTS.md"),
)

# Only events that indicate an actual change.
_CHANGE_EVENTS = frozenset(
    {EVENT_TYPE_CREATED, EVENT_TYPE_DELETED, EVENT_TYPE_MODIFIED, EVENT_TYPE_MOVED, EVENT_TYPE_CLOSED}
)


class _ChangeEventHandler(FileSystemEventHandler):
    def __init__(self, watcher: "_DebouncedWatcher") -> None:
        super().__init__()
        self._watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type not in _CHANGE_EVENTS:
            return

        if event.is_directory and event.event_type == EVENT_TYPE_MODIFIED:
            # Watchdog reports a dir as "modified" alongside each create, delete, move and close-write event of an
            # entry in it (see .tox/py314/.../watchdog/observers/inotify.py, lines 140–195).
            # The entry's own event is handled, so the one on the dir is redundant.
            return

        paths = [event.src_path, event.dest_path] if event.dest_path else [event.src_path]
        if any(self._watcher.is_relevant(Path(os.fsdecode(p))) for p in paths):
            self._watcher.mark_dirty()


class _DebouncedWatcher:
    """Base for watchers recording changes from the observer thread and reporting them (debounced) to the TUI.

    Args:
        path: Directory to watch.
        debounce: Seconds without further events before the changes are reported. Editors and SeReTo itself often
            write a file in several steps, so this coalesces a burst of events into a single reload.
    """

    def __init__(self, path: Path, debounce: float = 0.2) -> None:
        self.path = path
        self.debounce = debounce
        # Lock protecting the dirty flag and last event timestamp.
        # Needed since the observer thread (calling `mark_dirty`) and the TUI main thread (calling `pending` and
        # `consume`) may access these attributes concurrently.
        self._lock = threading.Lock()
        self._dirty = False
        self._last_event = 0.0
        self._observer: BaseObserver | None = None

    def start(self) -> None:
        """Start watching in a background thread."""
        if self._observer is not None:
            return
        observer = Observer()
        self._schedule(observer)
        observer.daemon = True
        observer.start()
        self._observer = observer

    def _schedule(self, observer: BaseObserver) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        """Stop watching and wait for the background thread to finish."""
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=2)
        self._observer = None

    def is_relevant(self, path: Path) -> bool:
        raise NotImplementedError

    def mark_dirty(self) -> None:
        """Record that a change happened (called from the watchdog's observer thread)."""
        with self._lock:
            self._dirty = True
            self._last_event = time.monotonic()

    @property
    def pending(self) -> bool:
        """Whether there are changes that have not been consumed yet (regardless of the debounce period)."""
        with self._lock:
            return self._dirty

    def consume(self) -> bool:
        """Return `True` (once) if changes happened and have settled for at least `debounce` seconds.
        (called from the TUI main thread)."""
        with self._lock:
            if not self._dirty:
                return False
            if time.monotonic() - self._last_event < self.debounce:
                return False
            self._dirty = False
            return True


class ProjectWatcher(_DebouncedWatcher):
    """Watch a project directory recursively and report (debounced) changes."""

    def _schedule(self, observer: BaseObserver) -> None:
        observer.schedule(_ChangeEventHandler(self), str(self.path), recursive=True)

    def is_relevant(self, path: Path) -> bool:
        """Return `True` if a change to `path` may affect the project (i.e. it is not an ignored path)."""
        try:
            rel = path.relative_to(self.path)
        except ValueError:
            return False
        return not any(rel == ignored or rel.is_relative_to(ignored) for ignored in IGNORED_PATHS)


# Files (relative to a project root) defining the project's identity (ID, name) and whether it is a project at all.
PROJECT_IDENTITY_FILES: frozenset[str] = frozenset({"config.json", ".sereto"})


class ProjectsDirWatcher(_DebouncedWatcher):
    """Watch the projects directory and report (debounced) changes affecting the list of projects.

    Reported are project directories being added, removed or renamed, and changes to the identity files
    (`PROJECT_IDENTITY_FILES`) of any project, e.g. a project's ID or name being edited. Other changes inside the
    projects are not reported (those are handled by `ProjectWatcher` for the active project).

    To avoid watching the whole tree recursively, the projects directory and each of its subdirectories are watched
    non-recursively. Call `sync_project_dirs` after directories were added or removed to update the watched set.
    """

    def __init__(self, path: Path, debounce: float = 0.2) -> None:
        super().__init__(path, debounce)
        self._project_watches: dict[Path, ObservedWatch] = {}

    def _schedule(self, observer: BaseObserver) -> None:
        observer.schedule(_DirectoryChangeHandler(self), str(self.path), recursive=False)
        self._sync_project_dirs(observer)

    def stop(self) -> None:
        super().stop()
        self._project_watches.clear()

    def sync_project_dirs(self) -> None:
        """Watch the identity files of every directory currently in the projects directory (and stop watching removed
        directories)."""
        if self._observer is not None:
            self._sync_project_dirs(self._observer)

    def _sync_project_dirs(self, observer: BaseObserver) -> None:
        try:
            dirs = {d for d in self.path.iterdir() if d.is_dir()}
        except OSError:
            return
        for path in self._project_watches.keys() - dirs:
            watch = self._project_watches.pop(path)
            # The directory is gone, and possibly its watch as well
            with contextlib.suppress(KeyError, OSError):
                observer.unschedule(watch)
        for path in dirs - self._project_watches.keys():
            # E.g. no permission; such a directory cannot be a usable project anyway
            with contextlib.suppress(OSError):
                self._project_watches[path] = observer.schedule(_ChangeEventHandler(self), str(path), recursive=False)

    def is_relevant(self, path: Path) -> bool:
        """Return `True` for entries directly in the projects directory and for projects' identity files."""
        return path.parent == self.path or (path.parent.parent == self.path and path.name in PROJECT_IDENTITY_FILES)


class _DirectoryChangeHandler(_ChangeEventHandler):
    def on_any_event(self, event: FileSystemEvent) -> None:
        # Consider only directory events.
        # On Windows, every deletion (even of directories) is reported as a file deletion, so deletions are accepted
        # regardless of the type. Deleting a regular file only causes a needless (harmless) re-scan.
        if event.is_directory or event.event_type == EVENT_TYPE_DELETED:
            super().on_any_event(event)
