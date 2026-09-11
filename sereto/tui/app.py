"""Unified SeReTo TUI application.

This module provides the single continuous TUI that replaces/pushes screens on top
of each other. The entry point is :func:`launch_tui`.

Screen stack (outermost → innermost):
  ProjectBrowserScreen  – always present
  ConfigScreen / RenderScreen / FindingSearchScreen / plugin's screen(s)
  FindingPreviewScreen  – modal pushed on top of FindingSearchScreen
  AddSubFindingScreen   – modal pushed on top of FindingSearchScreen
"""

from __future__ import annotations

import re
import shutil
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, cast

from pydantic import TypeAdapter, ValidationError
from rich.console import RenderableType
from rich.markup import escape
from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen, Screen
from textual.types import NoSelection
from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Rule, Select, Static, TabbedContent, TabPane

from sereto.config import VersionConfig
from sereto.enums import Risk
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.date import TYPES_WITH_ALLOWED_RANGE, Date, DateRange, DateType, SeretoDate
from sereto.models.person import Person, PersonType
from sereto.models.target import TargetDastModel, TargetMobileModel, TargetModel, TargetSastModel
from sereto.project import Project, is_project_dir, new_project
from sereto.retest import add_retest
from sereto.sereto_types import TypeProjectId
from sereto.settings import load_settings_function
from sereto.target import Target
from sereto.tui.finding import SearchWidget
from sereto.tui.widgets.input import InputWithLabel


# ── Parent screen for poppable screens ─────────────────────────────────────────
class _PoppableScreen(Screen[None]):
    """Base for screens that exit via Escape with priority over child widgets."""

    BINDINGS = [Binding("escape", "pop_screen", "Back", priority=True)]

    def action_pop_screen(self) -> None:
        self.app.pop_screen()


# ── Delete Confirmation dialog ───────────────────────────────────────────────────────
class DeleteConfirmationScreen(ModalScreen[bool]):
    """Generic yes/no modal. Dismisses with 'True' on Confirm, 'False' on Cancel."""

    AUTO_FOCUS = "#confirm-yes"
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self._message, id="confirm-message", markup=True)
            with Horizontal(id="confirm-buttons"):
                yield Button("Cancel", variant="default", id="confirm-no")
                yield Button("Confirm", variant="success", id="confirm-yes")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")

    def action_cancel(self) -> None:
        self.dismiss(False)


# ── Target JSON view modal ─────────────────────────────────────────────────────
class RecordDetailScreen(ModalScreen[None]):
    """Read-only modal showing plain content or labeled detail rows."""

    BINDINGS = [Binding("escape", "close", "Close", priority=True)]

    def __init__(
        self,
        title: str,
        content: RenderableType | None = None,
        *,
        details: tuple[tuple[str, str, str | None], ...] | None = None,
    ) -> None:
        super().__init__()
        self._title = title
        self._content = content
        self._details = details

    def compose(self) -> ComposeResult:
        title_escaped = escape(self._title)
        title_prefix, separator, title_suffix = title_escaped.partition("  ")

        title_markup = f"[cyan]{title_prefix}[/cyan]{separator}{title_suffix}"

        with Vertical(id="record-detail-dialog"):
            yield Label(f"[b]{title_markup}[/b]", id="record-detail-title")
            with ScrollableContainer(id="record-detail-body"):
                if self._details is None:
                    yield Static(self._content or "", id="record-detail-content", expand=True)
                else:
                    for icon, tooltip, value in self._details:
                        with Horizontal(classes="record-detail-row"):
                            icon_widget = Static(icon, classes="record-detail-icon")
                            icon_widget.tooltip = tooltip
                            yield icon_widget
                            yield Static(value or "—", classes="record-detail-value")
            with Horizontal(id="record-detail-buttons"):
                yield Button("Close", variant="default", id="record-detail-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


def _highlight_json(json_text: str) -> Text:
    """Highlight serialized JSON using one style for keys and one for everything else."""
    text = Text(json_text, style="white")
    key_pattern = r'(?m)^\s*(?P<key>"(?:\\.|[^"\\])*")(?=\s*:)'
    for match in re.finditer(key_pattern, json_text):
        text.stylize("medium_purple4", *match.span("key"))
    return text


@dataclass(frozen=True)
class _TargetFormData:
    category: str
    name: str


@dataclass(frozen=True)
class _DateFormData:
    type: DateType
    start: str
    end: str


@dataclass(frozen=True)
class _PersonFormData:
    type: PersonType
    name: str
    business_unit: str
    email: str
    role: str


type _ConfigFormData = _TargetFormData | _DateFormData | _PersonFormData


class ConfigRecordFormScreen(ModalScreen[_ConfigFormData | None]):
    """Modal form for adding or editing a target, date, or person."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "submit", "Submit", priority=True),
    ]

    def __init__(
        self,
        kind: str,
        *,
        categories: list[str] | None = None,
        initial: _ConfigFormData | None = None,
    ) -> None:
        super().__init__()
        self._kind = kind
        self._categories = categories or []
        self._initial = initial

    def compose(self) -> ComposeResult:
        action = "Edit" if self._initial is not None else "Add"
        with Vertical(id="config-record-dialog"):
            yield Label(f"{action} {self._kind}", id="config-record-title")
            with ScrollableContainer(id="config-record-fields"):
                if self._kind == "target":
                    target_initial = self._initial if isinstance(self._initial, _TargetFormData) else None
                    with Horizontal(classes="field-row"):
                        yield Label("Category", classes="field-label")
                        yield Select[str](
                            [(category, category.lower()) for category in self._categories],
                            id="modal-target-category",
                            prompt="Select category…",
                            value=target_initial.category if target_initial else Select.NULL,
                            disabled=target_initial is not None,
                        )
                    yield InputWithLabel(
                        Input(
                            value=target_initial.name if target_initial else "",
                            id="modal-target-name",
                            placeholder="Target name…",
                        ),
                        "Name",
                    )
                elif self._kind == "date":
                    date_initial = self._initial if isinstance(self._initial, _DateFormData) else None
                    with Horizontal(classes="field-row"):
                        yield Label("Type", classes="field-label")
                        yield Select[DateType](
                            [(date_type.value.replace("_", " ").title(), date_type) for date_type in DateType],
                            value=date_initial.type if date_initial else Select.NULL,
                            id="modal-date-type",
                            prompt="Select type…",
                        )
                    yield InputWithLabel(
                        Input(
                            value=date_initial.start if date_initial else "",
                            id="modal-date-start",
                            placeholder="DD-Mmm-YYYY",
                        ),
                        "Start",
                    )
                    yield InputWithLabel(
                        Input(
                            value=date_initial.end if date_initial else "",
                            id="modal-date-end",
                            placeholder="DD-Mmm-YYYY (optional)",
                        ),
                        "End",
                        id="modal-date-end-row",
                    )
                else:
                    person_initial = self._initial if isinstance(self._initial, _PersonFormData) else None
                    with Horizontal(classes="field-row"):
                        yield Label("Type", classes="field-label")
                        yield Select[PersonType](
                            [(person_type.value.replace("_", " ").title(), person_type) for person_type in PersonType],
                            value=person_initial.type if person_initial else Select.NULL,
                            id="modal-person-type",
                            prompt="Select type…",
                        )
                    yield InputWithLabel(
                        Input(
                            value=person_initial.name if person_initial else "",
                            id="modal-person-name",
                            placeholder="Full name",
                        ),
                        "Name",
                    )
                    yield InputWithLabel(
                        Input(
                            value=person_initial.business_unit if person_initial else "",
                            id="modal-person-bu",
                            placeholder="Business unit",
                        ),
                        "BU",
                    )
                    yield InputWithLabel(
                        Input(
                            value=person_initial.email if person_initial else "",
                            id="modal-person-email",
                            placeholder="user@example.com",
                        ),
                        "Email",
                    )
                    yield InputWithLabel(
                        Input(
                            value=person_initial.role if person_initial else "",
                            id="modal-person-role",
                            placeholder="Role",
                        ),
                        "Role",
                    )
            with Horizontal(id="config-record-buttons"):
                yield Button("Cancel", id="config-record-cancel")
                yield Button("Save", variant="success", id="config-record-save")

    def on_mount(self) -> None:
        if self._kind == "date":
            date_type = cast(DateType | NoSelection, self.query_one("#modal-date-type", Select).value)
            self._set_date_end_visibility(date_type)

    @on(Select.Changed, "#modal-date-type")
    def handle_date_type_changed(self, event: Select.Changed) -> None:
        self._set_date_end_visibility(cast(DateType | NoSelection, event.value))

    def _set_date_end_visibility(self, date_type: DateType | NoSelection) -> None:
        end_row = self.query_one("#modal-date-end-row", InputWithLabel)
        end_input = self.query_one("#modal-date-end", Input)
        end_row.display = date_type in TYPES_WITH_ALLOWED_RANGE
        if not end_row.display:
            end_input.value = ""

    @on(Button.Pressed, "#config-record-cancel")
    def handle_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#config-record-save")
    def handle_save(self) -> None:
        if self._kind == "target":
            target_initial = self._initial if isinstance(self._initial, _TargetFormData) else None
            if target_initial is not None:
                category = target_initial.category
            else:
                selected_category = cast(str | NoSelection, self.query_one("#modal-target-category", Select).value)
                if isinstance(selected_category, NoSelection):
                    self.notify("Select a category.", severity="warning", timeout=3)
                    return
                category = selected_category
            name = self.query_one("#modal-target-name", Input).value.strip()
            if not name:
                self.notify("Enter a target name.", severity="warning", timeout=3)
                return
            self.dismiss(_TargetFormData(category, name))
        elif self._kind == "date":
            date_type = cast(DateType | NoSelection, self.query_one("#modal-date-type", Select).value)
            if isinstance(date_type, NoSelection):
                self.notify("Select a date type.", severity="warning", timeout=3)
                return
            start_text = self.query_one("#modal-date-start", Input).value.strip()
            end_text = self.query_one("#modal-date-end", Input).value.strip()
            if not start_text:
                self.notify("Start date is required.", severity="warning", timeout=3)
                return
            try:
                start = SeretoDate(start_text)
                date_value: SeretoDate | DateRange = start
                if end_text:
                    date_value = DateRange(start=start, end=SeretoDate(end_text))
                Date(type=DateType(date_type), date=date_value)
            except (ValueError, ValidationError) as exc:
                self.notify(str(exc), title="Invalid date", severity="error", markup=False)
                return
            self.dismiss(
                _DateFormData(
                    DateType(date_type),
                    start_text,
                    end_text,
                )
            )
        else:
            person_type = cast(PersonType | NoSelection, self.query_one("#modal-person-type", Select).value)
            if isinstance(person_type, NoSelection):
                self.notify("Select a person type.", severity="warning", timeout=3)
                return
            if not self.query_one("#modal-person-name", Input).value.strip():
                self.notify("Person name is required.", severity="warning", timeout=3)
                return
            result = _PersonFormData(
                PersonType(person_type),
                self.query_one("#modal-person-name", Input).value.strip(),
                self.query_one("#modal-person-bu", Input).value.strip(),
                self.query_one("#modal-person-email", Input).value.strip(),
                self.query_one("#modal-person-role", Input).value.strip(),
            )
            try:
                Person(
                    type=result.type,
                    name=result.name or None,
                    business_unit=result.business_unit or None,
                    email=result.email or None,
                    role=result.role or None,
                )
            except ValidationError as exc:
                self.notify(str(exc), title="Invalid person", severity="error", markup=False)
                return
            self.dismiss(result)

    # ── Actions ───────────────────────────────────────────────────────────────
    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        self.handle_save()


# ── Risk label helpers ─────────────────────────────────────────────────────────
_RISK_STYLE: dict[Risk, str] = {
    Risk.critical: "bold red3",
    Risk.high: "bold dark_orange",
    Risk.medium: "bold yellow1",
    Risk.low: "bold chartreuse2",
    Risk.info: "bold dodger_blue2",
}


def _risk_text(risk: Risk) -> Text:
    return Text(risk.capitalize(), style=_RISK_STYLE.get(risk, ""))


# ── Finding search screen ──────────────────────────────────────────────────────
class FindingSearchScreen(_PoppableScreen):
    """Full-screen wrapper around :class:`SearchWidget` for the unified TUI.

    Pushed on top of :class:`ProjectBrowserScreen` when the user wants to add a
    new finding to the currently selected project.
    """

    def compose(self) -> ComposeResult:
        search = SearchWidget()
        search.id = "search"
        yield Header()
        yield search
        yield Footer()

    def on_mount(self) -> None:
        app: SeretoUnifiedApp = self.app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        all_targets = [t for v in app.project.config.versions for t in app.project.config.at_version(v).targets]
        if not all_targets:
            self.notify(
                "No targets found in this project. Add them via 'Config' button.", severity="warning", timeout=3
            )
            app.pop_screen()
            return
        self.query_one(SearchWidget).input_field.focus()

    def action_focus_search(self) -> None:
        """Re-focus the search input after a sub-finding has been saved."""
        self.query_one(SearchWidget).input_field.focus()


# ── Config screen ──────────────────────────────────────────────────────────────
class ConfigScreen(_PoppableScreen):
    """Screen for managing the project configuration (general info, targets, dates, people)."""

    SUB_TITLE = "Project Configuration"

    BINDINGS = [Binding("a", "add_new", "Add")]

    # Entry points that just select their matching tab (`tab-<entry_point>`),
    # e.g. `sereto config targets add` → launch_tui(entry_point="targets").
    TABS: ClassVar[frozenset[str]] = frozenset({"targets", "dates", "people"})

    def __init__(self, initial_tab: str | None = None) -> None:
        super().__init__()
        self._initial_tab = initial_tab

    @property
    def _active_vc(self) -> VersionConfig:
        return self.app.project.config.at_version(self.app.selected_project_version)  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]

    @staticmethod
    def _table_header(add_btn_id: str, *columns: tuple[str, str]) -> ComposeResult:
        """Yield a light-table header row: (label, css-class) column pairs + a trailing 'Add new' button."""
        with Horizontal(classes="table-header"):
            for label, css_class in columns:
                yield Static(label, classes=f"table-header-cell {css_class}")
            yield Button("Add new", id=add_btn_id, variant="success", classes="table-header-add-btn")

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="config-tabs"):
            with TabPane("General", id="tab-general"), ScrollableContainer(id="general-form"):
                yield InputWithLabel(Input(value=self._active_vc.id, id="cfg-id"), "ID")
                yield InputWithLabel(Input(value=self._active_vc.name, id="cfg-name"), "Name")
                yield InputWithLabel(Input(value=self._active_vc.version_description, id="cfg-version-desc"), "Desc")
                with Horizontal(classes="config-add-row"):
                    yield Button("Save", variant="success", id="save-general")
            with TabPane("Targets", id="tab-targets"), Vertical(classes="tab-container"):
                yield from self._table_header(
                    "scroll-add-targets-btn",
                    ("Category", "table-header-category"),
                    ("Name", "table-header-name"),
                )
                with ScrollableContainer(id="targets-form"):
                    yield Vertical(id="targets-list")
            with TabPane("Dates", id="tab-dates"), Vertical(classes="tab-container"):
                yield from self._table_header(
                    "scroll-add-dates-btn",
                    ("Type", "table-header-type"),
                    ("Start date", "table-header-start"),
                    ("End date", "table-header-end"),
                )
                with ScrollableContainer(id="dates-form"):
                    yield Vertical(id="dates-list")
            with TabPane("People", id="tab-people"), Vertical(classes="tab-container"):
                yield from self._table_header(
                    "scroll-add-people-btn",
                    ("Type", "table-header-type"),
                    ("Name", "table-header-name"),
                )
                with ScrollableContainer(id="people-form"):
                    yield Vertical(id="people-list")
        yield Footer()

    def on_mount(self) -> None:
        app: SeretoUnifiedApp = self.app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

        # Disable the sliding animation on the tab underline bar
        from textual.widgets import Tabs

        _tabs = self.query_one("#config-tabs").query_one(Tabs)
        _orig_highlight = _tabs.__class__._highlight_active
        _tabs._highlight_active = lambda animate=True: _orig_highlight(_tabs, animate=False)  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
        tab = self._initial_tab
        if tab is None and app.entry_point in self.TABS:
            tab = f"tab-{app.entry_point}"
        if tab is not None:
            self.query_one("#config-tabs", TabbedContent).active = tab
        # Load project's configuration data
        self._refresh_targets()
        self._refresh_dates()
        self._refresh_people()

    # ── Button handlers ────────────────────────────────────────────────────────
    @on(Button.Pressed, "#save-general")
    def handle_save_general(self) -> None:
        self._do_save_general()

    @on(Button.Pressed, "#scroll-add-targets-btn, #scroll-add-dates-btn, #scroll-add-people-btn")
    def handle_add_record(self, event: Button.Pressed) -> None:
        """Open the matching record form from a table header's Add new button."""
        button_id = event.button.id or ""
        tab_name = button_id.removeprefix("scroll-add-").removesuffix("-btn")
        if tab_name == "targets":
            self._open_target_form()
        elif tab_name == "dates":
            self._open_date_form()
        elif tab_name == "people":
            self._open_person_form()

    @on(Button.Pressed, ".config-ppl-remove-btn, .config-targets-remove-btn, .config-date-remove-btn")
    def handle_remove(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        button_id = button_id.removeprefix("remove-")

        # focus the button that was pressed
        event.button.focus()

        for type_prefix in ("target", "date", "person"):
            if button_id.startswith(f"{type_prefix}-"):
                index = int(button_id.removeprefix(f"{type_prefix}-"))
                self._confirm_remove(type_prefix, index)
                return

    def _confirm_remove(self, kind: str, index: int) -> None:
        """Push a Yes/No confirmation, then delete the record of *kind* at *index* on confirm."""
        handler_map = {
            "target": self._do_remove_target,
            "date": self._do_remove_date,
            "person": self._do_remove_person,
        }
        handler = handler_map[kind]
        self.app.push_screen(
            DeleteConfirmationScreen(f"Remove this {kind}?"),
            callback=lambda confirmed, i=index, h=handler: h(i) if confirmed else None,
        )

    @on(Button.Pressed, ".config-ppl-edit-btn, .config-targets-edit-btn, .config-date-edit-btn")
    def handle_edit(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        button_id = button_id.removeprefix("edit-")

        # focus the button that was pressed
        event.button.focus()

        handler_map = {
            "target": self._open_target_form,
            "date": self._open_date_form,
            "person": self._open_person_form,
        }
        for type_prefix, handler in handler_map.items():
            if button_id.startswith(f"{type_prefix}-"):
                handler(int(button_id.removeprefix(f"{type_prefix}-")))
                return

    def show_target_detail(self, target: Target) -> None:
        title = f"{target.data.category.upper()}  {target.data.name}"
        content = _highlight_json(target.data.model_dump_json(indent=2, exclude_none=True))
        self.app.push_screen(RecordDetailScreen(title=title, content=content))

    def show_person_detail(self, person: Person) -> None:
        type_label = person.type.value.replace("_", " ").title()
        title = f"{type_label}  {person.name or '(no name)'}"
        details = (
            ("🏢", "Business unit", person.business_unit),
            ("📧", "Email", person.email),
            ("👔", "Role", person.role),
        )
        self.app.push_screen(RecordDetailScreen(title=title, details=details))

    # ── List refresh ───────────────────────────────────────────────────────────
    def _refresh_targets(self) -> None:
        container = self.query_one("#targets-list", Vertical)
        container.remove_children()
        for i, t in enumerate(self._active_vc.targets, start=1):
            container.mount(_TargetRow(t, i))

    def sort_key(self, d: Date) -> tuple[SeretoDate, SeretoDate]:
        if isinstance(d.date, DateRange):
            return (d.date.start, d.date.end)
        else:
            return (d.date, d.date)

    def _refresh_dates(self) -> None:
        container = self.query_one("#dates-list", Vertical)
        container.remove_children()
        # Keep each date paired with its real (1-based) index in the underlying config list,
        # since that's what add_date/delete_date/list-item-assignment expect — the display
        # order below is sorted and does not match it.
        indexed_dates = list(enumerate(self._active_vc.dates, start=1))
        sorted_dates = sorted(indexed_dates, key=lambda pair: self.sort_key(pair[1]), reverse=True)
        for index, d in sorted_dates:
            container.mount(_DateRow(d, index))

    def _refresh_people(self) -> None:
        container = self.query_one("#people-list", Vertical)
        container.remove_children()
        # Same real-index caveat as _refresh_dates — display order is sorted by type.
        indexed_people = list(enumerate(self._active_vc.people, start=1))
        sorted_people = sorted(indexed_people, key=lambda pair: pair[1].type.value)
        for index, p in sorted_people:
            container.mount(_PersonRow(p, index))

    # ── Targets tab actions ────────────────────────────────────────────────────
    def _open_target_form(self, index: int | None = None) -> None:
        target = self._active_vc.targets[index - 1] if index is not None else None
        initial = _TargetFormData(target.data.category, target.data.name) if target is not None else None
        app: SeretoUnifiedApp = self.app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        self.app.push_screen(
            ConfigRecordFormScreen("target", categories=app.categories, initial=initial),
            callback=lambda result: self._save_target(result, index),
        )

    def _save_target(self, result: _ConfigFormData | None, index: int | None) -> None:
        if not isinstance(result, _TargetFormData):
            return
        if not result.name:
            self.notify("Enter a target name.", severity="warning", timeout=3)
            return

        model_class: type[TargetModel]
        match result.category:
            case "dast":
                model_class = TargetDastModel
            case "sast":
                model_class = TargetSastModel
            case "mobile":
                model_class = TargetMobileModel
            case _:
                model_class = TargetModel

        try:
            target_model = model_class.model_validate({"category": result.category, "name": result.name})
        except ValidationError as exc:
            self.notify(str(exc), title="Validation error", severity="error", markup=False)
            return

        if index is not None:
            target = self._active_vc.targets[index - 1]
            try:
                target.data.name = target_model.name
                self.app.project.config.save()  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
            except Exception as exc:
                self.notify(str(exc), title="Failed to update target", severity="error", markup=False)
                return

            self._refresh_targets()
            self.notify(result.name, title="Target updated", timeout=3)
            for screen in self.app.screen_stack:
                if isinstance(screen, ProjectBrowserScreen):
                    screen.refresh_content()
                    break
            return

        project = self.app.project  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        version = self.app.selected_project_version  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]

        try:
            new_target = Target.new(
                data=target_model,
                project_path=project.path,
                templates=project.settings.templates_path,
                version=version,
            )
            self._active_vc.add_target(new_target)
            project.config.save()
        except Exception as exc:
            self.notify(str(exc), title="Failed to create target", severity="error", markup=False)
            return

        self._refresh_targets()
        self.notify(result.name, title="Target added", timeout=3)

        # Refresh the project browser to show the new target
        for screen in self.app.screen_stack:
            if isinstance(screen, ProjectBrowserScreen):
                screen.refresh_content()
                break

    def _do_remove_target(self, index: int) -> None:
        try:
            vc = self._active_vc
            target_path = vc.targets[index - 1].path
            vc.delete_target(index)
            self.app.project.config.save()  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
            if target_path.is_dir():
                shutil.rmtree(target_path)
            self._refresh_targets()
            self.notify("Target removed.", timeout=3)
            # Refresh the project browser to show the updated targets
            for screen in self.app.screen_stack:
                if isinstance(screen, ProjectBrowserScreen):
                    screen.refresh_content()
                    break
        except Exception as exc:
            self.notify(str(exc), title="Failed to remove target", severity="error", markup=False)

    # ── General tab actions ────────────────────────────────────────────────────
    def _do_save_general(self) -> None:
        vc = self._active_vc
        id_val = self.query_one("#cfg-id", Input).value.strip()
        name_val = self.query_one("#cfg-name", Input).value.strip()
        desc_val = self.query_one("#cfg-version-desc", Input).value.strip()

        if id_val:
            ta: TypeAdapter[TypeProjectId] = TypeAdapter(TypeProjectId)
            try:
                ta.validate_python(id_val)
            except ValidationError:
                self.notify(
                    "Project ID must be 1–20 characters: letters, digits, '.', '_', '-'.",
                    severity="error",
                )
                return
        else:
            id_val = vc.id  # keep the existing ID if the input is empty

        if not name_val:
            name_val = vc.name  # keep the existing name if the input is empty

        vc.id = id_val
        vc.name = name_val
        vc.version_description = desc_val

        try:
            self.app.project.config.save()  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
            self.notify("General settings saved.", timeout=3)
            # Update the project select options to reflect the new name/ID
            for screen in self.app.screen_stack:
                if isinstance(screen, ProjectBrowserScreen):
                    screen.refresh_project_select()
                    break

        except Exception as exc:
            self.notify(str(exc), title="Save failed", severity="error", markup=False)

    # ── Dates tab actions ──────────────────────────────────────────────────────
    def _open_date_form(self, index: int | None = None) -> None:
        initial: _DateFormData | None = None
        if index is not None:
            date = self._active_vc.dates[index - 1]
            match date.date:
                case DateRange():
                    start, end = str(date.date.start), str(date.date.end)
                case _:
                    start, end = str(date.date), ""
            initial = _DateFormData(date.type, start, end)
        self.app.push_screen(
            ConfigRecordFormScreen("date", initial=initial),
            callback=lambda result: self._save_date(result, index),
        )

    def _save_date(self, result: _ConfigFormData | None, index: int | None) -> None:
        if not isinstance(result, _DateFormData):
            return
        if not result.start:
            self.notify("Start date is required.", severity="warning", timeout=3)
            return

        try:
            start = SeretoDate(result.start)
        except ValueError:
            self.notify(f"Invalid start date: {result.start!r}. Use DD-Mmm-YYYY.", severity="error", markup=False)
            return

        date_value: SeretoDate | DateRange

        if result.end:
            try:
                end = SeretoDate(result.end)
            except ValueError:
                self.notify(f"Invalid end date: {result.end!r}. Use DD-Mmm-YYYY.", severity="error", markup=False)
                return
            try:
                date_value = DateRange(start=start, end=end)
            except Exception as exc:
                self.notify(str(exc), title="Invalid date range", severity="error", markup=False)
                return
        else:
            date_value = start

        try:
            new_date = Date(type=result.type, date=date_value)
            if index is not None:
                self._active_vc.dates[index - 1] = new_date
            else:
                self._active_vc.add_date(new_date)
            self.app.project.config.save()  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        except Exception as exc:
            self.notify(str(exc), title="Failed to save date", severity="error", markup=False)
            return

        self._refresh_dates()
        self.notify("Date updated." if index is not None else "Date added.", timeout=3)

    def _do_remove_date(self, index: int) -> None:
        try:
            self._active_vc.delete_date(index)
            self.app.project.config.save()  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
            self._refresh_dates()
            self.notify("Date removed.", timeout=3)
        except Exception as exc:
            self.notify(str(exc), title="Failed to remove date", severity="error", markup=False)

    # ── People tab actions ─────────────────────────────────────────────────────
    def _open_person_form(self, index: int | None = None) -> None:
        person = self._active_vc.people[index - 1] if index is not None else None
        initial = (
            _PersonFormData(
                person.type,
                person.name or "",
                person.business_unit or "",
                person.email or "",
                person.role or "",
            )
            if person is not None
            else None
        )
        self.app.push_screen(
            ConfigRecordFormScreen("person", initial=initial),
            callback=lambda result: self._save_person(result, index),
        )

    def _save_person(self, result: _ConfigFormData | None, index: int | None) -> None:
        if not isinstance(result, _PersonFormData):
            return

        try:
            new_person = Person(
                type=result.type,
                name=result.name or None,
                business_unit=result.business_unit or None,
                email=result.email or None,
                role=result.role or None,
            )
            if index is not None:
                self._active_vc.people[index - 1] = new_person
            else:
                self._active_vc.add_person(new_person)
            self.app.project.config.save()  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        except Exception as exc:
            self.notify(str(exc), title="Failed to save person", severity="error", markup=False)
            return

        self._refresh_people()
        self.notify("Person updated." if index is not None else "Person added.", timeout=3)

    def _do_remove_person(self, index: int) -> None:
        try:
            self._active_vc.delete_person(index)
            self.app.project.config.save()  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
            self._refresh_people()
            self.notify("Person removed.", timeout=3)
        except Exception as exc:
            self.notify(str(exc), title="Failed to remove person", severity="error", markup=False)

    # ── Actions ───────────────────────────────────────────────────────────────
    def action_add_new(self) -> None:
        active_tab = self.query_one("#config-tabs", TabbedContent).active
        if active_tab == "tab-targets":
            self._open_target_form()
        elif active_tab == "tab-dates":
            self._open_date_form()
        elif active_tab == "tab-people":
            self._open_person_form()


# ── Config row widgets ─────────────────────────────────────────────────────────
class _NonSelectableStatic(Static):
    """A static widget that prevents selection of config row contents."""

    ALLOW_SELECT = False


class _ButtonHitArea(Horizontal):
    """Invisible container that expands a row button's clickable area."""

    def __init__(self, button: Button) -> None:
        super().__init__(classes="config-row-button-hit-area")
        self._button = button

    def compose(self) -> ComposeResult:
        yield self._button

    def on_click(self, event: events.Click) -> None:
        if event.widget is self:
            self.post_message(Button.Pressed(self._button))


class _DateRow(Horizontal):
    """Single row in the dates table: type, start date, end date + Edit/Remove buttons."""

    def __init__(self, date: Date, index: int) -> None:
        super().__init__(classes="date-row")
        self._date = date
        self._index = index  # 1-based

    def compose(self) -> ComposeResult:
        type_label = self._date.type.value.replace("_", " ").title()
        yield _NonSelectableStatic(f"[cyan]{type_label}[/cyan]", classes="date-type", markup=True)

        match self._date.date:
            case DateRange():
                start_text, end_text = str(self._date.date.start), str(self._date.date.end)
            case _:
                start_text, end_text = str(self._date.date), "\u2014"
        yield _NonSelectableStatic(start_text, classes="date-start")
        yield _NonSelectableStatic(end_text, classes="date-end")

        yield _ButtonHitArea(
            Button(
                "Edit",
                variant="primary",
                id=f"edit-date-{self._index}",
                classes="config-date-edit-btn",
                tooltip="Edit date",
            )
        )
        yield _ButtonHitArea(
            Button(
                "Remove",
                variant="error",
                id=f"remove-date-{self._index}",
                classes="config-date-remove-btn",
                tooltip="Remove date",
            )
        )


class _TargetRow(Horizontal):
    """Single row in the targets table: category, name + Edit/Remove buttons."""

    def __init__(self, target: Target, index: int) -> None:
        super().__init__(classes="target-row")
        self._target = target
        self._index = index  # 1-based

    def compose(self) -> ComposeResult:
        yield _NonSelectableStatic(
            f"[cyan]{self._target.data.category.upper()}[/cyan]", classes="target-category", markup=True
        )
        yield _NonSelectableStatic(self._target.data.name, classes="target-name")
        yield _ButtonHitArea(
            Button(
                "Edit",
                variant="primary",
                id=f"edit-target-{self._index}",
                classes="config-targets-edit-btn",
                tooltip="Edit target",
            )
        )
        yield _ButtonHitArea(
            Button(
                "Remove",
                variant="error",
                id=f"remove-target-{self._index}",
                classes="config-targets-remove-btn",
                tooltip="Remove target",
            )
        )

    def on_click(self, event: events.Click) -> None:
        if event.chain == 2 and isinstance(self.screen, ConfigScreen):
            self.screen.show_target_detail(self._target)


class _PersonRow(Horizontal):
    """Single row in the people table: type, name + Edit/Remove buttons."""

    def __init__(self, person: Person, index: int) -> None:
        super().__init__(classes="person-row")
        self._person = person
        self._index = index  # 1-based

    def compose(self) -> ComposeResult:
        type_label = self._person.type.value.replace("_", " ").title()
        yield _NonSelectableStatic(f"[cyan]{type_label}[/cyan]", classes="person-type-badge", markup=True)
        yield _NonSelectableStatic(self._person.name or "[dim](no name)[/dim]", classes="person-name", markup=True)
        yield _ButtonHitArea(
            Button(
                "Edit",
                variant="primary",
                id=f"edit-person-{self._index}",
                classes="config-ppl-edit-btn",
                tooltip="Edit person",
            )
        )
        yield _ButtonHitArea(
            Button(
                "Remove",
                variant="error",
                id=f"remove-person-{self._index}",
                classes="config-ppl-remove-btn",
                tooltip="Remove person",
            )
        )

    def on_click(self, event: events.Click) -> None:
        if event.chain == 2 and isinstance(self.screen, ConfigScreen):
            self.screen.show_person_detail(self._person)


# ── Render screen ─────────────────────────────────────────────────────────────
class RenderScreen(_PoppableScreen):
    """Screen for generating PDFs (report, SoW, targets, finding groups)."""

    SUB_TITLE = "Render PDF"

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="render-layout"):
            with Horizontal(id="render-controls"):
                yield Select[str](
                    [
                        ("Report", "report"),
                        ("SoW", "sow"),
                        ("Render finding group(s)", "fg"),
                        ("Render all finding groups", "all_fg"),
                    ],
                    id="render-type-select",
                    allow_blank=False,
                )
                with Vertical(id="fg-filters"):
                    yield Select[str]([], id="fg-target-select", allow_blank=True, prompt="All targets")
                    yield Select[str]([], id="fg-group-select", allow_blank=True, prompt="All groups")
                yield Button("Render", variant="primary", id="render-btn")
                yield Button("Clean build", variant="warning", id="render-clean-btn")
            yield RichLog(id="render-log", highlight=True, markup=True, wrap=True)
            yield Button("Open PDF", variant="success", id="open-pdf-btn", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self._last_pdf: Path | None = None
        self.query_one("#render-log", RichLog).write("[dim]Select a render action above.[/dim]")
        self._reload_fg_selectors()
        # Initially hide the finding group filters
        self.query_one("#fg-filters", Vertical).display = False

    # ── helpers ───────────────────────────────────────────────────────────────
    def _log(self, text: str) -> None:
        self.query_one("#render-log", RichLog).write(text)

    def _set_last_pdf(self, path: Path) -> None:
        self._last_pdf = path
        btn = self.query_one("#open-pdf-btn", Button)
        btn.disabled = False
        btn.label = f"Open  {path.name}"

    def _set_buttons_disabled(self, disabled: bool) -> None:
        for btn_id in (
            "#render-btn",
            "#render-clean-btn",
        ):
            self.query_one(btn_id, Button).disabled = disabled

    def _reload_fg_selectors(self) -> None:
        targets = self.app.project.config.at_version(self.app.selected_project_version).targets  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        target_options = [(f"{t.data.category.upper()}  {t.data.name}", t.data.uname) for t in targets]
        target_select = self.query_one("#fg-target-select", Select)
        fg_select = self.query_one("#fg-group-select", Select)
        target_select.set_options(target_options)
        target_select.clear()
        fg_select.set_options([])

    @on(Select.Changed, "#fg-target-select")
    def on_fg_target_changed(self, event: Select.Changed) -> None:
        fg_select = self.query_one("#fg-group-select", Select)
        if isinstance(event.value, NoSelection):
            fg_select.set_options([])
            return
        targets = self.app.project.config.at_version(self.app.selected_project_version).targets  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        target_uname = str(event.value)
        target = next((t for t in targets if t.data.uname == target_uname), None)
        if target is None:
            fg_select.set_options([])
            return
        fg_options = [(g.name, g.uname) for g in target.findings.groups]
        fg_select.set_options(fg_options)
        # Auto-select the first group if available
        if fg_options:
            fg_select.value = fg_options[0][1]

    # ── button handlers ───────────────────────────────────────────────────────
    @on(Select.Changed, "#render-type-select")
    def on_render_type_changed(self, event: Select.Changed) -> None:
        fg_filters = self.query_one("#fg-filters", Vertical)
        # Show filters only if "Render finding group(s)" is selected
        fg_filters.display = event.value == "fg"

    @on(Button.Pressed, "#render-btn")
    def handle_render(self) -> None:
        render_type_select = self.query_one("#render-type-select", Select)
        if isinstance(render_type_select.value, NoSelection):
            self.notify("Select a render type.", severity="warning", timeout=3)
            return
        render_type = render_type_select.value
        self._run_render(render_type)

    @on(Button.Pressed, "#open-pdf-btn")
    def handle_open_pdf(self) -> None:
        if self._last_pdf is not None:
            import webbrowser

            webbrowser.open(self._last_pdf.as_uri())

    @on(Button.Pressed, "#render-clean-btn")
    def handle_clean(self) -> None:
        self._do_clean()

    # ── workers ───────────────────────────────────────────────────────────────
    @work(thread=True)
    def _run_render(self, kind: str) -> None:
        from loguru import logger

        from sereto.pdf import (
            find_and_generate_pdf_finding_group,
            generate_all_pdf_finding_groups,
            generate_pdf_report,
            generate_pdf_sow,
        )

        self.app.call_from_thread(self._set_buttons_disabled, True)
        self.app.call_from_thread(self._log, f"[bold cyan]▶ Starting {kind} render…[/bold cyan]")

        # Forward Loguru records to the RichLog for the duration of this render
        def _tui_sink(message: logger.Record) -> None:  # type: ignore[name-defined]  # ty: ignore[unresolved-attribute]
            record = message.record
            level = record["level"].name.lower()
            text = record["message"].rstrip()
            style_map = {
                "info": "dim",
                "success": "bold green",
                "warning": "bold yellow",
                "error": "bold red",
                "critical": "bold red",
                "debug": "dim",
            }
            style = style_map.get(level, "")
            self.app.call_from_thread(
                self._log,
                f"[{style}]{text}[/{style}]" if style else text,
            )

        sink_id = logger.add(_tui_sink, format="{message}", colorize=False)

        project = self.app.project  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        version = self.app.selected_project_version  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]

        try:
            match kind:
                case "report":
                    from sereto.source_archive import create_source_archive, embed_attachment_to_pdf

                    pdf_path = generate_pdf_report(
                        project=project,
                        template="report",
                        version=version,
                    )
                    archive = create_source_archive(project_path=project.path, config=project.config)
                    embed_attachment_to_pdf(
                        attachment=archive,
                        pdf=pdf_path,
                        name=f"source{archive.suffix}",
                        keep_original=False,
                    )
                    self.app.call_from_thread(self._set_last_pdf, pdf_path)
                    self.app.call_from_thread(
                        self._log,
                        f"[bold green]✔ Report saved:[/bold green] {pdf_path}",
                    )
                case "sow":
                    pdf_path = generate_pdf_sow(
                        project=project,
                        sow_recipe=None,
                        version=version,
                    )
                    self.app.call_from_thread(self._set_last_pdf, pdf_path)
                    self.app.call_from_thread(
                        self._log,
                        f"[bold green]✔ SoW saved:[/bold green] {pdf_path}",
                    )
                case "fg":
                    target_sel = self.query_one("#fg-target-select", Select)
                    fg_sel = self.query_one("#fg-group-select", Select)
                    target_uname = None if isinstance(target_sel.value, NoSelection) else str(target_sel.value)
                    fg_uname = None if isinstance(fg_sel.value, NoSelection) else str(fg_sel.value)
                    pdf_path = find_and_generate_pdf_finding_group(
                        project=project,
                        template="finding_group",
                        target_selector=target_uname,
                        finding_group_selector=fg_uname,
                        converter=None,
                        renderer=None,
                        version=version,
                    )
                    self.app.call_from_thread(self._set_last_pdf, pdf_path)
                    self.app.call_from_thread(
                        self._log,
                        f"[bold green]✔ Finding group saved:[/bold green] {pdf_path}",
                    )
                case "all_fg":
                    paths = generate_all_pdf_finding_groups(
                        project=project,
                        template="finding_group",
                        converter=None,
                        renderer=None,
                        version=version,
                    )
                    for p in paths:
                        self.app.call_from_thread(
                            self._log,
                            f"[bold green]✔ Finding group:[/bold green] {p}",
                        )
                    self.app.call_from_thread(
                        self._log,
                        f"[bold green]Done — {len(paths)} finding group PDF(s) generated.[/bold green]",
                    )
        except Exception as exc:
            self.app.call_from_thread(
                self._log,
                f"[bold red]✖ Error:[/bold red] {exc}",
            )
        finally:
            logger.remove(sink_id)
            self.app.call_from_thread(self._set_buttons_disabled, False)

    def _do_clean(self) -> None:
        project = self.app.project  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        removed: list[str] = []
        if (build_dir := project.path / ".build").is_dir():
            shutil.rmtree(build_dir)
            removed.append(".build")
        if (gen_dir := project.path / "layouts" / "generated").is_dir():
            shutil.rmtree(gen_dir)
            removed.append("layouts/generated")
        if removed:
            self._log(f"[bold green]✔ Removed:[/bold green] {', '.join(removed)}")
        else:
            self._log("[dim]Nothing to clean.[/dim]")


# ── Project browser screen ─────────────────────────────────────────────────────
class NewProjectScreen(Screen[bool]):
    """Full-page form for creating a new SeReTo project.

    Dismisses with ``True`` when a project was created, ``False`` when cancelled.
    """

    SUB_TITLE = "New Project"

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="new-project-layout"):
            yield Label("Create a New Project", id="new-project-title")
            yield Rule()
            yield InputWithLabel(
                Input(placeholder="e.g. PT01234  (max 20 chars: a-z A-Z 0-9 . _ -)", id="new-project-id"),
                "Project ID",
            )
            yield InputWithLabel(
                Input(placeholder="e.g. Pentest", id="new-project-name"),
                "Name",
            )
            with Horizontal(id="new-project-buttons"):
                yield Button("Create", variant="success", id="new-project-create")
                yield Button("Cancel", variant="default", id="new-project-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#new-project-id", Input).focus()

    @on(Input.Submitted)
    def _on_submitted(self) -> None:
        self._do_create()

    @on(Button.Pressed, "#new-project-create")
    def _on_create(self) -> None:
        self._do_create()

    @on(Button.Pressed, "#new-project-cancel")
    def _on_cancel(self) -> None:
        self.dismiss(False)

    def _do_create(self) -> None:
        id_input = self.query_one("#new-project-id", Input)
        name_input = self.query_one("#new-project-name", Input)

        project_id = id_input.value.strip()
        project_name = name_input.value.strip()

        if not project_id:
            self.notify("Project ID is required.", severity="warning")
            id_input.focus()
            return

        if not project_name:
            self.notify("Project name is required.", severity="warning")
            name_input.focus()
            return

        ta: TypeAdapter[TypeProjectId] = TypeAdapter(TypeProjectId)
        try:
            ta.validate_python(project_id)
        except ValidationError:
            self.notify(
                "Project ID must be 1–20 characters: letters, digits, '.', '_', '-'.",
                severity="error",
            )
            id_input.focus()
            return

        app: SeretoUnifiedApp = self.app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        try:
            project = new_project(
                projects_path=app.settings.projects_path,
                templates_path=app.settings.templates_path,
                risk_due_dates=app.settings.risk_due_dates,
                id=project_id,
                name=project_name,
                people=app.settings.default_people,
            )
            app.current_project = project
        except SeretoPathError as exc:
            self.notify(str(exc), severity="error")
            return
        except Exception as exc:
            self.notify(f"Failed to create project: {exc}", severity="error")
            return

        self.notify(f"Project '{project_id}' created.", severity="information", timeout=4)
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


# ── TUI plugin interface and internal registry ─────────────────────────────────
class TuiPlugin:
    """Interface that every plugin which should be also part of the TUI must implement.

    Subclass this class, set the required class attributes, and register it
    from your plugin module's ``register_tui_actions`` function.  SeReTo calls
    that function during :func:`~sereto.cli.cli.load_plugins` (when plugins are
    enabled in global settings), exactly mirroring how ``register_commands`` is
    used for CLI commands.

    Required class attributes:
        label (str): Text shown on the action-bar button within home page.
        screen (Callable[[SeretoUnifiedApp], Screen]): Factory invoked with the
            running app when the button is pressed (or the entry point is
            reached), and returning the :class:`~textual.screen.Screen` to
            push. A bare zero-arg ``Screen`` subclass also works as long as it
            tolerates the extra call-site argument being ignored (use
            ``staticmethod(lambda app: MyScreen())`` in that case). Plugins
            that need private state should build it inside the factory and
            inject it via launch_tui's ``plugin_context`` parameter.

    Optional class attributes:
        id (str): Unique key used for ``launch_tui(entry_point=…)`` routing.
            Defaults to the lower-cased class name when not set.
        requires_project (bool): When ``True`` (the default) the action is
            blocked if no project is currently selected.
        show_in_bar (bool): When ``True`` (the default) a button is rendered in
            the action bar.  Set to ``False`` for entry-point-only tokens.
        precursor_id (str): Optional id of another registered plugin/screen which
            should be pushed onto the stack *before* this plugin's screen.  Use
            this when the current plugin's screen requires a parent screen below
            it (e.g. a sub-screen that needs its menu screen under it).

    Plugin module convention::

        # my_plugin/__init__.py
        def register_commands(cli):
            cli.add_command(my_command)        # CLI integration

        def register_tui_actions(register_plugin):
            from my_plugin.tui_plugins import CspPlugin
            register_plugin(CspPlugin)          # TUI integration

    Plugin :class:`TuiPlugin` subclass::

        from sereto.tui import TuiPlugin
        from my_plugin.screens import MyScreen

        class MyPlugin(TuiPlugin):
            label = "Just my plugin"
            screen = staticmethod(lambda app: MyScreen())
            # requires_project = True   # default
            # show_in_bar = True        # default
    """

    label: ClassVar[str]
    screen: ClassVar[Callable[[SeretoUnifiedApp], Screen[Any]] | Callable[[], Screen[Any]]]
    id: ClassVar[str | None] = None
    requires_project: ClassVar[bool] = True
    show_in_bar: ClassVar[bool] = True
    precursor_id: ClassVar[str | None] = None

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        missing = [a for a in ("label", "screen") if not hasattr(cls, a)]
        if missing:
            raise TypeError(
                f"{cls.__name__} must define the following class attribute(s): " + ", ".join(f"'{a}'" for a in missing)
            )


@dataclass(frozen=True)
class _TuiEntry:
    """Internal registry entry for ProjectBrowserScreen — not part of the public API."""

    id: str
    label: str
    requires_project: bool
    screen: Callable[[SeretoUnifiedApp], Screen[Any]]
    show_in_bar: bool = field(default=True)
    precursor_id: str | None = field(default=None)


# Module-level registry — populated from built-in TuiPlugin subclasses and
# discovered plugin TuiPlugin subclasses before launch_tui() starts the app.
_ACTION_REGISTRY: list[_TuiEntry] = []


def _register_entry(entry: _TuiEntry) -> None:
    """Add/replace an entry in :data:`_ACTION_REGISTRY` by id."""
    for i, existing in enumerate(_ACTION_REGISTRY):
        if existing.id == entry.id:
            _ACTION_REGISTRY[i] = entry
            return
    _ACTION_REGISTRY.append(entry)


def register_tui_plugin(plugin: type[TuiPlugin]) -> None:
    """Register a :class:`TuiPlugin` subclass in the action registry.

    Call this from your plugin module's ``register_tui_actions`` function::

        def register_tui_actions(register_plugin):
            register_plugin(CspPlugin)

    SeReTo passes this function as the ``register_plugin`` argument when
    loading plugins via :func:`~sereto.cli.cli.load_plugins`.

    Registering the same plugin id again replaces the existing entry
    instead of appending a duplicate.
    """
    entry_id = plugin.id or plugin.__name__.lower()
    _register_entry(
        _TuiEntry(
            entry_id,
            plugin.label,
            plugin.requires_project,
            plugin.screen,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            plugin.show_in_bar,
            plugin.precursor_id,
        )
    )


# ── Project browser screen ─────────────────────────────────────────────────────
def _precursor_chain(action: _TuiEntry, _seen: frozenset[str] = frozenset()) -> list[_TuiEntry]:
    """Return ordered precursor entries for *action*, outermost first."""
    if action.precursor_id is None or action.precursor_id in _seen:
        return []  # no precursor, or cycle guard
    precursor = next((a for a in _ACTION_REGISTRY if a.id == action.precursor_id), None)
    if precursor is None:
        return []
    return [*_precursor_chain(precursor, _seen | {action.id}), precursor]


class ProjectBrowserScreen(Screen[None]):
    """Dropdown project selector with a detail panel filling the remaining space."""

    SUB_TITLE = "Project Browser"

    BINDINGS = [
        Binding("a", "add_finding", "Add finding"),
        Binding("c", "config", "Config"),
        Binding("p", "render", "Render PDF"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="browser-layout"):
            with Horizontal(id="project-select-row"):
                yield Select[Path]([], id="project-select", prompt="Select a project…")
                yield Select[str](
                    [("v1.0", "v1.0")],  # Temporary placeholder, will be replaced when project loads
                    id="version-select",
                    allow_blank=False,
                )
                yield Button("Retest", id="retest-btn", variant="warning", tooltip="Add retest version")
                yield Button("+", id="new-project-btn", variant="success", tooltip="Create new project")
            yield Horizontal(id="action-bar")  # buttons injected at mount
            with ScrollableContainer(id="content-panel"):
                yield Vertical(id="content-container")
        yield Footer()

    def on_mount(self) -> None:
        # Initially hide version select if no project
        app: SeretoUnifiedApp = self.app  # type: ignore
        if not app.current_project:
            self.query_one("#version-select", Select).display = False
            self.query_one("#retest-btn", Button).display = False

        self._populate_action_bar()
        self._load_projects()

        self.query_one("#content-container", Vertical).mount(Static(self._welcome_text()))

        # If the app was launched with an entry point, try to activate right away
        if app.entry_point is not None:
            action = next((a for a in _ACTION_REGISTRY if a.id == app.entry_point), None)
            if action is not None:
                if action.requires_project and app.current_project is None:
                    self.notify("Select a project first.", severity="warning", timeout=3)
                else:
                    for precursor in _precursor_chain(action):
                        self.app.push_screen(precursor.screen(app))
                    self.app.push_screen(action.screen(app))

    def _populate_action_bar(self) -> None:
        """Inject one Button per registered action into the action bar."""
        bar = self.query_one("#action-bar", Horizontal)
        for action in _ACTION_REGISTRY:
            if action.show_in_bar:
                bar.mount(Button(action.label, id=f"action-{action.id}", variant="primary", classes="action-btn"))

    @on(Button.Pressed, ".action-btn")
    def _on_action_btn(self, event: Button.Pressed) -> None:
        entry_id = (event.button.id or "").removeprefix("action-")
        app: SeretoUnifiedApp = self.app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        for action in _ACTION_REGISTRY:
            if action.id == entry_id:
                if action.requires_project and app.current_project is None:
                    self.notify("Select a project first.", severity="warning", timeout=3)
                    return
                for precursor in _precursor_chain(action):
                    self.app.push_screen(precursor.screen(app))
                self.app.push_screen(action.screen(app))
                return

    @on(Button.Pressed, "#new-project-btn")
    def _on_new_project_btn(self) -> None:
        def _on_created(created: bool | None) -> None:
            if created:
                self._load_projects()
                project_select = self.query_one("#project-select", Select)
                project_select.value = self.app.project.path  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]

        self.app.push_screen(NewProjectScreen(), _on_created)

    @on(Button.Pressed, "#retest-btn")
    def _on_retest_btn(self) -> None:
        app: SeretoUnifiedApp = self.app  # type: ignore
        try:
            add_retest(project=app.project)
            # Reload the project to update version list
            project = Project.load_from(app.project.path)
            version_select = self.query_one("#version-select", Select)
            version_select.set_options([(str(v), str(v)) for v in project.config.versions])
            version_select.value = str(project.config.last_version)
            app.selected_project_version = str(project.config.last_version)
            self.notify("Retest version added successfully.", severity="information", timeout=3)
        except Exception as e:
            self.notify(f"Failed to add retest: {e}", severity="error", timeout=5)

    # ── Project loading ────────────────────────────────────────────────────────
    def _load_projects(self) -> None:
        app: SeretoUnifiedApp = self.app  # type: ignore
        select = self.query_one("#project-select", Select)
        container = self.query_one("#content-container", Vertical)

        try:
            project_dirs = sorted(d for d in app.settings.projects_path.iterdir() if is_project_dir(d))
        except (OSError, PermissionError):
            container.remove_children()
            container.mount(Static(Text("Cannot read projects directory.", style="red")))
            return

        if not project_dirs:
            container.remove_children()
            container.mount(Static(Text("No projects found.", style="dim")))
            return

        options: list[tuple[Text, Path]] = []
        for project_dir in project_dirs:
            try:
                project = Project.load_from(project_dir)
                last_vc = project.config.last_config
                label = Text.assemble((last_vc.id, "bold cyan"), f"  {last_vc.name}")
            except Exception:
                label = Text.assemble((project_dir.name, "bold cyan"), "  [unreadable]")
            options.append((label, project_dir))

        select.set_options(options)

        # Auto-select if cwd is inside a known project
        cwd = Path.cwd()
        if is_project_dir(cwd):
            for _, path in options:
                if path == cwd:
                    select.value = path
                    # Eagerly activate so entry_point logic in on_mount sees the project
                    self._do_activate_project(path)
                    break

    # ── Selection handler ──────────────────────────────────────────────────────
    @on(Select.Changed, "#version-select")
    def on_render_version_selected(self, event: Select.Changed) -> None:
        app: SeretoUnifiedApp = self.app  # type: ignore
        app.selected_project_version = str(event.value) if not isinstance(event.value, NoSelection) else None
        self.refresh_content()

    @on(Select.Changed, "#project-select")
    def on_project_selected(self, event: Select.Changed) -> None:
        container = self.query_one("#content-container", Vertical)
        version_select = self.query_one("#version-select", Select)
        retest_button = self.query_one("#retest-btn", Button)

        app: SeretoUnifiedApp = self.app  # type: ignore

        if isinstance(event.value, NoSelection):
            container.remove_children()
            container.mount(Static(self._welcome_text(), markup=True))
            app.current_project = None
            app.categories = []
            app.selected_project_version = None
            version_select.display = False
            retest_button.display = False
            return

        project_path = Path(str(event.value))  # Guaranteed non-NoSelection after isinstance check above
        try:
            self._do_activate_project(project_path)
            version_select.display = True
            retest_button.display = True
        except Exception:
            container.remove_children()
            container.mount(
                Static(
                    self._error_content(
                        title=f"Failed to load: {project_path.name}",
                        detail=traceback.format_exc(),
                    ),
                    markup=True,
                )
            )
            version_select.display = False
            retest_button.display = False
            app.selected_project_version = None

    def _do_activate_project(self, project_path: Path) -> None:
        """Set the app's current project; skips reload if already active."""
        app: SeretoUnifiedApp = self.app  # type: ignore
        version_select = self.query_one("#version-select", Select)
        try:
            project = Project.load_from(project_path)
            app.current_project = project
            app.categories = sorted(c.upper() for c in app.current_project.settings.categories)
            app.selected_project_version = str(project.config.last_version)
            version_select.set_options([(str(v), str(v)) for v in project.config.versions])
            version_select.value = str(project.config.last_version)
            self._populate_content_panel(project)
        except Exception:
            app.current_project = None
            app.selected_project_version = None
            app.categories = []
            raise

    # ── Content builders ───────────────────────────────────────────────────────
    @staticmethod
    def _welcome_text() -> str:
        return "[dim]Select a project from the dropdown above to view its details.[/dim]"

    def _populate_content_panel(self, project: Project) -> None:
        """Populate the content panel with widgets: stats boxes and target list."""
        app: SeretoUnifiedApp = self.app  # type: ignore
        version_str = app.selected_project_version
        if version_str is None:
            return
        vc = project.config.at_version(version_str)
        container = self.query_one("#content-container", Vertical)
        container.remove_children()

        # Calculate risk counts
        risk_counts: dict[Risk, int] = {risk: 0 for risk in Risk}
        for target in vc.targets:
            for group in target.findings.groups:
                risk_counts[group.risk] += 1

        # Stats box row
        stats_row = Horizontal(classes="browser-stats-row")
        container.mount(stats_row)

        for risk in [Risk.critical, Risk.high, Risk.medium, Risk.low, Risk.info]:
            count = risk_counts[risk]
            label = risk.value.capitalize()
            stat_text = Text.assemble(f"{count} ", (label, _RISK_STYLE[risk]))
            stat_box = Static(stat_text, classes=f"browser-stat-box browser-stat-{risk.value}")
            stats_row.mount(stat_box)

        # Targets list
        targets_list = Vertical(classes="browser-targets-list")
        container.mount(targets_list)

        if not vc.targets:
            targets_list.mount(Static("[dim]No targets. Add them via 'Config' button.[/dim]", markup=True))
        else:
            for target in vc.targets:
                # Target header: CATEGORY + name
                target_text = Text.assemble(
                    (target.data.category.upper(), "bold medium_purple"),
                    " ",
                    (target.data.name, "bold"),
                )
                target_item = Static(target_text, classes="browser-target-item")
                targets_list.mount(target_item)
                # Findings under this target
                if target.findings.groups:
                    for group in target.findings.groups:
                        count = len(group.sub_findings)
                        finding_text = Text.assemble(
                            ("  ▪ ", "dim"),
                            _risk_text(group.risk),
                            "  ",
                            group.suggested_name,
                            (f"  ({count} sub-finding{'s' if count != 1 else ''})", "dim"),
                        )
                        targets_list.mount(Static(finding_text, classes="browser-finding-item"))

    @staticmethod
    def _error_content(title: str, detail: str) -> Text:
        text = Text()
        text.append(title, style="bold red")
        text.append("\n")
        text.append("\n\n")
        text.append(detail, style="dim")
        return text

    def refresh_content(self) -> None:
        """Refresh the project detail panel for the currently active project."""
        app: SeretoUnifiedApp = self.app  # type: ignore
        if app.current_project is None:
            return
        self._populate_content_panel(app.current_project)

    def refresh_project_select(self) -> None:
        """Rebuild the project select options, preserving the current selection.

        Called after a project's ID or name has been changed in the ConfigScreen,
        so the dropdown label reflects the new values.
        """
        app: SeretoUnifiedApp = self.app  # type: ignore
        current_path = app.current_project.path if app.current_project is not None else None
        self._load_projects()
        if current_path is not None:
            self.query_one("#project-select", Select).value = current_path

    # ── Base actions ────────────────────────────────────────────────────────────────
    def action_add_finding(self) -> None:
        app: SeretoUnifiedApp = self.app  # type: ignore

        if app.current_project is None:
            self.notify("Select a project first.", severity="warning", timeout=3)
            return

        self.app.push_screen(FindingSearchScreen())

    def action_config(self) -> None:
        app: SeretoUnifiedApp = self.app  # type: ignore

        if app.current_project is None:
            self.notify("Select a project first.", severity="warning", timeout=3)
            return

        self.app.push_screen(ConfigScreen())

    def action_render(self) -> None:
        app: SeretoUnifiedApp = self.app  # type: ignore

        if app.current_project is None:
            self.notify("Select a project first.", severity="warning", timeout=3)
            return

        self.app.push_screen(RenderScreen())


# ── Unified app ────────────────────────────────────────────────────────────────
class SeretoUnifiedApp(App[None]):
    """The single continuous SeReTo TUI.

    Screens are pushed on top of each other; the base is always
    :class:`ProjectBrowserScreen`.
    """

    CSS_PATH = ["app.tcss", "finding.tcss"]
    TITLE = "SeReTo"
    SUB_TITLE = "Security Reporting Tool"

    # Override the default (hidden) Ctrl+Q binding so it appears in the footer.
    BINDINGS = [Binding("ctrl+q", "quit", "Quit", priority=True)]

    def __init__(
        self,
        entry_point: str | None = None,
        project: Project | None = None,
        plugin_context: object | None = None,
    ) -> None:
        super().__init__()
        self.settings = load_settings_function()
        self.entry_point = entry_point
        self.plugin_context = plugin_context
        self.current_project: Project | None = None
        self.selected_project_version: str | None = None
        self.categories: list[str] = []
        try:
            if project is not None and is_project_dir(project.path):
                self.current_project = project
                self.selected_project_version = str(project.config.last_version)
                self.categories = sorted(c.upper() for c in project.settings.categories)
        except Exception:
            self.current_project = None
            self.selected_project_version = None
            self.categories = []

    @property
    def project(self) -> Project:
        """Enforces current_project to be not None, consumed by :class:`~sereto.tui.finding.SearchWidget`
        and :class:`~sereto.tui.finding.AddSubFindingScreen`."""
        if self.current_project is None:
            raise SeretoValueError("no project selected")
        return self.current_project

    def on_mount(self) -> None:
        self.push_screen(ProjectBrowserScreen())

    def action_focus_search(self) -> None:
        """Called by :class:`~sereto.tui.finding.AddSubFindingScreen` after saving.

        Walks the screen stack to find :class:`FindingSearchScreen` and focuses
        its search input. Also refreshes the project browser detail panel.
        """
        for screen in reversed(self.screen_stack):
            if isinstance(screen, FindingSearchScreen):
                screen.action_focus_search()

        for screen in self.screen_stack:
            if isinstance(screen, ProjectBrowserScreen):
                screen.refresh_content()
                break


# ── Built-in TuiPlugin registrations ──────────────────────────────────────────
class _FindingsAddPlugin(TuiPlugin):
    label = "Add finding"
    screen: Callable[[SeretoUnifiedApp], Screen[Any]] = staticmethod(lambda app: FindingSearchScreen())  # type: ignore
    id = "findings_add"


class _ConfigPlugin(TuiPlugin):
    label = "Config"
    screen: Callable[[SeretoUnifiedApp], Screen[Any]] = staticmethod(lambda app: ConfigScreen())  # type: ignore
    id = "config"


class _RenderPlugin(TuiPlugin):
    label = "Render PDF"
    screen: Callable[[SeretoUnifiedApp], Screen[Any]] = staticmethod(lambda app: RenderScreen())  # type: ignore
    id = "render"


_BUILTIN_PLUGINS: list[type[TuiPlugin]] = [
    _FindingsAddPlugin,
    _ConfigPlugin,
    _RenderPlugin,
]


def _register_builtin_actions() -> None:
    """Register built-in actions into :data:`_ACTION_REGISTRY`.

    Plugin TUI actions are registered earlier, during
    :func:`~sereto.cli.cli.load_plugins`, by calling each plugin module's
    ``register_tui_actions(register_plugin)`` function. This function only
    handles the built-in actions that are always present.
    """
    for plugin in _BUILTIN_PLUGINS:
        register_tui_plugin(plugin)
    # Entry-point-only aliases (e.g. `sereto config targets add`); no button,
    # and ConfigScreen itself resolves which tab to open from app.entry_point.
    for entry_id in ConfigScreen.TABS:
        _register_entry(_TuiEntry(entry_id, "", True, lambda app: ConfigScreen(), False))

    for entry_id in ConfigScreen.TABS:
        _register_entry(_TuiEntry(entry_id, "", True, lambda app: ConfigScreen(), False))


# ── Entry point ────────────────────────────────────────────────────────────────
async def launch_tui(
    entry_point: str | None = None,
    project: Project | None = None,
    plugin_context: object | None = None,
) -> None:
    """Launch the unified SeReTo TUI.

    Args:
        entry_point: Optional initial screen to push after the project browser.
            ``"findings_add"`` pushes :class:`FindingSearchScreen`.
            ``"targets"`` pushes :class:`ConfigScreen` with the targets tab selected.
        project: Optional already-loaded project (e.g. from REPL context).
        plugin_context: Optional opaque object for the plugin whose entry point is
            being launched (e.g. CLI-supplied credentials/options).  Read back via
            ``app.plugin_context`` inside that plugin's own screen factory.
    """
    _register_builtin_actions()
    app = SeretoUnifiedApp(entry_point=entry_point, project=project, plugin_context=plugin_context)
    await app.run_async()
