from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, Literal, assert_never, cast

if TYPE_CHECKING:
    from sereto.tui.app import SeretoUnifiedApp

import click
import frontmatter
from rich.syntax import Syntax
from rich.text import Text
from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical, VerticalScroll
from textual.markup import escape
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from sereto.models.date import DateType
from sereto.models.version import SeretoVersion
from sereto.project_merge import (
    LOCAL_MARKER,
    UNPACKED_MARKER,
    DateKey,
    FileKey,
    FindingKey,
    GroupKey,
    MergeKey,
    MergeRecord,
    MergeSelection,
    MergeStatus,
    MergeValue,
    PersonKey,
    TargetKey,
    apply_entity_merge,
    discover_merge_dates,
    discover_merge_files,
    discover_merge_findings,
    discover_merge_groups,
    discover_merge_people,
    discover_merge_targets,
    has_conflict_markers,
    render_conflict_markers,
)
from sereto.source_archive import extract_source_archive_from_pdf


@dataclass(frozen=True)
class UnpackContext:
    pdf_path: Path | None = None


def get_unpack_context(app: SeretoUnifiedApp) -> UnpackContext:
    """Return ``app.plugin_context`` if it's a `UnpackContext`, otherwise defaults."""
    ctx = app.plugin_context
    return ctx if isinstance(ctx, UnpackContext) else UnpackContext()


def _project_versions_match(local_dir: Path, unpacked_dir: Path) -> bool:
    local_version = SeretoVersion.from_str(json.loads((local_dir / "config.json").read_text())["sereto_version"])
    unpacked_version = SeretoVersion.from_str(json.loads((unpacked_dir / "config.json").read_text())["sereto_version"])
    # Only compare the major and minor versions for compatibility
    return (local_version.root.major == unpacked_version.root.major) and (
        local_version.root.minor == unpacked_version.root.minor
    )


class ExistingProjectScreen(ModalScreen[bool]):
    """Ask whether to merge an unpacked project with an existing local project if possible (compatible versions)."""

    AUTO_FOCUS = "#existing-project-merge"
    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    def __init__(self, project_name: str, compatible: bool) -> None:
        super().__init__()
        self.project_name = project_name
        self.compatible = compatible

    def compose(self) -> ComposeResult:
        message = Text(f"A project with the same ID ('{self.project_name}') already exists locally.")
        if self.compatible:
            message.append("\n\nChoose Continue to compare the local and unpacked projects before applying changes.")
        else:
            message.append(
                "\n\nThe local and unpacked projects have different major/minor SeReTo versions "
                "and cannot be merged. Patch version differences are allowed.",
                style="italic red",
            )
        with Vertical(id="existing-project-dialog"):
            yield Static("Project already exists", id="existing-project-title")
            yield Static(message, id="existing-project-message")
            with Horizontal(id="existing-project-buttons"):
                yield Button("Cancel", id="existing-project-cancel")
                yield Button("Continue", id="existing-project-merge", variant="success", disabled=not self.compatible)

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#existing-project-cancel")
    def cancel(self) -> None:
        self.action_cancel()

    @on(Button.Pressed, "#existing-project-merge")
    def merge(self) -> None:
        if self.compatible:
            self.dismiss(True)


class UnpackProjectScreen(Screen[None]):
    """Screen for providing a PDF which to unpack."""

    AUTO_FOCUS = "#unpack-submit"
    SUB_TITLE = "Unpack project from PDF"
    BINDINGS = [Binding("escape", "close", "Back")]

    def __init__(self, projects_path: Path, pdf_path: Path | None = None) -> None:
        super().__init__()
        self.projects_path = projects_path
        self.pdf_path = pdf_path
        self._temporary_dir: TemporaryDirectory[str] | None = None
        self._merge_project_name: str | None = None

    @property
    def sereto_app(self) -> SeretoUnifiedApp:
        return cast("SeretoUnifiedApp", self.app)

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="unpack-layout"):
            yield Static("Unpack a SeReTo project", id="unpack-title")
            yield Static(
                "[italic]Choose a report PDF containing an embedded project source archive.[/italic]", id="unpack-help"
            )
            yield Input(
                value=str(self.pdf_path) if self.pdf_path is not None else "",
                placeholder="/path/to/report.pdf",
                id="unpack-pdf-path",
            )
            yield Static("", id="unpack-status")
            with Horizontal(id="unpack-buttons"):
                yield Button("Back", id="unpack-back")
                yield Button("Unpack project", id="unpack-submit", variant="success")
        yield Footer()

    def on_mount(self) -> None:
        if self.pdf_path is None:
            self.query_one("#unpack-pdf-path", Input).focus()
        else:
            # Trigger unpack action automatically if PDF path is already provided.
            self.action_unpack()

    def _set_busy(self, busy: bool) -> None:
        self.query_one("#unpack-pdf-path", Input).disabled = busy
        self.query_one("#unpack-submit", Button).disabled = busy
        if busy:
            self.query_one("#unpack-status", Static).update("Extracting project...")

    def _show_error(self, message: str) -> None:
        self._set_busy(False)
        self.query_one("#unpack-status", Static).update(Text(message, style="bold red"))

    def _show_success(self, project_name: str) -> None:
        self._set_busy(False)
        self.query_one("#unpack-status", Static).update(
            Text(f"Project '{project_name}' unpacked successfully.", style="bold green")
        )

    def _cleanup_temporary_dir(self) -> None:
        if self._temporary_dir is not None:
            self._temporary_dir.cleanup()
            self._temporary_dir = None

    def _open_merge(self, local_dir: Path, unpacked_dir: Path) -> None:
        try:
            screen = MergeUnpackedScreen(local_dir, unpacked_dir)
        except (OSError, ValueError) as exc:
            self._merge_project_name = None
            self._cleanup_temporary_dir()
            self._show_error(f"Could not compare projects: {exc}")
            return
        self._set_busy(False)
        self._merge_project_name = unpacked_dir.name
        self.sereto_app.push_screen(screen, self._merge_finished)

    def _confirm_merge(self, local_dir: Path, unpacked_dir: Path, compatible: bool) -> None:
        self.query_one("#unpack-status", Static).update("Project already exists locally.")

        def confirmed(merge: bool | None) -> None:
            if merge and compatible:
                self._open_merge(local_dir, unpacked_dir)
            else:
                self._cleanup_temporary_dir()
                self._set_busy(False)
                self.query_one("#unpack-status", Static).update("Unpack cancelled.")

        self.sereto_app.push_screen(ExistingProjectScreen(unpacked_dir.name, compatible), confirmed)

    def _merge_finished(self, applied: bool | None) -> None:
        project_name = self._merge_project_name
        self._merge_project_name = None
        self._cleanup_temporary_dir()
        if applied and project_name is not None:
            self._show_success(project_name)
        else:
            self.query_one("#unpack-status", Static).update("Merge cancelled.")

    @work(thread=True, exclusive=True)
    def _unpack(self, pdf_path: Path) -> None:
        self.sereto_app.call_from_thread(self._set_busy, True)
        temporary_dir = TemporaryDirectory(prefix="sereto-unpack-")
        try:
            unpacked_dir = extract_source_archive_from_pdf(pdf=pdf_path, output_dir=Path(temporary_dir.name))
            if unpacked_dir is None:
                temporary_dir.cleanup()
                self.sereto_app.call_from_thread(self._show_error, "The embedded source archive is empty.")
                return

            local_dir = self.projects_path / unpacked_dir.name
            if local_dir.exists():
                compatible = _project_versions_match(local_dir, unpacked_dir)
                self._temporary_dir = temporary_dir
                self.sereto_app.call_from_thread(self._confirm_merge, local_dir, unpacked_dir, compatible)
                return

            # Local project does not exist, unpack the new project with no further additional logic
            self.projects_path.mkdir(parents=True, exist_ok=True)
            shutil.move(unpacked_dir, local_dir)
            temporary_dir.cleanup()
            self.sereto_app.call_from_thread(self._show_success, local_dir.name)
        except Exception as exc:
            temporary_dir.cleanup()
            self.sereto_app.call_from_thread(self._show_error, str(exc))

    def action_unpack(self) -> None:
        raw_path = self.query_one("#unpack-pdf-path", Input).value.strip()
        if not raw_path:
            self._show_error("Choose a PDF file to unpack.")
            return
        pdf_path = Path(raw_path).expanduser().resolve()
        if not pdf_path.is_file():
            self._show_error(f"File not found: '{pdf_path}'")
            return
        if pdf_path.suffix.lower() != ".pdf":
            self._show_error("Choose a PDF file.")
            return
        self._unpack(pdf_path)

    def action_close(self) -> None:
        self._cleanup_temporary_dir()
        if isinstance(self.sereto_app.plugin_context, UnpackContext):
            self.sereto_app.plugin_context = None
        self.sereto_app.pop_screen()

    @on(Button.Pressed, "#unpack-submit")
    def unpack_project(self) -> None:
        self.action_unpack()

    @on(Button.Pressed, "#unpack-back")
    def close(self) -> None:
        self.action_close()


# Flag object used to indicate a missing (not null) value in the merge resolution logic
_MISSING = object()


@dataclass(frozen=True)
class _ResolutionField:
    """Represents a single field in the merge conflict resolution modal screen."""

    label: str
    path: tuple[str, ...] | None
    local: object
    unpacked: object
    local_present: bool
    unpacked_present: bool
    default_choice: str | None


def _resolution_fields(local: dict[str, Any], unpacked: dict[str, Any]) -> list[_ResolutionField]:
    fields: list[_ResolutionField] = []

    def visit(
        path: tuple[str, ...],
        local_value: object,
        local_present: bool,
        unpacked_value: object,
        unpacked_present: bool,
    ) -> None:
        if local_present and unpacked_present and isinstance(local_value, dict) and isinstance(unpacked_value, dict):
            keys = [*local_value, *(key for key in unpacked_value if key not in local_value)]
            if not keys:
                fields.append(_ResolutionField(".".join(path) or "Record", path, {}, {}, True, True, "local"))
            for key in keys:
                # Recursively visit nested dictionary fields to build resolution fields for each key
                visit(
                    (*path, key),
                    local_value.get(key, _MISSING),
                    key in local_value,
                    unpacked_value.get(key, _MISSING),
                    key in unpacked_value,
                )
            return

        if not local_present:
            default_choice = "unpacked"
        elif not unpacked_present or local_value == unpacked_value:
            default_choice = "local"
        else:
            default_choice = None
        fields.append(
            _ResolutionField(
                ".".join(path) or "Record",
                path,
                local_value,
                unpacked_value,
                local_present,
                unpacked_present,
                default_choice,
            )
        )

    visit((), local, True, unpacked, True)
    return fields


def _json_default(value: object) -> str:
    if isinstance(value, (date, time)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _display_value(value: object, present: bool) -> str:
    if not present:
        return "—"
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace") or "(empty)"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def _path_value(value: dict[str, object], path: tuple[str, ...]) -> tuple[object, bool]:
    """Retrieve the value at the specified path within a nested dictionary, returning a tuple of the value and
    a boolean indicating presence.
    """
    current: object = value
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return _MISSING, False
        current = current[part]
    return current, True


def _set_path_value(result: dict[str, object], path: tuple[str, ...], value: object) -> None:
    if not path:
        if isinstance(value, dict):
            result.update(copy.deepcopy(value))
        return
    current = result
    for part in path[:-1]:
        child = current.setdefault(part, {})
        if not isinstance(child, dict):
            raise TypeError(f"Cannot resolve nested field {'.'.join(path)!r}.")
        current = child
    current[path[-1]] = copy.deepcopy(value)


class ConflictResolutionScreen(ModalScreen[dict[str, Any] | None]):
    BINDINGS = [
        Binding("ctrl+s", "apply", "Apply selection"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self, title: str, local: dict[str, Any], unpacked: dict[str, Any], selected: dict[str, Any] | None
    ) -> None:
        super().__init__()
        self.title = title
        self.local = local
        self.unpacked = unpacked
        self.fields = _resolution_fields(local, unpacked)
        self.choices: dict[int, str] = {
            index: field.default_choice for index, field in enumerate(self.fields) if field.default_choice is not None
        }
        if selected is not None:
            self._restore_choices(selected)

    def _restore_choices(self, selected: dict[str, Any]) -> None:
        """Restore previously selected choices from the given dictionary."""
        for index, field in enumerate(self.fields):
            if field.path is None:
                selected_value: object = selected
                selected_present = True
            elif isinstance(selected, dict):
                selected_value, selected_present = _path_value(selected, field.path)
            else:
                continue
            if selected_present and field.local_present and selected_value == field.local:
                self.choices[index] = "local"
            elif selected_present and field.unpacked_present and selected_value == field.unpacked:
                self.choices[index] = "unpacked"
            elif not selected_present and not field.local_present:
                self.choices[index] = "local"
            elif not selected_present and not field.unpacked_present:
                self.choices[index] = "unpacked"

    def compose(self) -> ComposeResult:
        dialog = Vertical(id="conflict-dialog")
        dialog.border_title = escape(f"Resolve values for {self.title}")
        with dialog:
            yield Static(
                "[italic]Click a local or unpacked value in each row. "
                "Highlighted values form the merged record.[/italic]",
                id="conflict-hint",
            )
            with Horizontal(id="conflict-headings"):
                yield Static("Field", classes="conflict-field-name")
                yield Static("Local project", classes="conflict-value")
                yield Static("Unpacked project", classes="conflict-value")
                yield Static("Merged", classes="conflict-result")
            with ScrollableContainer(id="conflict-fields"):
                for index, field in enumerate(self.fields):
                    with Horizontal(classes="conflict-row"):
                        yield Static(Text(field.label), classes="conflict-field-name")
                        local_button = Button(
                            self._button_label(index, "local"),
                            id=f"conflict-choice-local-{index}",
                            classes="conflict-value",
                            compact=True,
                            variant="primary" if self.choices.get(index) == "local" else "default",
                        )
                        yield local_button
                        unpacked_button = Button(
                            self._button_label(index, "unpacked"),
                            id=f"conflict-choice-unpacked-{index}",
                            classes="conflict-value",
                            compact=True,
                            variant="primary" if self.choices.get(index) == "unpacked" else "default",
                        )
                        yield unpacked_button
                        yield Static(
                            self._selected_label(index), id=f"conflict-result-{index}", classes="conflict-result"
                        )
            yield Static(
                Text("All conflicts must be resolved first", style="dim italic red"),
                id="conflict-warning",
            ).set_class(self._all_fields_selected(), "hidden")
            with Horizontal(id="conflict-buttons"):
                yield Button("All local", id="conflict-all-local")
                yield Button("All unpacked", id="conflict-all-unpacked")
                yield Button("Cancel", id="conflict-cancel")
                yield Button(
                    "Apply",
                    id="conflict-apply",
                    variant="success",
                    disabled=not self._all_fields_selected(),
                    tooltip="Apply the selected choices",
                )

    def on_mount(self) -> None:
        if self.fields:
            index = next((index for index in range(len(self.fields)) if index not in self.choices), 0)
            self.query_one(f"#conflict-choice-local-{index}", Button).focus()

    def _button_label(self, index: int, source: str) -> Text:
        field = self.fields[index]
        value = field.local if source == "local" else field.unpacked
        present = field.local_present if source == "local" else field.unpacked_present
        display = _display_value(value, present)
        marker = "✓ " if self.choices.get(index) == source else ""
        return Text(marker + display, overflow="fold")

    def _selected_label(self, index: int) -> Text:
        choice = self.choices.get(index)
        if choice is None:
            return Text("Choose a value", style="bold yellow")
        field = self.fields[index]
        value = field.local if choice == "local" else field.unpacked
        present = field.local_present if choice == "local" else field.unpacked_present
        return Text(_display_value(value, present), overflow="fold")

    def _all_fields_selected(self) -> bool:
        return len(self.choices) == len(self.fields)

    def _build_result(self) -> dict[str, Any]:
        result: dict[str, object] = {}
        for index, field in enumerate(self.fields):
            if field.path is None:
                selected_value = self.local if self.choices[index] == "local" else self.unpacked
                if not isinstance(selected_value, dict):
                    raise TypeError("Record values must be dictionaries.")
                return copy.deepcopy(selected_value)
            if self.choices[index] == "local":
                value, present = field.local, field.local_present
            else:
                value, present = field.unpacked, field.unpacked_present
            if present:
                _set_path_value(result, field.path, value)
        return result

    def action_apply(self) -> None:
        if self._all_fields_selected():
            self.dismiss(self._build_result())
        else:
            self.notify("Choose a version for every conflicting field.", severity="warning")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _select_field(self, index: int, source: str) -> None:
        """Select a source for a given field index.

        Args:
            index: The index of the field to select.
            source: The source to select, either "local" or "unpacked".
        """
        self.choices[index] = source
        for choice in ("local", "unpacked"):
            button = self.query_one(f"#conflict-choice-{choice}-{index}", Button)
            button.label = self._button_label(index, choice)
            button.variant = "primary" if choice == source else "default"
        self.query_one(f"#conflict-result-{index}", Static).update(self._selected_label(index))
        self.query_one("#conflict-apply", Button).disabled = not self._all_fields_selected()
        self.query_one("#conflict-warning", Static).set_class(self._all_fields_selected(), "hidden")

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("conflict-choice-"):
            _, _, source, index_text = button_id.rsplit("-", 3)
            index = int(index_text)
            self._select_field(index, source)
        elif button_id in ("conflict-all-local", "conflict-all-unpacked"):
            source = button_id.rsplit("-", 1)[1]
            for index in range(len(self.fields)):
                self._select_field(index, source)
        elif button_id == "conflict-apply":
            self.action_apply()
        elif button_id == "conflict-cancel":
            self.action_cancel()


def _decode_strict(content: bytes) -> str | None:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _file_content(content: bytes) -> str:
    text = _decode_strict(content)
    if text is None or "\x00" in text:
        return f"Binary file: {len(content)} bytes\nSHA-256: {hashlib.sha256(content).hexdigest()}"
    return text or "(empty)"


class FileConflictScreen(ModalScreen[bytes | None]):
    """Resolve differing file content: take either whole version or edit a file with git-style conflict markers."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        title: str,
        local: bytes,
        unpacked: bytes,
        selected: bytes | None,
        file_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.title = title
        self.local = local
        self.unpacked = unpacked
        self.selected = selected
        self.file_path = file_path
        self._local_text = _decode_strict(local)
        self._unpacked_text = _decode_strict(unpacked)
        self._temporary_dir: TemporaryDirectory[str] | None = None
        self.edit_path: Path | None = None
        self.mode: Literal["pick", "manual"] | None = None

    @property
    def editable(self) -> bool:
        return (
            self._local_text is not None
            and self._unpacked_text is not None
            and "\x00" not in self._local_text
            and "\x00" not in self._unpacked_text
        )

    def compose(self) -> ComposeResult:
        dialog = Vertical(id="finding-dialog")
        dialog.border_title = escape(f"Resolve content of {self.title}")
        with dialog:
            with VerticalScroll(id="finding-body"):
                yield Static(
                    "[italic]The content differs between the local and the unpacked project. "
                    "Either keep one of the versions as a whole, or resolve the differences manually.[/italic]",
                    classes="finding-help",
                )
                with Horizontal(id="finding-modes"):
                    yield Button("Use local/unpacked", id="finding-mode-pick", variant="warning")
                    yield Button(
                        "Resolve manually",
                        id="finding-mode-manual",
                        disabled=not self.editable,
                        tooltip=None if self.editable else "The content is not valid UTF-8 text",
                        variant="warning",
                    )
                with Vertical(id="finding-pick", classes="hidden"):
                    yield Static(
                        "[italic]Click the version you want to use. Its whole content will be taken as the "
                        "resolution.[/italic]",
                        classes="finding-help",
                    )
                    with Horizontal(id="finding-columns"):
                        for source, title, content in (
                            ("local", "Local project", self.local),
                            ("unpacked", "Unpacked project", self.unpacked),
                        ):
                            with Vertical(classes="finding-column"):
                                yield Static(title, classes="finding-column-title")
                                with ScrollableContainer(classes="finding-version"):
                                    yield Button(
                                        Text(_file_content(content), overflow="fold"),
                                        id=f"finding-choice-{source}",
                                        classes="finding-choice",
                                        variant="primary" if self.selected == content else "default",
                                    )
                with Vertical(id="finding-manual", classes="hidden"):
                    yield Static(
                        "[italic]Choose the editor in which you want to resolve the differences. "
                        "The content of both versions is saved in a single file, where every differing section "
                        f"is marked like in git:[/italic]\n\n{LOCAL_MARKER}\n(content of the local project)\n"
                        f"=======\n(content of the unpacked project)\n{UNPACKED_MARKER}\n\n"
                        "[italic]Edit the file as you wish and remove the markers. Then save it and confirm "
                        "with 'Use edited content'.[/italic]",
                        classes="finding-help",
                    )
                    with Horizontal(id="finding-edit"):
                        yield Button("Edit in default editor", id="finding-edit-default", variant="primary")
                        yield Button(
                            "Edit in VS Code",
                            id="finding-edit-code",
                            disabled=shutil.which("code") is None,
                            tooltip=None if shutil.which("code") else "The 'code' command was not found in PATH",
                            variant="primary",
                        )
                        yield Button(
                            "Use edited content", id="finding-use-edited", variant="success", classes="hidden"
                        )
                yield Static("", id="finding-status")
            with Horizontal(id="finding-buttons"):
                yield Button("Cancel", id="finding-cancel")

    def on_mount(self) -> None:
        if self.selected is not None:
            # Continue with the kind of resolution that was chosen previously
            self._set_mode("pick" if self.selected in (self.local, self.unpacked) else "manual")

    def on_unmount(self) -> None:
        if self._temporary_dir is not None:
            self._temporary_dir.cleanup()
            self._temporary_dir = None

    def _set_mode(self, mode: Literal["pick", "manual"]) -> None:
        self.mode = mode
        self.query_one("#finding-pick").set_class(mode != "pick", "hidden")
        self.query_one("#finding-manual").set_class(mode != "manual", "hidden")
        self.query_one("#finding-mode-pick", Button).variant = "warning" if mode == "pick" else "default"
        self.query_one("#finding-mode-manual", Button).variant = "warning" if mode == "manual" else "default"

    def _edit_file(self) -> Path:
        """Return the file for editing, creating it with the conflict markers on first use."""
        if self.edit_path is None:
            if self._local_text is None or self._unpacked_text is None:
                raise ValueError("Finding content is not valid UTF-8 text.")
            self._temporary_dir = TemporaryDirectory(prefix="sereto-finding-")
            self.edit_path = Path(self._temporary_dir.name) / (
                self.file_path.name if self.file_path is not None else "finding.md"
            )
            if self.selected is not None and self.selected not in (self.local, self.unpacked):
                # Continue with the previously resolved content
                self.edit_path.write_bytes(self.selected)
            else:
                self.edit_path.write_text(render_conflict_markers(self._local_text, self._unpacked_text), "utf-8")
        return self.edit_path

    def _set_status(self, message: str, style: str = "") -> None:
        self.query_one("#finding-status", Static).update(Text(message, style=style))

    def _launch(self, use_vscode: bool) -> None:
        try:
            path = self._edit_file()
        except (OSError, ValueError) as exc:
            self._set_status(f"Could not prepare the file: {exc}", "bold red")
            return
        self.query_one("#finding-use-edited", Button).remove_class("hidden")
        self._set_status(f"Editing {path}. Save the file, then choose 'Use edited content'.", "italic")
        self._open_editor(path, use_vscode)

    @work(thread=True, exclusive=True, group="finding-editor")
    def _open_editor(self, path: Path, use_vscode: bool) -> None:
        try:
            if use_vscode:
                # Assume the 'code' command is available in PATH
                code = shutil.which("code")
                if code is None:
                    raise FileNotFoundError("The 'code' command was not found in PATH")
                subprocess.run(
                    [code, str(path)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
            elif click.launch(str(path)) != 0:  # Check return code
                raise RuntimeError("No application could open the file")
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            self.app.call_from_thread(self._set_status, f"Could not open the editor: {exc}", "bold red")

    def _use_edited(self) -> None:
        if self.edit_path is None:
            return
        try:
            content = self.edit_path.read_bytes()
        except OSError as exc:
            self._set_status(f"Could not read the edited file: {exc}", "bold red")
            return
        text = _decode_strict(content)
        if text is None:
            self._set_status("The edited file is not valid UTF-8 text.", "bold red")
        elif has_conflict_markers(text):
            self._set_status(
                f"The file still contains conflict markers ({LOCAL_MARKER} / {UNPACKED_MARKER}). "
                "Resolve them and save the file.",
                "italic bold red",
            )
        else:
            self.dismiss(content)

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "finding-mode-pick":
                self._set_mode("pick")
            case "finding-mode-manual":
                self._set_mode("manual")
            case "finding-choice-local":
                self.dismiss(self.local)
            case "finding-choice-unpacked":
                self.dismiss(self.unpacked)
            case "finding-edit-default":
                self._launch(use_vscode=False)
            case "finding-edit-code":
                self._launch(use_vscode=True)
            case "finding-use-edited":
                self._use_edited()
            case "finding-cancel":
                self.action_cancel()


def _record_content(value: MergeValue | None) -> Text | Syntax:
    """Render the whole record: indented JSON for structured records, decoded plain text for findings."""
    if value is None:
        return Text("(not present)")
    if isinstance(value, bytes):
        return Text(_file_content(value))
    return Syntax(
        json.dumps(value, ensure_ascii=False, indent=2, default=_json_default),
        "json",
        line_numbers=False,
        word_wrap=True,
    )


class RecordDetailScreen(ModalScreen[None]):
    """Read-only side-by-side view of a whole record from the local and the unpacked project."""

    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(
        self,
        title: str,
        local: MergeValue | None,
        unpacked: MergeValue | None,
        *,
        local_group: str | None = None,
        unpacked_group: str | None = None,
    ) -> None:
        super().__init__()
        self.record_title = title
        self.local = local
        self.unpacked = unpacked
        self.local_group = local_group
        self.unpacked_group = unpacked_group

    def compose(self) -> ComposeResult:
        dialog = Vertical(id="detail-dialog")
        dialog.border_title = escape(self.record_title)
        with dialog:
            with Horizontal(id="detail-panes"):
                for source, heading, value, group in (
                    ("local", "Local project", self.local, self.local_group),
                    ("unpacked", "Unpacked project", self.unpacked, self.unpacked_group),
                ):
                    with Vertical(classes="detail-pane"):
                        yield Static(heading, classes="detail-heading")
                        if group is not None:
                            yield Static(Text(f"Group: {group}"), classes="detail-heading")
                        with ScrollableContainer(id=f"detail-{source}-scroll", classes="detail-body"):
                            yield Static(_record_content(value), id=f"detail-{source}")
            with Horizontal(id="detail-buttons"):
                yield Button("Close", id="detail-close")

    def on_mount(self) -> None:
        self.query_one("#detail-local-scroll", ScrollableContainer).focus()

    def action_close(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#detail-close")
    def close(self) -> None:
        self.action_close()


ACTION_COLUMN_WIDTH = 20
ACTION_BUTTON_WIDTH = 11
CELL_PADDING = 1


def _padded(text: Text) -> Text:
    """Pad a cell manually, since the table has no padding so that the action column reaches its right edge."""
    return Text.assemble(" " * CELL_PADDING, text, " " * CELL_PADDING)


class MergeComparisonTable(DataTable[str | Text]):
    BINDINGS = [
        Binding("enter", "select_cursor", "Record detail"),
    ]

    class ActionClicked(Message):
        """The Action cell of a row was clicked."""

    def on_click(self, event: events.Click) -> None:
        row = event.style.meta.get("row")
        column = event.style.meta.get("column")
        if not isinstance(row, int) or not 0 <= row < self.row_count or event.style.meta.get("out_of_bounds", False):
            return
        event.prevent_default()
        event.stop()
        self.move_cursor(row=row)
        if column == len(self.ordered_columns) - 1:
            # Last column (Action) is clicked
            if event.chain == 1:
                # Trigger resolution for the action cell
                self.post_message(self.ActionClicked())
        elif event.chain == 2:
            # Same as pressing Enter on the row
            self.action_select_cursor()


class MergeUnpackedScreen(Screen[bool]):
    SUB_TITLE = "Merge unpacked project"
    BINDINGS = [
        Binding("space", "resolve", "Record action"),
        Binding("ctrl+s", "submit", "Apply"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, local_dir: Path, unpacked_dir: Path) -> None:
        super().__init__()
        self.local_dir = local_dir
        self.unpacked_dir = unpacked_dir
        self.dates = discover_merge_dates(local_dir, unpacked_dir)
        self.people = discover_merge_people(local_dir, unpacked_dir)
        self.targets = discover_merge_targets(local_dir, unpacked_dir)
        self.groups = discover_merge_groups(local_dir, unpacked_dir, self.targets)
        self.findings = discover_merge_findings(
            local_dir,
            unpacked_dir,
            self.targets,
            {target.key for target in self.targets},
        )
        self.files = discover_merge_files(local_dir, unpacked_dir, self.targets, self.findings)
        self.records: list[MergeRecord[MergeValue]] = [
            *self.dates,
            *self.people,
            *self.targets,
            *self.groups,
            *self.findings,
            *self.files,
        ]
        self.rows: list[MergeRecord[MergeValue]] = [*self.dates, *self.people]
        self._row_groups: dict[int, GroupKey] = {}
        for target in self.targets:
            self.rows.append(target)
            for group in self.groups:
                if group.parent_key != target.key:
                    continue
                self.rows.append(group)
                for finding in self.findings:
                    if group.key in (finding.local_group, finding.unpacked_group):
                        if not isinstance(group.key, GroupKey):
                            raise TypeError(f"Expected group key, got {group.key!r}")
                        self._row_groups[len(self.rows)] = group.key
                        self.rows.append(finding)
            self.rows.extend(file for file in self.files if file.parent_key == target.key)
        self.rows.extend(file for file in self.files if file.parent_key is None)
        self._tree_prefixes = self._build_tree_prefixes()
        self.selection = MergeSelection()
        self._highlighted_row = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="merge-layout"):
            yield Static(
                "[italic]Compare local and unpacked records. Press Enter or double-click a row to view "
                "the whole record side by side. Click Action (or press Space) to change a selection "
                "or resolve a conflict. "
                "Swap src switches one-sided records between Local and Unpacked; omitted rows are dimmed. "
                "Omitting a target also omits its groups, findings and target files; "
                "omitting a group omits findings assigned to it.",
                id="merge-help",
            )
            yield MergeComparisonTable(
                id="merge-table",
                cursor_type="row",
                zebra_stripes=False,
                cell_padding=0,
                cursor_foreground_priority="renderable",
            )
            yield Static("", id="merge-status")
            with Horizontal(id="merge-buttons"):
                yield Button("All local", id="merge-all-local")
                yield Button("All unpacked", id="merge-all-unpacked")
                yield Button("Cancel", id="merge-cancel")
                yield Button("Apply merge", id="merge-apply", variant="success")
        yield Footer()

    def on_mount(self) -> None:
        self.call_after_refresh(self._populate_table)
        self.query_one("#merge-table", DataTable).focus()
        self._update_apply_button()

    def on_resize(self, event: events.Resize) -> None:
        # Handle terminal resize events to adjust table layout accordingly
        if self.is_mounted and self.query_one("#merge-table", DataTable).columns:
            self.call_after_refresh(self._populate_table)

    def _populate_table(self) -> None:
        table = cast(DataTable[str | Text], self.query_one("#merge-table", DataTable))
        cursor = table.cursor_coordinate
        self._highlighted_row = cursor.row
        table.clear(columns=True)
        status_width = 10
        # Reserve the vertical scrollbar gutter before distributing the record columns.
        table_width = table.scrollable_content_region.width
        available = table_width - ACTION_COLUMN_WIDTH - status_width - 10 * CELL_PADDING
        # Version and type columns shrink (and wrap) on narrow terminals to leave room for the records.
        meta_width = min(8, max(3, (available - 24) // 2))
        version_width = type_width = meta_width
        record_total = max(2, available - version_width - type_width)
        record_width = record_total // 2
        table.header_height = 2 if record_width < len("Unpacked Project") else 1
        for label, key, width in (
            ("Version", "version", version_width),
            ("Type", "type", type_width),
            ("Local Project", "local", record_width),
            ("Unpacked Project", "unpacked", record_total - record_width),
            ("Status", "status", status_width),
            ("", "action", ACTION_COLUMN_WIDTH),
        ):
            if key == "action":
                table.add_column(label, key=key, width=width)
            else:
                table.add_column(_padded(Text(label)), key=key, width=width + 2 * CELL_PADDING)
        for index, record in enumerate(self.rows):
            table.add_row(
                self._version_cell(record),
                self._type_cell(record),
                self._record_cell(record, "local", self._row_groups.get(index)),
                self._record_cell(record, "unpacked", self._row_groups.get(index)),
                self._status_cell(record),
                self._action_cell(record, index == cursor.row),
                key=str(index),
                height=None,
            )
        table.move_cursor(row=cursor.row, column=cursor.column, animate=False)

    @staticmethod
    def _record_type_version(record: MergeRecord[MergeValue]) -> tuple[str, str]:
        match record.key:
            case DateKey():
                return "Date", record.key.version
            case PersonKey():
                return "Person", record.key.version
            case TargetKey():
                return "Target", record.key.version
            case GroupKey():
                return "Group", record.key.target.version
            case FindingKey():
                return "Finding", record.key.target.version
            case FileKey():
                return "File", record.key.target.version if record.key.target is not None else ""
            case _:
                assert_never(record.key)

    @staticmethod
    def _record_summary(record: MergeRecord[MergeValue], value: MergeValue | None = None) -> str:
        match record.key:
            case DateKey():
                date_type = DateType(record.key.type).value.replace("_", " ").title()
                return f"{date_type}"
            case PersonKey():
                value = value if isinstance(value, dict) else record.local or record.unpacked or {}
                if not isinstance(value, dict):
                    raise TypeError(f"Invalid person value for {record.key!r}")
                identity = value.get("email") or value.get("name") or record.key.email
                person_type = record.key.type.replace("_", " ").title()
                return f"{person_type}: {identity}"
            case TargetKey():
                return f"{record.key.category.upper()} {record.key.name}"
            case GroupKey():
                return record.key.name
            case FindingKey():
                if value is None:
                    value = record.local if record.local is not None else record.unpacked
                if not isinstance(value, bytes):
                    raise TypeError(f"Invalid finding value for {record.key!r}")
                metadata, _ = frontmatter.parse(value.decode("utf-8"))
                name = metadata.get("name") or record.key.name
                return str(name)
            case FileKey():
                return record.key.path.as_posix()
            case _:
                assert_never(record.key)

    @classmethod
    def _record_label(cls, record: MergeRecord[MergeValue], value: MergeValue | None = None) -> str:
        kind, version = cls._record_type_version(record)
        summary = cls._record_summary(record, value)
        if isinstance(record.key, (GroupKey, FindingKey)):
            summary = f"{record.key.target.name} / {summary}"
        return f"{kind}: {version} / {summary}"

    def _status(self, record: MergeRecord[MergeValue]) -> MergeStatus:
        """Effective status, including target and selected group exclusions."""
        return self.selection.effective_status(record)

    def _target_excluded(self, record: MergeRecord[MergeValue]) -> bool:
        """Whether the record is omitted by its target or selected group."""
        return self.selection.parent_excluded(record)

    def _status_label(self, record: MergeRecord[MergeValue]) -> str:
        """Show the selected project source or merge progress."""
        match self._status(record):
            case MergeStatus.INCLUDED:
                return "Local" if record.in_local else "Unpacked"
            case MergeStatus.EXCLUDED:
                return "Unpacked" if record.in_local else "Local"
            case MergeStatus.RESOLVED:
                return "Merged"
            case MergeStatus.IDENTICAL:
                return "Identical"
            case MergeStatus.CONFLICT:
                return "Conflict"

    def _row_style(self, record: MergeRecord[MergeValue]) -> str:
        """Text style of a row, reflecting its effective status."""
        match self._status(record):
            case MergeStatus.CONFLICT:
                return "bold #ff0000"
            case MergeStatus.EXCLUDED:
                return "dim"
            case _:
                return ""

    def _build_tree_prefixes(self) -> dict[tuple[str, MergeKey], str]:
        """Tree branches for each source's actual group membership."""
        prefixes: dict[tuple[str, MergeKey], str] = {}
        for source in ("local", "unpacked"):
            for target in self.targets:
                groups = [
                    group
                    for group in self.groups
                    if group.parent_key == target.key
                    and (group.local if source == "local" else group.unpacked) is not None
                ]
                for group_index, group in enumerate(groups):
                    last_group = group_index == len(groups) - 1
                    prefixes[source, group.key] = "└─ " if last_group else "├─ "
                    findings = [
                        finding
                        for finding in self.findings
                        if (finding.local_group if source == "local" else finding.unpacked_group) == group.key
                    ]
                    for index, finding in enumerate(findings):
                        prefixes[source, finding.key] = ("   " if last_group else "│  ") + (
                            "└─ " if index == len(findings) - 1 else "├─ "
                        )
        return prefixes

    def _record_cell(
        self, record: MergeRecord[MergeValue], source: Literal["local", "unpacked"], group: GroupKey | None = None
    ) -> Text:
        value = record.local if source == "local" else record.unpacked
        source_group = record.local_group if source == "local" else record.unpacked_group
        if value is None or (isinstance(record.key, FindingKey) and source_group != group):
            return _padded(Text("—", style="dim"))
        summary = self._record_summary(record, value)
        if isinstance(record.key, (GroupKey, FindingKey)):
            return _padded(
                Text.assemble(
                    Text(self._tree_prefixes[source, record.key], style="dim"),
                    Text(summary, style=self._row_style(record)),
                )
            )
        return _padded(Text(summary, style=self._row_style(record)))

    def _version_cell(self, record: MergeRecord[MergeValue]) -> Text:
        _, version = self._record_type_version(record)
        return _padded(Text(version, style=self._row_style(record)))

    def _type_cell(self, record: MergeRecord[MergeValue]) -> Text:
        kind, _ = self._record_type_version(record)
        return _padded(Text(kind, style=self._row_style(record)))

    def _status_cell(self, record: MergeRecord[MergeValue]) -> Text:
        return _padded(Text(self._status_label(record), style=self._row_style(record)))

    def _action_label(self, record: MergeRecord[MergeValue]) -> str:
        if self._target_excluded(record):
            return "Parent omitted"
        match self.selection.status(record):
            case MergeStatus.INCLUDED | MergeStatus.EXCLUDED:
                return "Swap src"
            case MergeStatus.CONFLICT:
                return "Resolve"
            case MergeStatus.RESOLVED:
                return "Edit"
            case MergeStatus.IDENTICAL:
                return ""

    def _action_cell(self, record: MergeRecord[MergeValue], highlighted: bool = False) -> Text:
        """Render the action as a centered label with a filled background, resembling a button.

        The background is darkened when the row is highlighted.
        """
        label = self._action_label(record)
        if label in ("", "Parent omitted"):
            return Text(label.rjust(ACTION_COLUMN_WIDTH), style="dim italic")
        if label == "Resolve":
            style = f"bold white on {'#420000' if highlighted else 'dark_red'}"
        else:
            style = f"bold white on {'#1d4766' if highlighted else '#1c74b2'}"
        return Text.assemble(
            " " * (ACTION_COLUMN_WIDTH - ACTION_BUTTON_WIDTH),
            (label.center(ACTION_BUTTON_WIDTH), style),
        )

    def _has_unresolved_conflicts(self) -> bool:
        return self.selection.has_conflicts(self.records)

    def _current_record(self) -> MergeRecord[MergeValue] | None:
        table = cast(DataTable[str | Text], self.query_one("#merge-table", DataTable))
        if not self.rows or table.cursor_row >= len(self.rows):
            return None
        return self.rows[table.cursor_row]

    def _refresh_row(self, table: DataTable[str | Text], row_key: str, record: MergeRecord[MergeValue]) -> None:
        table.update_cell(row_key, "version", self._version_cell(record))
        table.update_cell(row_key, "type", self._type_cell(record))
        group = self._row_groups.get(int(row_key))
        table.update_cell(row_key, "local", self._record_cell(record, "local", group))
        table.update_cell(row_key, "unpacked", self._record_cell(record, "unpacked", group))
        table.update_cell(row_key, "status", self._status_cell(record))
        table.update_cell(row_key, "action", self._action_cell(record, int(row_key) == table.cursor_row))

    def _update_rows(self) -> None:
        table = cast(DataTable[str | Text], self.query_one("#merge-table", DataTable))
        for index, record in enumerate(self.rows):
            self._refresh_row(table, str(index), record)
        self._update_apply_button()

    def _update_apply_button(self) -> None:
        self.query_one("#merge-apply", Button).disabled = self._has_unresolved_conflicts()

    def action_resolve(self) -> None:
        if not self.query_one("#merge-table", DataTable).has_focus:
            return
        record = self._current_record()
        if record is None:
            return
        status = self.selection.status(record)
        if status is MergeStatus.IDENTICAL:
            return
        if self._target_excluded(record):
            self.notify("Include the target or assigned group before changing this record.", severity="warning")
            return
        if status in (MergeStatus.INCLUDED, MergeStatus.EXCLUDED):
            # Toggle the status between INCLUDED and EXCLUDED
            self.selection.set_status(
                record, MergeStatus.EXCLUDED if status is MergeStatus.INCLUDED else MergeStatus.INCLUDED
            )
            self._update_rows()
            return
        if record.local is None or record.unpacked is None:
            return
        selected = self.selection.resolved_values.get(record.key)
        screen: ModalScreen[Any]
        if isinstance(record.key, FindingKey) and record.local_group != record.unpacked_group:
            chosen_group = self.selection.finding_group(record)
            screen = ConflictResolutionScreen(
                f"{self._record_label(record)} / Group Membership",
                {"group": record.local_group.name} if record.local_group is not None else {},
                {"group": record.unpacked_group.name} if record.unpacked_group is not None else {},
                {"group": chosen_group.name} if chosen_group is not None else None,
            )
            self.app.push_screen(screen, lambda result: self._membership_finished(record, result))
            return
        if isinstance(record.local, bytes) and isinstance(record.unpacked, bytes):
            screen = FileConflictScreen(
                self._record_label(record),
                record.local,
                record.unpacked,
                selected if isinstance(selected, bytes) else None,
                file_path=record.key.path if isinstance(record.key, FileKey) else None,
            )
        elif isinstance(record.local, dict) and isinstance(record.unpacked, dict):
            screen = ConflictResolutionScreen(
                self._record_label(record),
                record.local,
                record.unpacked,
                selected if isinstance(selected, dict) else None,
            )
        else:
            return
        self.app.push_screen(screen, lambda result: self._resolution_finished(record, result))

    def _membership_finished(self, record: MergeRecord[MergeValue], selected: dict[str, Any] | None) -> None:
        if selected is None:
            return
        group = next(
            (
                group
                for group in (record.local_group, record.unpacked_group)
                if group is not None and group.name == selected.get("group")
            ),
            None,
        )
        if group is None:
            self.notify("Choose a local or unpacked group for the finding.", severity="error")
            return
        if not isinstance(record.local, bytes) or not isinstance(record.unpacked, bytes):
            raise TypeError(f"Expected finding content for {record.key!r}")
        if record.local == record.unpacked:
            self._resolution_finished(record, record.local, group=group)
            return
        value = self.selection.resolved_values.get(record.key)
        self.app.push_screen(
            FileConflictScreen(
                self._record_label(record),
                record.local,
                record.unpacked,
                value if isinstance(value, bytes) else None,
            ),
            lambda result: self._resolution_finished(record, result, group=group),
        )

    def _resolution_finished(
        self,
        record: MergeRecord[MergeValue],
        selected: MergeValue | None,
        *,
        group: GroupKey | None = None,
    ) -> None:
        if selected is not None:
            try:
                self.selection.resolve(record, selected, group=group)
            except (ValueError, TypeError) as exc:
                self.notify(f"Could not resolve record: {exc}", severity="error", timeout=10, markup=False)
                return
            self._update_rows()

    @on(MergeComparisonTable.ActionClicked)
    def action_clicked(self) -> None:
        self.action_resolve()

    @on(DataTable.RowHighlighted, "#merge-table")
    def action_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        table = cast(DataTable[str | Text], self.query_one("#merge-table", DataTable))
        for index in {self._highlighted_row, event.cursor_row}:
            if 0 <= index < len(self.rows):
                table.update_cell(str(index), "action", self._action_cell(self.rows[index], index == event.cursor_row))
        self._highlighted_row = event.cursor_row

    @on(DataTable.RowSelected, "#merge-table")
    def action_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_show_detail()

    def action_show_detail(self) -> None:
        record = self._current_record()
        if record is None:
            return
        self.app.push_screen(
            RecordDetailScreen(
                self._record_label(record),
                record.local,
                record.unpacked,
                local_group=record.local_group.name if record.local_group is not None else None,
                unpacked_group=record.unpacked_group.name if record.unpacked_group is not None else None,
            )
        )

    def action_submit(self) -> None:
        if self._has_unresolved_conflicts():
            self.notify("Resolve each conflicting record before applying.", severity="warning")
            return
        try:
            apply_entity_merge(
                self.local_dir,
                self.unpacked_dir,
                self.records,
                self.selection,
            )
        except (OSError, ValueError, TypeError) as exc:
            message = f"Could not apply merge: {exc}"
            self.query_one("#merge-status", Static).update(Text(message, style="bold red"))
            self.notify(message, severity="error", timeout=10, markup=False)
            return
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_all(self, source: Literal["local", "unpacked"]) -> None:
        self.selection.resolve_all_as(self.records, source)
        self._populate_table()
        self._update_apply_button()

    @on(Button.Pressed, "#merge-all-local")
    def all_local(self) -> None:
        self.action_all("local")

    @on(Button.Pressed, "#merge-all-unpacked")
    def all_unpacked(self) -> None:
        self.action_all("unpacked")

    @on(Button.Pressed, "#merge-cancel")
    def cancel(self) -> None:
        self.action_cancel()

    @on(Button.Pressed, "#merge-apply")
    def apply(self) -> None:
        self.action_submit()
