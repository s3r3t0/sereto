from __future__ import annotations

import copy
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sereto.tui.app import SeretoUnifiedApp

from rich.text import Text
from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from sereto.models.version import SeretoVersion
from sereto.project_merge import (
    DateKey,
    FindingKey,
    MergeDate,
    MergeFinding,
    MergePerson,
    MergeStatus,
    MergeTarget,
    PersonKey,
    ResolvedMergeValues,
    TargetKey,
    apply_entity_merge,
    discover_merge_dates,
    discover_merge_findings,
    discover_merge_people,
    discover_merge_targets,
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


class UnpackProjectScreen(Screen[None]):
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
            yield Static("Choose a report PDF containing an embedded project source archive.", id="unpack-help")
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
        self.query_one("#unpack-pdf-path", Input).focus()

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
        self._set_busy(False)
        self._merge_project_name = unpacked_dir.name
        self.sereto_app.push_screen(MergeUnpackedScreen(local_dir, unpacked_dir), self._merge_finished)

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
                # Local project already exists - check if the versions match before attempting to merge
                if not _project_versions_match(local_dir, unpacked_dir):
                    temporary_dir.cleanup()
                    self.sereto_app.call_from_thread(
                        self._show_error,
                        "Project with same ID already exists and the local and unpacked project versions"
                        + " are incompatible and therefore cannot be merged.",
                    )
                    return
                # Only projects with matching sereto versions can be merged
                self._temporary_dir = temporary_dir
                self.sereto_app.call_from_thread(self._open_merge, local_dir, unpacked_dir)
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
        self.sereto_app.pop_screen()

    @on(Button.Pressed, "#unpack-submit")
    def unpack_project(self) -> None:
        self.action_unpack()

    @on(Button.Pressed, "#unpack-back")
    def close(self) -> None:
        self.action_close()


_MISSING = object()
MergeRow = MergeDate | MergePerson | MergeTarget | MergeFinding
MergeKey = DateKey | PersonKey | TargetKey | FindingKey
MergeValue = dict[str, object] | bytes


@dataclass(frozen=True)
class _ResolutionField:
    label: str
    path: tuple[str, ...] | None
    local: object
    unpacked: object
    local_present: bool
    unpacked_present: bool
    default_choice: str | None


def _resolution_fields(
    local: dict[str, object] | bytes, unpacked: dict[str, object] | bytes
) -> list[_ResolutionField]:
    if isinstance(local, bytes) and isinstance(unpacked, bytes):
        return [
            _ResolutionField(
                "Content",
                None,
                local,
                unpacked,
                True,
                True,
                "local" if local == unpacked else None,
            )
        ]
    if not isinstance(local, dict) or not isinstance(unpacked, dict):
        raise TypeError("Local and unpacked record values must have matching types.")

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


def _display_value(value: object, present: bool) -> str:
    if not present:
        return "—"
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace") or "(empty)"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _path_value(value: dict[str, object], path: tuple[str, ...]) -> tuple[object, bool]:
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


class ConflictResolutionScreen(ModalScreen[MergeValue | None]):
    BINDINGS = [
        Binding("ctrl+s", "apply", "Apply selection"),
        Binding("escape", "cancel", "Cancel"),
    ]
    DEFAULT_CSS = """
    ConflictResolutionScreen {
        align: center middle;
    }
    #conflict-dialog {
        width: 95%;
        height: 90%;
        border: heavy $primary;
        padding: 1 2;
        background: $surface;
    }
    #conflict-title {
        height: auto;
        margin-bottom: 1;
        text-style: bold;
    }
    #conflict-headings,
    .conflict-row {
        height: auto;
        width: 100%;
    }
    #conflict-fields {
        height: 1fr;
        scrollbar-gutter: stable;
    }
    .conflict-field-name {
        width: 18;
        padding: 1;
        text-style: bold;
    }
    .conflict-value {
        width: 1fr;
        min-width: 0;
        height: auto;
        min-height: 3;
        margin: 0 1;
        content-align: left middle;
        text-align: left;
    }
    .conflict-result {
        width: 1fr;
        height: auto;
        padding: 1;
    }
    #conflict-buttons {
        height: auto;
        margin-top: 1;
        align-horizontal: right;
    }
    #conflict-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, title: str, local: MergeValue, unpacked: MergeValue, selected: MergeValue | None) -> None:
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

    def _restore_choices(self, selected: MergeValue) -> None:
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
        with Vertical(id="conflict-dialog"):
            yield Static(Text(f"Resolve values for {self.title}"), id="conflict-title")
            yield Static("Click a local or unpacked value in each row. Highlighted values form the merged record.")
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
                            variant="primary" if self.choices.get(index) == "local" else "default",
                        )
                        local_button.tooltip = _display_value(field.local, field.local_present)
                        yield local_button
                        unpacked_button = Button(
                            self._button_label(index, "unpacked"),
                            id=f"conflict-choice-unpacked-{index}",
                            classes="conflict-value",
                            variant="primary" if self.choices.get(index) == "unpacked" else "default",
                        )
                        unpacked_button.tooltip = _display_value(field.unpacked, field.unpacked_present)
                        yield unpacked_button
                        yield Static(
                            self._selected_label(index), id=f"conflict-result-{index}", classes="conflict-result"
                        )
            with Horizontal(id="conflict-buttons"):
                yield Button("Cancel", id="conflict-cancel")
                yield Button(
                    "Apply selection",
                    id="conflict-apply",
                    variant="success",
                    disabled=not self._all_fields_selected(),
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

    def _build_result(self) -> MergeValue:
        if isinstance(self.local, bytes):
            selected = self.local if self.choices[0] == "local" else self.unpacked
            if not isinstance(selected, bytes):
                raise TypeError("Finding content must be bytes.")
            return selected
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

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("conflict-choice-"):
            _, _, source, index_text = button_id.rsplit("-", 3)
            index = int(index_text)
            self.choices[index] = source
            for choice in ("local", "unpacked"):
                button = self.query_one(f"#conflict-choice-{choice}-{index}", Button)
                button.label = self._button_label(index, choice)
                button.variant = "primary" if choice == source else "default"
            self.query_one(f"#conflict-result-{index}", Static).update(self._selected_label(index))
            self.query_one("#conflict-apply", Button).disabled = not self._all_fields_selected()
        elif button_id == "conflict-apply":
            self.action_apply()
        elif button_id == "conflict-cancel":
            self.action_cancel()


class MergeComparisonTable(DataTable[str | Text]):
    def on_click(self, event: events.Click) -> None:
        row = event.style.meta.get("row")
        column = event.style.meta.get("column")
        if (
            column == 3
            and isinstance(row, int)
            and 0 <= row < self.row_count
            and not event.style.meta.get("out_of_bounds", False)
        ):
            event.prevent_default()
            event.stop()
            self.move_cursor(row=row, column=column)
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
        self.findings = discover_merge_findings(
            local_dir,
            unpacked_dir,
            self.targets,
            {target.key for target in self.targets},
        )
        self.rows: list[MergeRow] = [*self.dates, *self.people, *self.targets, *self.findings]
        self.statuses: dict[MergeKey, MergeStatus] = {record.key: record.default_status for record in self.rows}
        self.resolved_values: ResolvedMergeValues = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="merge-layout"):
            yield Static(
                "Compare local and unpacked records. Click Action (or press Space) to change a selection or "
                "resolve a conflict. Excluding a target also excludes its findings.",
                id="merge-help",
            )
            yield MergeComparisonTable(id="merge-table", cursor_type="cell", zebra_stripes=True)
            with Horizontal(id="merge-buttons"):
                yield Button("All local", id="merge-all-local")
                yield Button("All unpacked", id="merge-all-unpacked")
                yield Button("Cancel", id="merge-cancel")
                yield Button("Apply merge", id="merge-apply", variant="success")
        yield Footer()

    def on_mount(self) -> None:
        self._populate_table()
        self.query_one("#merge-table", DataTable).focus()
        self._update_apply_button()

    def on_resize(self, event: events.Resize) -> None:
        if self.is_mounted and self.query_one("#merge-table", DataTable).columns:
            self._populate_table()

    def _populate_table(self) -> None:
        table = cast(DataTable[str | Text], self.query_one("#merge-table", DataTable))
        cursor = table.cursor_coordinate
        table.clear(columns=True)
        record_width = max(12, (self.size.width - 54) // 2)
        for label, key, width in (
            ("Local Project", "local", record_width),
            ("Unpacked Project", "unpacked", record_width),
            ("Status", "status", 18),
            ("Action", "action", 22),
        ):
            table.add_column(label, key=key, width=width)
        for index, record in enumerate(self.rows):
            table.add_row(
                Text(self._record_label(record, record.local)) if record.in_local else "—",
                Text(self._record_label(record, record.unpacked)) if record.in_unpacked else "—",
                self._init_status_label(record),
                f"[bold italic]{self._action_label(record)}[/bold italic]",
                key=str(index),
            )
        table.move_cursor(row=cursor.row, column=cursor.column, animate=False)

    @staticmethod
    def _record_label(record: MergeRow, value: MergeValue | None = None) -> str:
        if isinstance(record, MergeDate):
            date = value.get("date", "") if isinstance(value, dict) else ""
            return f"Date: {record.key.version} / {record.key.type} / {date}"
        if isinstance(record, MergePerson):
            value = value if isinstance(value, dict) else record.local or record.unpacked or {}
            identity = value.get("name") or value.get("email") or record.key.email
            return f"Person: {record.key.version} / {identity}"
        if isinstance(record, MergeTarget):
            return f"Target: {record.key.version} / {record.key.category.upper()} / {record.key.name}"
        target = record.key.target
        return f"Finding: {target.version} / {target.name} / {record.key.name}"

    def _init_status_label(self, record: MergeRow) -> str:
        if self._is_excluded(record):
            return "Excluded"
        if record.key in self.resolved_values:
            return "Resolved"
        if not record.in_local:
            return "Unpacked only"
        if not record.in_unpacked:
            return "Local only"
        if record.is_identical:
            return "Identical"
        if record.is_conflict:
            return "[bold red]Conflict"
        return f"Mergeable ({self.statuses[record.key].value})"

    def _current_status_label(self, record: MergeRow) -> str:
        state = self.statuses.get(record.key)
        match state:
            case MergeStatus.EXCLUDED:
                return "Excluded"
            case MergeStatus.MERGED:
                return "Resolved"
            case MergeStatus.UNPACKED:
                return "Unpacked only"
            case MergeStatus.LOCAL:
                return "Local only"
            case _:
                return "Unknown"

    def _action_label(self, record: MergeRow) -> str:
        if isinstance(record, MergeFinding) and self.statuses.get(record.key.target) is MergeStatus.EXCLUDED:
            return "Include target first"
        if not record.in_local or not record.in_unpacked:
            return "Include" if self._is_excluded(record) else "Exclude"
        if record.is_conflict:
            return "Edit" if record.key in self.resolved_values else "Resolve"
        if not record.is_identical:
            return "Change source"
        return "—"

    def _is_excluded(self, record: MergeRow) -> bool:
        return self.statuses[record.key] is MergeStatus.EXCLUDED or (
            isinstance(record, MergeFinding) and self.statuses[record.key.target] is MergeStatus.EXCLUDED
        )

    def _has_unresolved_conflicts(self) -> bool:
        return any(
            record.is_conflict and not self._is_excluded(record) and record.key not in self.resolved_values
            for record in self.rows
        )

    def _current_record(self) -> MergeRow | None:
        table = cast(DataTable[str | Text], self.query_one("#merge-table", DataTable))
        if not self.rows or table.cursor_row >= len(self.rows):
            return None
        return self.rows[table.cursor_row]

    def _update_row(self, index: int, record: MergeRow) -> None:
        table = cast(DataTable[str | Text], self.query_one("#merge-table", DataTable))
        row_key = str(index)
        self.notify(f"Updating row {self._current_status_label(record)}", severity="warning")
        table.update_cell(row_key, "status", self._current_status_label(record))
        table.update_cell(row_key, "action", f"[bold italic]{self._action_label(record)}[/bold italic]")
        if isinstance(record, MergeTarget):
            for finding_index, finding in enumerate(self.rows):
                if isinstance(finding, MergeFinding) and finding.key.target == record.key:
                    table.update_cell(str(finding_index), "status", self._current_status_label(finding))
                    table.update_cell(
                        str(finding_index), "action", f"[bold italic]{self._action_label(finding)}[/bold italic]"
                    )
        self._update_apply_button()

    def _update_apply_button(self) -> None:
        self.query_one("#merge-apply", Button).disabled = self._has_unresolved_conflicts()

    def action_toggle_item(self) -> None:
        record = self._current_record()
        if record is None or record.is_identical:
            return
        if isinstance(record, MergeFinding) and self.statuses[record.key.target] is MergeStatus.EXCLUDED:
            self.notify("Include the target before changing its findings.", severity="warning")
            return
        if record.is_conflict:
            self.action_resolve()
            return
        choices = record.available_statuses
        current = self.statuses[record.key]
        self.statuses[record.key] = choices[(choices.index(current) + 1) % len(choices)]
        self.resolved_values.pop(record.key, None)
        table = cast(DataTable[str | Text], self.query_one("#merge-table", DataTable))
        self._update_row(table.cursor_row, record)

    def action_resolve(self) -> None:
        if not self.query_one("#merge-table", DataTable).has_focus:
            return
        record = self._current_record()
        if record is None:
            return
        if not record.is_conflict:
            self.action_toggle_item()
            return
        if record.local is None or record.unpacked is None:
            return
        self.app.push_screen(
            ConflictResolutionScreen(
                self._record_label(record),
                record.local,
                record.unpacked,
                self.resolved_values.get(record.key),
            ),
            lambda selected: self._resolution_finished(record, selected),
        )

    def _resolution_finished(self, record: MergeRow, selected: MergeValue | None) -> None:
        if selected is not None:
            self.resolved_values[record.key] = selected
            index = self.rows.index(record)
            self._update_row(index, record)

    @on(DataTable.CellSelected, "#merge-table")
    def action_cell_selected(self, event: DataTable.CellSelected) -> None:
        if event.coordinate.column == 3:
            self.action_resolve()

    def action_submit(self) -> None:
        if self._has_unresolved_conflicts():
            self.notify("Resolve each conflicting record before applying.", severity="warning")
            return
        try:
            apply_entity_merge(
                self.local_dir,
                self.unpacked_dir,
                self.dates,
                self.people,
                self.targets,
                self.findings,
                self.statuses,
                self.resolved_values,
            )
        except (OSError, ValueError, TypeError) as exc:
            self.notify(f"Could not apply merge: {exc}", severity="error", timeout=10)
            return
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_all_local(self) -> None:
        for record in self.rows:
            self.statuses[record.key] = MergeStatus.LOCAL if record.local is not None else MergeStatus.EXCLUDED
        # Refresh the table to reflect the updated statuses
        self.refresh()

    def action_all_unpacked(self) -> None:
        for record in self.rows:
            status = MergeStatus.UNPACKED if record.unpacked is not None else MergeStatus.EXCLUDED
            self.statuses[record.key] = status
            if record.is_conflict and status is MergeStatus.UNPACKED:
                self.resolved_values[record.key] = record.value_for(status)
                self._update_row(self.rows.index(record), record)

    @on(Button.Pressed, "#merge-all-local")
    def all_local(self) -> None:
        self.action_all_local()

    @on(Button.Pressed, "#merge-all-unpacked")
    def all_unpacked(self) -> None:
        self.action_all_unpacked()

    @on(Button.Pressed, "#merge-cancel")
    def cancel(self) -> None:
        self.action_cancel()

    @on(Button.Pressed, "#merge-apply")
    def apply(self) -> None:
        self.action_submit()
