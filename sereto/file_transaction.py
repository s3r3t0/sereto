import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Self, TypedDict, cast

from sereto.exceptions import SeretoRuntimeError


def file_digest(path: Path) -> str | None:
    """Return a file's SHA-256 digest, or None when it doesn't exist."""
    if not path.exists():
        return None
    if not path.is_file():
        raise SeretoRuntimeError(f"transaction path is not a file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class PendingFileWrite:
    path: Path
    content: bytes
    expected_digest: str | None


class TransactionEntry(TypedDict):
    path: str
    staged: str
    backup: str
    had_original: bool
    original_digest: str | None
    replacement_digest: str


class ProjectFileLock:
    """Cross-platform advisory lock for Sereto project writes."""

    def __init__(self, path: Path, timeout: float = 10.0) -> None:
        self.path = path
        self.timeout = timeout
        self._file: BinaryIO | None = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_file = self.path.open("a+b")
        if os.name == "nt" and self.path.stat().st_size == 0:
            lock_file.write(b"\0")
            lock_file.flush()

        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._acquire(lock_file)
                self._file = lock_file
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    lock_file.close()
                    raise SeretoRuntimeError(f"timed out waiting for project lock: {self.path}") from None
                time.sleep(0.05)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._file is None:
            return
        try:
            self._release(self._file)
        finally:
            self._file.close()
            self._file = None

    @staticmethod
    def _acquire(lock_file: BinaryIO) -> None:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _release(lock_file: BinaryIO) -> None:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class AtomicFileTransaction:
    """Atomically replace a set of files beneath one project root."""

    def __init__(self, project_root: Path, writes: tuple[PendingFileWrite, ...] = ()) -> None:
        self.project_root = project_root.resolve()
        self.writes = writes
        self.state_dir = self.project_root / ".sereto"
        self.transactions_dir = self.state_dir / "transactions"
        self.lock_path = _project_lock_path(self.project_root)

    def commit(self, validator: Callable[[], None] | None = None) -> None:
        if not self.writes:
            return

        with self.locked():
            self._commit_locked(self.writes, validator)

    def commit_planned(
        self,
        planner: Callable[[], tuple[PendingFileWrite, ...]],
        validator: Callable[[], None] | None = None,
    ) -> None:
        """Build and commit a write set while holding the project lock."""
        with self.locked():
            writes = planner()
            if writes:
                self._commit_locked(writes, validator)

    def _commit_locked(
        self,
        writes: tuple[PendingFileWrite, ...],
        validator: Callable[[], None] | None,
    ) -> None:
        entries = self._validate_and_describe_writes(writes)
        transaction_dir = self.transactions_dir / uuid.uuid4().hex
        transaction_dir.mkdir(mode=0o700, parents=True)

        try:
            self._stage(transaction_dir, writes, entries)
            self._write_journal(transaction_dir, state="prepared", entries=entries)
            self._write_journal(transaction_dir, state="applying", entries=entries)

            for entry in entries:
                target = self.project_root / entry["path"]
                staged = transaction_dir / entry["staged"]
                os.replace(staged, target)
                _fsync_directory(target.parent)

            if validator is not None:
                validator()
            self._write_journal(transaction_dir, state="committed", entries=entries)
        except BaseException:
            self._recover_transaction(transaction_dir)
            self._cleanup_empty_state_dirs()
            raise
        else:
            shutil.rmtree(transaction_dir)
            _fsync_directory(self.transactions_dir)
            self._cleanup_empty_state_dirs()

    @classmethod
    def recover(cls, project_root: Path) -> None:
        transaction = cls(project_root=project_root)
        with transaction.locked():
            pass

    @contextmanager
    def locked(self) -> Generator[None]:
        """Recover pending state and hold the project transaction lock."""
        with ProjectFileLock(self.lock_path):
            self._recover_locked()
            yield

    def _validate_and_describe_writes(
        self,
        writes: tuple[PendingFileWrite, ...],
    ) -> list[TransactionEntry]:
        entries: list[TransactionEntry] = []
        seen: set[Path] = set()
        for index, write in enumerate(writes):
            target = write.path.resolve()
            try:
                relative = target.relative_to(self.project_root)
            except ValueError:
                raise SeretoRuntimeError(f"transaction path escapes project root: {write.path}") from None
            if target in seen:
                raise SeretoRuntimeError(f"transaction contains duplicate path: {write.path}")
            if not target.parent.is_dir():
                raise SeretoRuntimeError(f"transaction parent directory does not exist: {target.parent}")

            current_digest = file_digest(target)
            if current_digest != write.expected_digest:
                raise SeretoRuntimeError(f"file changed after validation: {target}")

            seen.add(target)
            entries.append(
                {
                    "path": relative.as_posix(),
                    "staged": f"staged/{index}",
                    "backup": f"backup/{index}",
                    "had_original": current_digest is not None,
                    "original_digest": current_digest,
                    "replacement_digest": hashlib.sha256(write.content).hexdigest(),
                }
            )
        return entries

    def _stage(
        self,
        transaction_dir: Path,
        writes: tuple[PendingFileWrite, ...],
        entries: list[TransactionEntry],
    ) -> None:
        (transaction_dir / "staged").mkdir()
        (transaction_dir / "backup").mkdir()

        for write, entry in zip(writes, entries, strict=True):
            staged = transaction_dir / str(entry["staged"])
            staged.write_bytes(write.content)
            _fsync_file(staged)

            if entry["had_original"]:
                target = self.project_root / str(entry["path"])
                backup = transaction_dir / str(entry["backup"])
                shutil.copyfile(target, backup)
                _fsync_file(backup)

        _fsync_directory(transaction_dir / "staged")
        _fsync_directory(transaction_dir / "backup")

    def _recover_locked(self) -> None:
        if not self.transactions_dir.exists():
            self._cleanup_empty_state_dirs()
            return
        for transaction_dir in sorted(self.transactions_dir.iterdir()):
            if transaction_dir.is_dir():
                self._recover_transaction(transaction_dir)
        self._cleanup_empty_state_dirs()

    def _recover_transaction(self, transaction_dir: Path) -> None:
        journal_path = transaction_dir / "journal.json"
        if not journal_path.exists():
            shutil.rmtree(transaction_dir)
            return

        try:
            raw_journal: object = json.loads(journal_path.read_text(encoding="utf-8"))
            if not isinstance(raw_journal, dict):
                raise TypeError
            journal = cast(dict[str, object], raw_journal)
            version = journal["version"]
            state = journal["state"]
            raw_entries_value = journal["entries"]
            if version != 1 or not isinstance(state, str) or not isinstance(raw_entries_value, list):
                raise TypeError
            raw_entries = cast(list[object], raw_entries_value)
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise SeretoRuntimeError(f"invalid transaction journal: {journal_path}") from error

        entries = [self._parse_entry(entry, transaction_dir) for entry in raw_entries]

        if state == "applying":
            for entry in entries:
                self._restore_entry(transaction_dir, entry)
        elif state not in {"prepared", "committed"}:
            raise SeretoRuntimeError(f"invalid transaction state {state!r}: {journal_path}")

        shutil.rmtree(transaction_dir)
        _fsync_directory(self.transactions_dir)

    def _cleanup_empty_state_dirs(self) -> None:
        for directory in (self.transactions_dir, self.state_dir):
            try:
                directory.rmdir()
            except FileNotFoundError:
                continue
            except OSError:
                break
        _fsync_directory(self.project_root)

    @staticmethod
    def _parse_entry(entry: object, transaction_dir: Path) -> TransactionEntry:
        if not isinstance(entry, dict):
            raise SeretoRuntimeError(f"invalid transaction entry in {transaction_dir}")
        entry_data = cast(dict[str, object], entry)
        try:
            path = entry_data["path"]
            staged = entry_data["staged"]
            backup = entry_data["backup"]
            had_original = entry_data["had_original"]
            original_digest = entry_data["original_digest"]
            replacement_digest = entry_data["replacement_digest"]
            if not (
                isinstance(path, str)
                and isinstance(staged, str)
                and isinstance(backup, str)
                and isinstance(had_original, bool)
                and (original_digest is None or isinstance(original_digest, str))
                and isinstance(replacement_digest, str)
            ):
                raise TypeError
            path_parts = Path(path)
            staged_parts = Path(staged).parts
            backup_parts = Path(backup).parts
            if (
                path_parts.is_absolute()
                or ".." in path_parts.parts
                or len(staged_parts) != 2
                or staged_parts[0] != "staged"
                or not staged_parts[1].isdecimal()
                or len(backup_parts) != 2
                or backup_parts[0] != "backup"
                or not backup_parts[1].isdecimal()
                or had_original != (original_digest is not None)
            ):
                raise TypeError
        except (KeyError, TypeError) as error:
            raise SeretoRuntimeError(f"invalid transaction entry in {transaction_dir}") from error

        return TransactionEntry(
            path=path,
            staged=staged,
            backup=backup,
            had_original=had_original,
            original_digest=original_digest,
            replacement_digest=replacement_digest,
        )

    def _restore_entry(self, transaction_dir: Path, entry: TransactionEntry) -> None:
        try:
            target = (self.project_root / entry["path"]).resolve()
            target.relative_to(self.project_root)
        except ValueError as error:
            raise SeretoRuntimeError(f"invalid transaction entry in {transaction_dir}") from error

        had_original = entry["had_original"]
        original_digest = entry["original_digest"]
        replacement_digest = entry["replacement_digest"]

        current_digest = file_digest(target)
        if current_digest == original_digest:
            return
        if current_digest != replacement_digest:
            raise SeretoRuntimeError(f"cannot recover externally modified file: {target}")

        if had_original:
            backup = transaction_dir / str(entry["backup"])
            if original_digest is None or file_digest(backup) != original_digest:
                raise SeretoRuntimeError(f"transaction backup does not match original file: {target}")
            restore = transaction_dir / f"restore-{uuid.uuid4().hex}"
            shutil.copyfile(backup, restore)
            _fsync_file(restore)
            os.replace(restore, target)
        else:
            target.unlink()
        _fsync_directory(target.parent)

    @staticmethod
    def _write_journal(
        transaction_dir: Path,
        state: str,
        entries: list[TransactionEntry],
    ) -> None:
        journal_path = transaction_dir / "journal.json"
        temporary_path = transaction_dir / "journal.tmp"
        temporary_path.write_text(
            json.dumps({"version": 1, "state": state, "entries": entries}, indent=2) + "\n",
            encoding="utf-8",
        )
        _fsync_file(temporary_path)
        os.replace(temporary_path, journal_path)
        _fsync_directory(transaction_dir)


def _fsync_file(path: Path) -> None:
    with path.open("rb") as file:
        os.fsync(file.fileno())


def _project_lock_path(project_root: Path) -> Path:
    user_id = str(os.getuid()) if hasattr(os, "getuid") else "user"
    lock_root = Path(tempfile.gettempdir()) / f"sereto-{user_id}"
    _ensure_private_directory(lock_root)
    lock_dir = lock_root / "project-locks"
    _ensure_private_directory(lock_dir)
    digest = hashlib.sha256(str(project_root).encode("utf-8")).hexdigest()
    return lock_dir / f"{digest}.lock"


def _ensure_private_directory(directory: Path) -> None:
    with suppress(FileExistsError):
        directory.mkdir(mode=0o700)

    metadata = directory.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise SeretoRuntimeError(f"lock path is not a directory: {directory}")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise SeretoRuntimeError(f"lock directory is not owned by the current user: {directory}")
    if os.name != "nt":
        directory.chmod(0o700)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
