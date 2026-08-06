"""Unified SeReTo TUI application.

This module provides the single continuous TUI that replaces/pushes screens on top
of each other.  The entry point is :func:`launch_tui`.

Screen stack (outermost → innermost):
  ProjectBrowserScreen  – always present
  ConfigScreen / RenderScreen / FindingSearchScreen
  FindingPreviewScreen  – modal pushed on top of FindingSearchScreen
  AddSubFindingScreen   – modal pushed on top of FindingSearchScreen
"""

from __future__ import annotations

import shutil
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from pydantic import TypeAdapter, ValidationError
from rich.console import Console, Group as RichGroup
from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen, Screen
from textual.types import NoSelection
from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Rule, Select, Static, TabbedContent, TabPane

from sereto.config import VersionConfig
from sereto.enums import Risk
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.date import Date, DateRange, DateType, SeretoDate
from sereto.models.person import Person, PersonType
from sereto.models.target import TargetDastModel, TargetMobileModel, TargetModel, TargetSastModel
from sereto.models.version import ProjectVersion
from sereto.project import Project, is_project_dir, new_project
from sereto.sereto_types import TypeProjectId
from sereto.settings import load_settings_function
from sereto.target import Target
from sereto.tui.finding import SearchWidget
from sereto.tui.widgets.input import InputWithLabel

# ── Base screen for poppable screens ─────────────────────────────────────────


class _PoppableScreen(Screen[None]):
    """Base for screens that exit via Escape with priority over child widgets."""

    BINDINGS = [Binding("escape", "pop_screen", "Back", priority=True)]

    def action_pop_screen(self) -> None:
        self.app.pop_screen()


# ── Delete Confirmation dialog ───────────────────────────────────────────────────────


class DeleteConfirmationScreen(ModalScreen[bool]):
    """Generic yes/no modal.  Dismisses with True on Confirm, False on Cancel."""

    BINDINGS = [Binding("escape", "dismiss_false", "Cancel")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self._message, id="confirm-message", markup=True)
            with Horizontal(id="confirm-buttons"):
                yield Button("Confirm", variant="error", id="confirm-yes")
                yield Button("Cancel", variant="default", id="confirm-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")

    def action_dismiss_false(self) -> None:
        self.dismiss(False)


# ── Risk label helpers ─────────────────────────────────────────────────────────

_RISK_STYLE: dict[Risk, str] = {
    Risk.critical: "bold red",
    Risk.high: "bold dark_orange",
    Risk.medium: "bold yellow",
    Risk.low: "bold green",
    Risk.info: "bold blue",
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
            self.notify("No targets found in this project.", severity="warning", timeout=3)
            self.app.pop_screen()
            return
        self.query_one(SearchWidget).input_field.focus()

    def action_focus_search(self) -> None:
        """Re-focus the search input after a sub-finding has been saved."""
        self.query_one(SearchWidget).input_field.focus()


# ── Config row widgets ─────────────────────────────────────────────────────────


class _DateRow(Horizontal):
    """Single row in the dates list: formatted date text + Remove button."""

    def __init__(self, date: Date, index: int) -> None:
        super().__init__(classes="config-row")
        self._date = date
        self._index = index  # 1-based

    def compose(self) -> ComposeResult:
        match self._date.date:
            case DateRange():
                text = (
                    f"[b]{self._date.type.value.replace('_', ' ').title()}[/b]"
                    f"  {self._date.date.start} \u2013 {self._date.date.end}"
                )
            case _:
                text = f"[b]{self._date.type.value.replace('_', ' ').title()}[/b]  {self._date.date}"
        yield Static(text, classes="config-row-label", markup=True)
        yield Button("\u2715", variant="error", id=f"remove-date-{self._index}", classes="config-remove-btn")


class _TargetRow(Horizontal):
    """Single row in the targets list: formatted target text + Remove button."""

    def __init__(self, target: Target, index: int) -> None:
        super().__init__(classes="config-row")
        self._target = target
        self._index = index  # 1-based

    def compose(self) -> ComposeResult:
        text = f"[b]{self._target.data.category.upper()}[/b]  {self._target.data.name}"
        yield Static(text, classes="config-row-label", markup=True)
        yield Button("✕", variant="error", id=f"remove-target-{self._index}", classes="config-remove-btn")


class _PersonRow(Horizontal):
    """Single row in the people list: formatted person text + Remove button."""

    def __init__(self, person: Person, index: int) -> None:
        super().__init__(classes="config-row")
        self._person = person
        self._index = index  # 1-based

    def compose(self) -> ComposeResult:
        parts: list[str] = [f"[b]{self._person.type.value.replace('_', ' ').title()}[/b]"]
        if self._person.name:
            parts.append(self._person.name)
        if self._person.business_unit:
            parts.append(self._person.business_unit)
        if self._person.email:
            parts.append(self._person.email)
        if self._person.role:
            parts.append(self._person.role)
        yield Static("  \u00b7  ".join(parts), classes="config-row-label", markup=True)
        yield Button("\u2715", variant="error", id=f"remove-person-{self._index}", classes="config-remove-btn")


# ── Config screen ──────────────────────────────────────────────────────────────


class ConfigScreen(_PoppableScreen):
    """Screen for managing the project configuration (general info, dates, people)."""

    SUB_TITLE = "Project Configuration"

    def __init__(self, initial_tab: str | None = None) -> None:
        super().__init__()
        self._initial_tab = initial_tab

    @property
    def _active_vc(self) -> VersionConfig:
        return self.app.project.config.at_version(self._active_version)  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="version-bar"):
            yield Label("Version", id="version-bar-label")
            yield Select[str](
                [(str(v), str(v)) for v in self.app.project.config.versions],  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
                id="version-select",
                allow_blank=False,
                value=str(self.app.project.config.last_version),  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
            )
        with TabbedContent(id="config-tabs"):
            with TabPane("General", id="tab-general"), ScrollableContainer(id="general-form"):
                yield InputWithLabel(Input(id="cfg-id", placeholder="e.g. PRJ-001"), "ID")
                yield InputWithLabel(Input(id="cfg-name", placeholder="Project name\u2026"), "Name")
                yield InputWithLabel(Input(id="cfg-version-desc", placeholder="e.g. Initial"), "Description")
                with Horizontal(id="general-buttons"):
                    yield Button("Save", variant="success", id="save-general")
                    yield Button("Cancel", variant="default", id="cancel-cfg")
            with TabPane("Targets", id="tab-targets"), ScrollableContainer(id="targets-form"):
                yield Vertical(id="targets-list")
                yield Rule()
                with Horizontal(classes="field-row"):
                    yield Label("Category", classes="field-label")
                    yield Select(
                        options=[],
                        id="target-category-select",
                        prompt="Select category…",
                    )
                yield InputWithLabel(Input(id="target-name", placeholder="Target name…"), "Name")
                with Horizontal(classes="config-add-row"):
                    yield Button("Add target", variant="success", id="add-target-btn")
            with TabPane("Dates", id="tab-dates"), ScrollableContainer(id="dates-form"):
                yield Vertical(id="dates-list")
                yield Rule()
                with Horizontal(classes="field-row"):
                    yield Label("Type", classes="field-label")
                    yield Select(
                        options=[(dt.value.replace("_", " ").title(), dt) for dt in DateType],
                        id="date-type-select",
                        prompt="Select type\u2026",
                    )
                yield InputWithLabel(Input(id="date-start", placeholder="DD-Mmm-YYYY"), "Start")
                yield InputWithLabel(Input(id="date-end", placeholder="DD-Mmm-YYYY (optional)"), "End")
                with Horizontal(classes="config-add-row"):
                    yield Button("Add date", variant="success", id="add-date-btn")
            with TabPane("People", id="tab-people"), ScrollableContainer(id="people-form"):
                yield Vertical(id="people-list")
                yield Rule()
                with Horizontal(classes="field-row"):
                    yield Label("Type", classes="field-label")
                    yield Select(
                        options=[(pt.value.replace("_", " ").title(), pt) for pt in PersonType],
                        id="person-type-select",
                        prompt="Select type\u2026",
                    )
                yield InputWithLabel(Input(id="person-name", placeholder="Full name"), "Name")
                yield InputWithLabel(Input(id="person-bu", placeholder="Business unit"), "BU")
                yield InputWithLabel(Input(id="person-email", placeholder="user@example.com"), "Email")
                yield InputWithLabel(Input(id="person-role", placeholder="Role"), "Role")
                with Horizontal(classes="config-add-row"):
                    yield Button("Add person", variant="success", id="add-person-btn")
        yield Footer()

    def on_mount(self) -> None:
        self._active_version: ProjectVersion = self.app.project.config.last_version  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        # populate category selector
        app: SeretoUnifiedApp = self.app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        cat_options: list[tuple[str, str]] = [(c, c.lower()) for c in app.categories]
        self.query_one("#target-category-select", Select).set_options(cat_options)

        # Disable the sliding animation on the tab underline bar
        from textual.widgets import Tabs

        _tabs = self.query_one("#config-tabs").query_one(Tabs)
        _orig_highlight = _tabs.__class__._highlight_active
        _tabs._highlight_active = lambda animate=True: _orig_highlight(_tabs, animate=False)  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
        if self._initial_tab is not None:
            self.query_one("#config-tabs", TabbedContent).active = self._initial_tab
        self._reload_all_tabs()

    @on(Select.Changed, "#version-select")
    def on_version_changed(self, event: Select.Changed) -> None:
        if isinstance(event.value, NoSelection):
            return
        self._active_version = ProjectVersion.from_str(event.value)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        self._reload_all_tabs()

    def _reload_all_tabs(self) -> None:
        vc = self._active_vc
        self.query_one("#cfg-id", Input).value = vc.id
        self.query_one("#cfg-name", Input).value = vc.name
        self.query_one("#cfg-version-desc", Input).value = vc.version_description
        self._refresh_targets()
        self._refresh_dates()
        self._refresh_people()

    # ── List refresh ───────────────────────────────────────────────────────────

    def _refresh_targets(self) -> None:
        container = self.query_one("#targets-list", Vertical)
        container.remove_children()
        for i, t in enumerate(self._active_vc.targets, start=1):
            container.mount(_TargetRow(t, i))

    def _refresh_dates(self) -> None:
        container = self.query_one("#dates-list", Vertical)
        container.remove_children()
        for i, d in enumerate(self._active_vc.dates, start=1):
            container.mount(_DateRow(d, i))

    def _refresh_people(self) -> None:
        container = self.query_one("#people-list", Vertical)
        container.remove_children()
        for i, p in enumerate(self._active_vc.people, start=1):
            container.mount(_PersonRow(p, i))

    # ── Button handlers ────────────────────────────────────────────────────────

    @on(Button.Pressed, "#save-general")
    def handle_save_general(self) -> None:
        self._do_save_general()

    @on(Button.Pressed, "#cancel-cfg")
    def handle_cancel(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#add-target-btn")
    def handle_add_target(self) -> None:
        self._do_add_target()

    @on(Button.Pressed, "#add-date-btn")
    def handle_add_date(self) -> None:
        self._do_add_date()

    @on(Button.Pressed, "#add-person-btn")
    def handle_add_person(self) -> None:
        self._do_add_person()

    @on(Button.Pressed, ".config-remove-btn")
    def handle_remove(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("remove-target-"):
            index = int(button_id.removeprefix("remove-target-"))
            target = self._active_vc.targets[index - 1]
            name = target.data.name
            self.app.push_screen(
                DeleteConfirmationScreen(f"Remove target [b]{name}[/b]?"),
                callback=lambda confirmed, i=index: self._do_remove_target(i) if confirmed else None,
            )
        elif button_id.startswith("remove-date-"):
            index = int(button_id.removeprefix("remove-date-"))
            self.app.push_screen(
                DeleteConfirmationScreen("Remove this date?"),
                callback=lambda confirmed, i=index: self._do_remove_date(i) if confirmed else None,
            )
        elif button_id.startswith("remove-person-"):
            index = int(button_id.removeprefix("remove-person-"))
            self.app.push_screen(
                DeleteConfirmationScreen("Remove this person?"),
                callback=lambda confirmed, i=index: self._do_remove_person(i) if confirmed else None,
            )

    # ── Targets tab actions ────────────────────────────────────────────────────

    def _do_add_target(self) -> None:
        cat_select = self.query_one("#target-category-select", Select)
        name_input = self.query_one("#target-name", Input)

        if isinstance(cat_select.value, NoSelection):
            self.notify("Please select a category.", severity="warning", timeout=3)
            return

        category: str = cat_select.value
        name = name_input.value.strip()

        if not name:
            self.notify("Please enter a target name.", severity="warning", timeout=3)
            return

        model_class: type[TargetModel]
        match category:
            case "dast":
                model_class = TargetDastModel
            case "sast":
                model_class = TargetSastModel
            case "mobile":
                model_class = TargetMobileModel
            case _:
                model_class = TargetModel

        try:
            target_model = model_class.model_validate({"category": category, "name": name})
        except ValidationError as exc:
            self.notify(str(exc), title="Validation error", severity="error", markup=False)
            return

        project = self.app.project  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        version = self._active_version

        try:
            new_target = Target.new(
                data=target_model,
                project_path=project.path,
                templates=project.settings.templates_path,
                version=version,
            )
            project.config.at_version(version).add_target(new_target)
            project.config.save()
        except Exception as exc:
            self.notify(str(exc), title="Failed to create target", severity="error", markup=False)
            return

        name_input.value = ""
        self._refresh_targets()

        self.notify(name, title="Target added", timeout=3)

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
        except Exception as exc:
            self.notify(str(exc), title="Failed to remove target", severity="error", markup=False)

    # ── General tab actions ────────────────────────────────────────────────────

    def _do_save_general(self) -> None:
        vc = self._active_vc
        id_val = self.query_one("#cfg-id", Input).value.strip()
        name_val = self.query_one("#cfg-name", Input).value.strip()
        desc_val = self.query_one("#cfg-version-desc", Input).value.strip()

        if not id_val:
            self.notify("Project ID is required.", severity="warning", timeout=3)
            return
        if not name_val:
            self.notify("Project name is required.", severity="warning", timeout=3)
            return

        vc.id = id_val
        vc.name = name_val
        vc.version_description = desc_val

        try:
            self.app.project.config.save()  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
            self.notify("General settings saved.", timeout=3)
        except Exception as exc:
            self.notify(str(exc), title="Save failed", severity="error", markup=False)

    # ── Dates tab actions ──────────────────────────────────────────────────────

    def _do_add_date(self) -> None:
        type_select = self.query_one("#date-type-select", Select)
        start_input = self.query_one("#date-start", Input)
        end_input = self.query_one("#date-end", Input)

        if isinstance(type_select.value, NoSelection):
            self.notify("Please select a date type.", severity="warning", timeout=3)
            return

        date_type: DateType = type_select.value
        start_str = start_input.value.strip()

        if not start_str:
            self.notify("Start date is required.", severity="warning", timeout=3)
            return

        try:
            start = SeretoDate(start_str)
        except ValueError:
            self.notify(f"Invalid start date: {start_str!r}. Use DD-Mmm-YYYY.", severity="error", markup=False)
            return

        end_str = end_input.value.strip()
        date_value: SeretoDate | DateRange

        if end_str:
            try:
                end = SeretoDate(end_str)
            except ValueError:
                self.notify(f"Invalid end date: {end_str!r}. Use DD-Mmm-YYYY.", severity="error", markup=False)
                return
            try:
                date_value = DateRange(start=start, end=end)
            except Exception as exc:
                self.notify(str(exc), title="Invalid date range", severity="error", markup=False)
                return
        else:
            date_value = start

        try:
            new_date = Date(type=date_type, date=date_value)
            self._active_vc.add_date(new_date)
            self.app.project.config.save()  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        except Exception as exc:
            self.notify(str(exc), title="Failed to add date", severity="error", markup=False)
            return

        start_input.value = ""
        end_input.value = ""
        self._refresh_dates()
        self.notify("Date added.", timeout=3)

    def _do_remove_date(self, index: int) -> None:
        try:
            self._active_vc.delete_date(index)
            self.app.project.config.save()  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
            self._refresh_dates()
            self.notify("Date removed.", timeout=3)
        except Exception as exc:
            self.notify(str(exc), title="Failed to remove date", severity="error", markup=False)

    # ── People tab actions ─────────────────────────────────────────────────────

    def _do_add_person(self) -> None:
        type_select = self.query_one("#person-type-select", Select)
        name_val = self.query_one("#person-name", Input).value.strip()
        bu_val = self.query_one("#person-bu", Input).value.strip()
        email_val = self.query_one("#person-email", Input).value.strip()
        role_val = self.query_one("#person-role", Input).value.strip()

        if isinstance(type_select.value, NoSelection):
            self.notify("Please select a person type.", severity="warning", timeout=3)
            return

        person_type: PersonType = type_select.value

        try:
            new_person = Person(
                type=person_type,
                name=name_val or None,
                business_unit=bu_val or None,
                email=email_val or None,
                role=role_val or None,
            )
            self._active_vc.add_person(new_person)
            self.app.project.config.save()  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        except Exception as exc:
            self.notify(str(exc), title="Failed to add person", severity="error", markup=False)
            return

        self.query_one("#person-name", Input).value = ""
        self.query_one("#person-bu", Input).value = ""
        self.query_one("#person-email", Input).value = ""
        self.query_one("#person-role", Input).value = ""
        self._refresh_people()
        self.notify("Person added.", timeout=3)

    def _do_remove_person(self, index: int) -> None:
        try:
            self._active_vc.delete_person(index)
            self.app.project.config.save()  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
            self._refresh_people()
            self.notify("Person removed.", timeout=3)
        except Exception as exc:
            self.notify(str(exc), title="Failed to remove person", severity="error", markup=False)


# ── Render screen ─────────────────────────────────────────────────────────────


class RenderScreen(_PoppableScreen):
    """Screen for generating PDFs (report, SoW, targets, finding groups)."""

    SUB_TITLE = "Render PDF"

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="render-layout"):
            with Horizontal(id="render-controls"):
                with Horizontal(classes="render-field"):
                    yield Label("Version", classes="render-label")
                    yield Select[str](
                        [(str(v), str(v)) for v in self.app.project.config.versions],  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
                        id="render-version-select",
                        allow_blank=False,
                        value=str(self.app.project.config.last_version),  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
                    )
                with Vertical(id="render-buttons"):
                    yield Button("Report", variant="primary", id="render-report-btn")
                    yield Button("SoW", variant="primary", id="render-sow-btn")
                    with Horizontal(classes="render-field"):
                        yield Label("Target", classes="render-label")
                        yield Select[str]([], id="fg-target-select", allow_blank=True, prompt="All targets")
                    with Horizontal(classes="render-field"):
                        yield Label("Group", classes="render-label")
                        yield Select[str]([], id="fg-group-select", allow_blank=True, prompt="All groups")
                    yield Button("Render finding group(s)", variant="primary", id="render-fg-btn")
                    yield Button("Render all finding groups", variant="primary", id="render-all-fg-btn")
                    yield Button("Clean build", variant="warning", id="render-clean-btn")
            yield RichLog(id="render-log", highlight=True, markup=True, wrap=True)
            yield Button("Open PDF", variant="success", id="open-pdf-btn", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self._last_pdf: Path | None = None
        self.query_one("#render-log", RichLog).write("[dim]Select a render action above.[/dim]")
        self._reload_fg_selectors()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _log(self, text: str) -> None:
        self.query_one("#render-log", RichLog).write(text)

    def _selected_version(self) -> ProjectVersion:
        sel = self.query_one("#render-version-select", Select)
        return ProjectVersion.from_str(sel.value)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    def _set_last_pdf(self, path: Path) -> None:
        self._last_pdf = path
        btn = self.query_one("#open-pdf-btn", Button)
        btn.disabled = False
        btn.label = f"Open  {path.name}"

    def _set_buttons_disabled(self, disabled: bool) -> None:
        for btn_id in (
            "#render-report-btn",
            "#render-sow-btn",
            "#render-fg-btn",
            "#render-all-fg-btn",
            "#render-clean-btn",
        ):
            self.query_one(btn_id, Button).disabled = disabled

    def _reload_fg_selectors(self) -> None:
        version = self._selected_version()
        targets = self.app.project.config.at_version(version).targets  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        target_options = [(f"{t.data.category.upper()}  {t.data.name}", t.data.uname) for t in targets]
        target_select = self.query_one("#fg-target-select", Select)
        fg_select = self.query_one("#fg-group-select", Select)
        target_select.set_options(target_options)
        target_select.clear()
        fg_select.set_options([])
        fg_select.disabled = True

    @on(Select.Changed, "#render-version-select")
    def on_render_version_changed(self, event: Select.Changed) -> None:
        if not isinstance(event.value, NoSelection):
            self._reload_fg_selectors()

    @on(Select.Changed, "#fg-target-select")
    def on_fg_target_changed(self, event: Select.Changed) -> None:
        fg_select = self.query_one("#fg-group-select", Select)
        if isinstance(event.value, NoSelection):
            fg_select.set_options([])
            fg_select.clear()
            fg_select.disabled = True
            return
        version = self._selected_version()
        targets = self.app.project.config.at_version(version).targets  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        target_uname = str(event.value)
        target = next((t for t in targets if t.data.uname == target_uname), None)
        if target is None:
            fg_select.set_options([])
            fg_select.clear()
            fg_select.disabled = True
            return
        fg_options = [(g.name, g.uname) for g in target.findings.groups]
        fg_select.set_options(fg_options)
        fg_select.clear()
        fg_select.disabled = len(fg_options) == 0

    # ── button handlers ───────────────────────────────────────────────────────

    @on(Button.Pressed, "#render-report-btn")
    def handle_render_report(self) -> None:
        self._run_render("report")

    @on(Button.Pressed, "#render-sow-btn")
    def handle_render_sow(self) -> None:
        self._run_render("sow")

    @on(Button.Pressed, "#render-fg-btn")
    def handle_render_fg(self) -> None:
        self._run_render("fg")

    @on(Button.Pressed, "#render-all-fg-btn")
    def handle_render_all_fg(self) -> None:
        self._run_render("all_fg")

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
        version = self._selected_version()

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
                Input(placeholder="e.g. Pentest of Acme Corp", id="new-project-name"),
                "Name",
            )
            with Horizontal(id="new-project-buttons"):
                yield Button("Create", variant="success", id="new-project-create")
                yield Button("Cancel", variant="default", id="new-project-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#new-project-id", Input).focus()

    @on(Input.Submitted)
    def _on_submitted(self, event: Input.Submitted) -> None:
        self._do_create()

    @on(Button.Pressed, "#new-project-create")
    def _on_create(self, event: Button.Pressed) -> None:
        self._do_create()

    @on(Button.Pressed, "#new-project-cancel")
    def _on_cancel(self, event: Button.Pressed) -> None:
        self.dismiss(False)

    def _do_create(self) -> None:
        id_input = self.query_one("#new-project-id", Input)
        name_input = self.query_one("#new-project-name", Input)

        project_id = id_input.value.strip()
        project_name = name_input.value.strip()

        if not project_id:
            self.notify("Project ID is required.", severity="error")
            id_input.focus()
            return

        if not project_name:
            self.notify("Project name is required.", severity="error")
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
            new_project(
                projects_path=app.settings.projects_path,
                templates_path=app.settings.templates_path,
                risk_due_dates=app.settings.risk_due_dates,
                id=project_id,
                name=project_name,
                people=app.settings.default_people,
            )
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


# ── TUI plugin interface & internal registry ─────────────────────────────────


class TuiPlugin:
    """Interface that every plugin which should be also part of the TUI must implement.

    Subclass this class, set the required class attributes, and register it
    from your plugin module's ``register_tui_actions`` function.  SeReTo calls
    that function during :func:`~sereto.cli.cli.load_plugins` (when plugins are
    enabled in global settings), exactly mirroring how ``register_commands`` is
    used for CLI commands.

    Required class attributes:
        label (str): Text shown on the action-bar button.
        screen (type[Screen]): The :class:`~textual.screen.Screen` subclass to
            push when the button is pressed.  Instantiated with no arguments.

    Optional class attributes:
        id (str): Unique key used for ``launch_tui(entry_point=…)`` routing.
            Defaults to the lower-cased class name when not set.
        requires_project (bool): When ``True`` (the default) the action is
            blocked if no project is currently selected.
        show_in_bar (bool): When ``True`` (the default) a button is rendered in
            the action bar.  Set to ``False`` for entry-point-only tokens.

    Plugin module convention::

        # my_plugin/__init__.py
        def register_commands(cli):
            cli.add_command(my_command)        # CLI integration

        def register_tui_actions(register_plugin):
            from my_plugin.tui_plugins import CspPlugin
            register_plugin(CspPlugin)          # TUI integration

    Plugin :class:`TuiPlugin` subclass::

        from sereto.tui import TuiPlugin
        from my_plugin.screens import CspScreen

        class CspPlugin(TuiPlugin):
            label = "CSP Scan"
            screen = CspScreen
            # requires_project = True   # default
            # show_in_bar = True        # default
    """

    label: ClassVar[str]
    screen: ClassVar[type[Screen[Any]]]
    id: ClassVar[str | None] = None
    requires_project: ClassVar[bool] = True
    show_in_bar: ClassVar[bool] = True

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        missing = [a for a in ("label", "screen") if not hasattr(cls, a)]
        if missing:
            raise TypeError(
                f"{cls.__name__} must define the following class attribute(s): " + ", ".join(f"'{a}'" for a in missing)
            )


@dataclass(frozen=True)
class _TuiEntry:
    """Internal registry entry — not part of the public API."""

    id: str
    label: str
    requires_project: bool
    screen: type[Screen[Any]]
    show_in_bar: bool = field(default=True)


# Module-level registry — populated from built-in TuiPlugin subclasses and
# discovered plugin TuiPlugin subclasses before launch_tui() starts the app.
_ACTION_REGISTRY: list[_TuiEntry] = []


def register_tui_plugin(plugin: type[TuiPlugin]) -> None:
    """Register a :class:`TuiPlugin` subclass in the action registry.

    Call this from your plugin module's ``register_tui_actions`` function::

        def register_tui_actions(register_plugin):
            register_plugin(CspPlugin)

    SeReTo passes this function as the ``register_plugin`` argument when
    loading plugins via :func:`~sereto.cli.cli.load_plugins`.

    Registering the same plugin id again (e.g. because ``launch_tui()`` is
    called multiple times within the same process, as happens in the REPL)
    replaces the existing entry instead of appending a duplicate.
    """
    entry_id = plugin.id or plugin.__name__.lower()
    entry = _TuiEntry(entry_id, plugin.label, plugin.requires_project, plugin.screen, plugin.show_in_bar)
    for i, existing in enumerate(_ACTION_REGISTRY):
        if existing.id == entry_id:
            _ACTION_REGISTRY[i] = entry
            return
    _ACTION_REGISTRY.append(entry)


# ── Project browser screen ─────────────────────────────────────────────────────


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
                yield Button("+", id="new-project-btn", variant="success", tooltip="Create new project")
            yield Horizontal(id="action-bar")  # buttons injected at mount
            with ScrollableContainer(id="content-panel"):
                yield Static(self._welcome_text(), id="content-static", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self._populate_action_bar()
        self._load_projects()
        app: SeretoUnifiedApp = self.app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        if app.entry_point is not None:
            action = next((a for a in _ACTION_REGISTRY if a.id == app.entry_point), None)
            if action is not None:
                if action.requires_project and app.current_project is None:
                    self.notify("Select a project first.", severity="warning", timeout=3)
                else:
                    self.app.push_screen(action.screen())

    def _populate_action_bar(self) -> None:
        """Inject one Button per registered action into the action bar."""
        bar = self.query_one("#action-bar", Horizontal)
        for action in _ACTION_REGISTRY:
            if action.show_in_bar:
                bar.mount(Button(action.label, id=f"action-{action.id}", classes="action-btn"))

    @on(Button.Pressed, ".action-btn")
    def _on_action_btn(self, event: Button.Pressed) -> None:
        entry_id = (event.button.id or "").removeprefix("action-")
        app: SeretoUnifiedApp = self.app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        for action in _ACTION_REGISTRY:
            if action.id == entry_id:
                if action.requires_project and app.current_project is None:
                    self.notify("Select a project first.", severity="warning", timeout=3)
                    return
                self.app.push_screen(action.screen())
                return

    @on(Button.Pressed, "#new-project-btn")
    def _on_new_project_btn(self, event: Button.Pressed) -> None:
        def _on_created(created: bool | None) -> None:
            if created:
                self._load_projects()

        self.app.push_screen(NewProjectScreen(), _on_created)

    # ── Project loading ────────────────────────────────────────────────────────

    def _load_projects(self) -> None:
        app: SeretoUnifiedApp = self.app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        select = self.query_one("#project-select", Select)
        content = self.query_one("#content-static", Static)

        try:
            project_dirs = sorted(d for d in app.settings.projects_path.iterdir() if is_project_dir(d))
        except (OSError, PermissionError):
            content.update(Text("Cannot read projects directory.", style="red"))
            return

        if not project_dirs:
            content.update(Text("No projects found.", style="dim"))
            return

        options: list[tuple[str, Path]] = []
        for project_dir in project_dirs:
            try:
                project = Project.load_from(project_dir)
                last_vc = project.config.last_config
                label = f"{last_vc.id}  {last_vc.name}"
            except Exception:
                label = f"{project_dir.name}  [unreadable]"
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

    @on(Select.Changed, "#project-select")
    def on_project_selected(self, event: Select.Changed) -> None:
        content = self.query_one("#content-static", Static)

        if isinstance(event.value, NoSelection):
            content.update(self._welcome_text())
            app: SeretoUnifiedApp = self.app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
            app.current_project = None
            app.categories = []
            return

        project_path: Path = event.value  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        try:
            project = Project.load_from(project_path)
            self._do_activate_project(project_path, project)
            content.update(self._project_detail(project))
        except Exception:
            content.update(
                self._error_content(
                    title=f"Failed to load: {project_path.name}",
                    detail=traceback.format_exc(),
                )
            )

    def _do_activate_project(self, project_path: Path, project: Project | None = None) -> None:
        """Set the app's current project; skips reload if already active."""
        app: SeretoUnifiedApp = self.app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        try:
            if app.current_project is None or app.current_project.path != project_path:
                app.current_project = project or Project.load_from(project_path)
                app.categories = sorted(c.upper() for c in app.current_project.settings.categories)
        except Exception:
            pass

    # ── Content builders ───────────────────────────────────────────────────────

    @staticmethod
    def _welcome_text() -> str:
        return "[dim]Select a project from the dropdown above to view its details.[/dim]"

    @staticmethod
    def _project_detail(project: Project) -> RichGroup:
        sections: list[Text | Table] = []
        for version in project.config.versions:
            vc = project.config.at_version(version)

            # ── Header ────────────────────────────────────────────────────────
            header = Text.assemble(
                (vc.id, "bold cyan"),
                "  ",
                (vc.name, "bold"),
                *([(f"  ({vc.version_description})", "dim italic")] if vc.version_description else []),
            )

            # ── Metadata ──────────────────────────────────────────────────────
            meta = Table(show_header=False, box=None, padding=(0, 0), show_edge=False)
            meta.add_column(style="dim", min_width=10)
            meta.add_column()
            meta.add_row("Version", str(version))
            meta.add_row("Path", str(project.path))

            # ── Targets ───────────────────────────────────────────────────────
            target_lines: list[Text] = [Text("  [no targets]", style="dim italic")] if not vc.targets else []
            for target in vc.targets:
                target_lines.append(
                    Text.assemble(
                        "  ",
                        (target.data.category.upper(), "bold cyan"),
                        "  ",
                        (target.data.name, "bold"),
                        ("  target", "dim italic"),
                    )
                )
                for group in target.findings.groups:
                    count = len(group.sub_findings)
                    target_lines.append(
                        Text.assemble(
                            ("    ● ", "dim"),
                            _risk_text(group.risk),
                            "  ",
                            group.suggested_name,
                            (f"  ({count} sub-finding{'s' if count != 1 else ''})", "dim"),
                        )
                    )

            sections.extend(
                [
                    header,
                    Text("─" * 42, style="dim"),
                    meta,
                    Text(""),
                    *target_lines,
                    Text(""),
                ]
            )

        return RichGroup(*sections)

    @staticmethod
    def _error_content(title: str, detail: str) -> Text:
        text = Text()
        text.append(title, style="bold red")
        text.append("\n")
        text.append("─" * 42, style="dim")
        text.append("\n\n")
        text.append(detail, style="dim")
        return text

    def refresh_content(self) -> None:
        """Refresh the project detail panel for the currently active project."""
        app: SeretoUnifiedApp = self.app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        if app.current_project is None:
            return
        self.query_one("#content-static", Static).update(self._project_detail(app.current_project))

    # ── Actions ────────────────────────────────────────────────────────────────

    def action_add_finding(self) -> None:
        app: SeretoUnifiedApp = self.app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

        if app.current_project is None:
            self.notify("Select a project first.", severity="warning", timeout=3)
            return

        self.app.push_screen(FindingSearchScreen())

    def action_config(self) -> None:
        app: SeretoUnifiedApp = self.app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

        if app.current_project is None:
            self.notify("Select a project first.", severity="warning", timeout=3)
            return

        self.app.push_screen(ConfigScreen())

    def action_render(self) -> None:
        app: SeretoUnifiedApp = self.app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

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

    def __init__(self, entry_point: str | None = None, project: Project | None = None) -> None:
        super().__init__()
        self.settings = load_settings_function()
        self.entry_point = entry_point
        try:
            if project is not None and is_project_dir(project.path):
                self.current_project: Project | None = project
                self.categories: list[str] = sorted(c.upper() for c in project.settings.categories)
            else:
                self.current_project = None
                self.categories = []
        except Exception:
            self.current_project = None
            self.categories = []

    @property
    def project(self) -> Project:
        """Duck-type shim consumed by :class:`~sereto.tui.finding.SearchWidget`
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
            elif isinstance(screen, ProjectBrowserScreen):
                screen.refresh_content()


# ── Built-in TuiPlugin registrations ──────────────────────────────────────────
# Defined after all screen classes so the class-body references resolve.


class _FindingsAddPlugin(TuiPlugin):
    label = "Add finding"
    screen = FindingSearchScreen
    id = "findings_add"


class _ConfigPlugin(TuiPlugin):
    label = "Config"
    screen = ConfigScreen
    id = "config"


class _RenderPlugin(TuiPlugin):
    label = "Render PDF"
    screen = RenderScreen
    id = "render"


# Entry-point-only tokens: no button, but reachable via launch_tui(entry_point=…).
# These need a custom factory (ConfigScreen with an initial_tab argument) so we
# override the screen indirection with a thin wrapper class.

_BUILTIN_PLUGINS: list[type[TuiPlugin]] = [
    _FindingsAddPlugin,
    _ConfigPlugin,
    _RenderPlugin,
]


def _register_builtin_actions() -> None:
    """Register built-in actions into :data:`_ACTION_REGISTRY`.

    Plugin TUI actions are registered earlier, during
    :func:`~sereto.cli.cli.load_plugins`, by calling each plugin module's
    ``register_tui_actions(register_plugin)`` function.  This function only
    handles the built-in actions that are always present.
    """
    for plugin in _BUILTIN_PLUGINS:
        register_tui_plugin(plugin)


# ── Entry point ────────────────────────────────────────────────────────────────


async def launch_tui(entry_point: str | None = None, project: Project | None = None) -> None:
    """Launch the unified SeReTo TUI.

    Args:
        entry_point: Optional initial screen to push after the project browser.
            ``"findings_add"`` pushes :class:`FindingSearchScreen`.
            ``"targets"`` pushes :class:`ConfigScreen` with the targets tab selected.
        project: Optional already-loaded project (e.g. from REPL context).
    """
    _register_builtin_actions()
    app = SeretoUnifiedApp(entry_point=entry_point, project=project)
    await app.run_async()
