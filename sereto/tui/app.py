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

import shutil
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from pydantic import TypeAdapter, ValidationError
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen, Screen
from textual.types import NoSelection
from textual.widget import Widget
from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Rule, Select, Static, TabbedContent, TabPane

from sereto.config import VersionConfig
from sereto.enums import Risk
from sereto.exceptions import SeretoPathError, SeretoValueError
from sereto.models.date import Date, DateRange, DateType, SeretoDate
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

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self._message, id="confirm-message", markup=True)
            with Horizontal(id="confirm-buttons"):
                yield Button("Confirm", variant="success", id="confirm-yes")
                yield Button("Cancel", variant="default", id="confirm-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")

    def action_cancel(self) -> None:
        self.dismiss(False)


# ── Risk label helpers ─────────────────────────────────────────────────────────
_RISK_STYLE: dict[Risk, str] = {
    Risk.critical: "bold red",
    Risk.high: "bold dark_orange",
    Risk.medium: "bold yellow1",
    Risk.low: "bold green1",
    Risk.info: "bold slate_blue1",
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

    # Entry points that just select their matching tab (`tab-<entry_point>`),
    # e.g. `sereto config targets add` → launch_tui(entry_point="targets").
    TABS: ClassVar[frozenset[str]] = frozenset({"targets", "dates", "people"})

    def __init__(self, initial_tab: str | None = None) -> None:
        super().__init__()
        self._initial_tab = initial_tab

    @property
    def _active_vc(self) -> VersionConfig:
        app: Any = self.app
        return app.project.config.at_version(app.selected_project_version)

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="config-tabs"):
            with TabPane("General", id="tab-general"), ScrollableContainer(id="general-form"):
                yield InputWithLabel(Input(id="cfg-id", placeholder=self._active_vc.id), "ID")
                yield InputWithLabel(Input(id="cfg-name", placeholder=self._active_vc.name), "Name")
                yield InputWithLabel(
                    Input(id="cfg-version-desc", placeholder=self._active_vc.version_description), "Desc"
                )
                with Horizontal(classes="config-add-row"):
                    yield Button("Save", variant="success", id="save-general")
            with TabPane("Targets", id="tab-targets"), Vertical(classes="tab-container"):
                yield Button("Add", id="scroll-add-targets-btn", classes="scroll-add-btn", variant="primary")
                with ScrollableContainer(id="targets-form"):
                    yield Vertical(id="targets-list")
                    with Vertical(id="targets-add-form", classes="add-form-section"):
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
            with TabPane("Dates", id="tab-dates"), Vertical(classes="tab-container"):
                yield Button("Add", id="scroll-add-dates-btn", classes="scroll-add-btn", variant="primary")
                with ScrollableContainer(id="dates-form"):
                    yield Vertical(id="dates-list")
                    with Vertical(id="dates-add-form", classes="add-form-section"):
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
            with TabPane("People", id="tab-people"), Vertical(classes="tab-container"):
                yield Button("Add", id="scroll-add-people-btn", classes="scroll-add-btn", variant="primary")
                with ScrollableContainer(id="people-form"):
                    yield Vertical(id="people-list")
                    with Vertical(id="people-add-form", classes="add-form-section"):
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

        # Populate category select
        category_select = self.query_one("#target-category-select", Select)
        category_options = [(cat, cat.lower()) for cat in app.categories]
        category_select.set_options(category_options)

        # Load project's configuration data
        self._refresh_targets()
        self._refresh_dates()
        self._refresh_people()

        # Initialize button visibility and set up periodic updates
        self.set_timer(0.1, self._update_button_visibility)
        self.set_interval(0.5, self._update_button_visibility)

    def _update_button_visibility(self) -> None:
        """Update visibility of Add button for the currently active tab only."""
        tabs = self.query_one("#config-tabs", TabbedContent)
        active_tab = tabs.active
        if active_tab:
            active_tab = active_tab.removeprefix("tab-")
        if active_tab != "general" and active_tab not in self.TABS:
            raise RuntimeError(f"Unexpected tab ID: {tabs.active!r}")
        self._check_form_visibility(f"{active_tab}-form", f"{active_tab}-add-form", f"scroll-add-{active_tab}-btn")

    # ── Button handlers ────────────────────────────────────────────────────────
    @on(Button.Pressed, "#save-general")
    def handle_save_general(self) -> None:
        self._do_save_general()

    @on(Button.Pressed, "#add-target-btn")
    def handle_add_target(self) -> None:
        self._do_add_target()

    @on(Button.Pressed, "#add-date-btn")
    def handle_add_date(self) -> None:
        self._do_add_date()

    @on(Button.Pressed, "#add-person-btn")
    def handle_add_person(self) -> None:
        self._do_add_person()

    @on(Button.Pressed, "#scroll-add-targets-btn, #scroll-add-dates-btn, #scroll-add-people-btn")
    def handle_scroll_to_form(self, event: Button.Pressed) -> None:
        """Focus and scroll to the form for the clicked tab."""
        button_id = event.button.id or ""
        tab_name = button_id.removeprefix("scroll-add-").removesuffix("-btn")

        # Map tab names to their first input selector
        select_map = {
            "targets": "#target-category-select",
            "dates": "#date-type-select",
            "people": "#person-type-select",
        }

        if tab_name in select_map:
            select = self.query_one(select_map[tab_name], Select)
            container = self.query_one(f"#{tab_name}-form", ScrollableContainer)
            select.focus()
            self.call_after_refresh(lambda: container.scroll_to_widget(select, top=True))
            event.button.display = False

    def _check_form_visibility(self, container_id: str, form_id: str, button_id: str) -> None:
        """Check if form is visible and toggle button visibility accordingly."""
        try:
            container = self.query_one(f"#{container_id}", ScrollableContainer)
            form = self.query_one(f"#{form_id}")
            button = self.query_one(f"#{button_id}", Button)

            # Get the scroll position
            scroll_y = container.scroll_y
            viewport_height = container.size.height
            viewport_bottom = scroll_y + viewport_height

            # Only show button if there's enough total content that scrolling is needed
            total_content_height = container.virtual_size.height
            if total_content_height <= viewport_height * 1.2:
                button.display = False
                return

            # Calculate form's position within the scroll container
            # Walk up from form to find its offset relative to the scrollable container
            form_offset_y = 0
            node: Widget = form
            while node.parent is not None and node.parent != container:
                form_offset_y += node.offset.y
                node = node.parent  # type: ignore
            if node.parent == container:
                form_offset_y += node.offset.y

            form_top = form_offset_y
            form_bottom = form_top + form.size.height

            # Calculate how much of the form is visible in the viewport
            visible_top = max(form_top, scroll_y)
            visible_bottom = min(form_bottom, viewport_bottom)
            visible_height = max(0, visible_bottom - visible_top)

            # Show button only if less than 30% of form is visible
            # (meaning it's mostly scrolled out of view)
            form_is_mostly_hidden = visible_height < (form.size.height * 0.5)
            button.display = not form_is_mostly_hidden
        except Exception:
            pass

    @on(Button.Pressed, ".config-ppl-remove-btn, .config-targets-remove-btn, .timeline-remove-btn")
    def handle_remove(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        button_id = button_id.removeprefix("remove-")

        handler_map = {
            "target": self._do_remove_target,
            "date": self._do_remove_date,
            "person": self._do_remove_person,
        }

        for type_prefix, handler in handler_map.items():
            if button_id.startswith(f"{type_prefix}-"):
                index = int(button_id.removeprefix(f"{type_prefix}-"))
                self.app.push_screen(
                    DeleteConfirmationScreen(f"Remove this {type_prefix}?"),
                    callback=lambda confirmed, i=index, h=handler: h(i) if confirmed else None,
                )
                return

    # ── List refresh ───────────────────────────────────────────────────────────
    def _refresh_targets(self) -> None:
        container = self.query_one("#targets-list", Vertical)
        container.remove_children()
        for i, t in enumerate(self._active_vc.targets, start=1):
            container.mount(_TargetRow(t, i))
        self.set_timer(
            0.1, lambda: self._check_form_visibility("targets-form", "target-add-form", "scroll-add-target-btn")
        )

    def sort_key(self, d: Date) -> tuple[SeretoDate, SeretoDate]:
        if isinstance(d.date, DateRange):
            return (d.date.start, d.date.end)
        else:
            return (d.date, d.date)

    def _refresh_dates(self) -> None:
        container = self.query_one("#dates-list", Vertical)
        container.remove_children()
        dates_list = list(self._active_vc.dates)
        # sort by most recent start date first, then by end date if start dates are equal
        sorted_dates = sorted(dates_list, key=self.sort_key, reverse=True)
        for i, d in enumerate(sorted_dates, start=1):
            is_first = i == 1
            is_last = i == len(sorted_dates)
            container.mount(_DateRow(d, i, is_first, is_last))
        self.set_timer(0.1, lambda: self._check_form_visibility("dates-form", "date-add-form", "scroll-add-date-btn"))

    def _refresh_people(self) -> None:
        container = self.query_one("#people-list", Vertical)
        container.remove_children()
        people_list = list(self._active_vc.people)
        sorted_people = sorted(people_list, key=lambda p: p.type.value)
        for i, p in enumerate(sorted_people, start=1):
            container.mount(_PersonRow(p, i))
        self.set_timer(
            0.1, lambda: self._check_form_visibility("people-form", "person-add-form", "scroll-add-person-btn")
        )

    # ── Targets tab actions ────────────────────────────────────────────────────
    def _do_add_target(self) -> None:
        cat_select = self.query_one("#target-category-select", Select)
        name_input = self.query_one("#target-name", Input)

        if isinstance(cat_select.value, NoSelection):
            self.notify("Select a category.", severity="warning", timeout=3)
            return

        category: str = cat_select.value
        name = name_input.value.strip()

        if not name:
            self.notify("Enter a target name.", severity="warning", timeout=3)
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

        name_input.value = ""
        self._refresh_targets()

        self.notify(name, title="Target added", timeout=3)

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
    def _do_add_date(self) -> None:
        type_select = self.query_one("#date-type-select", Select)
        start_input = self.query_one("#date-start", Input)
        end_input = self.query_one("#date-end", Input)

        if isinstance(type_select.value, NoSelection):
            self.notify("Select a date type.", severity="warning", timeout=3)
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
            self.notify("Select a person type.", severity="warning", timeout=3)
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

        # Reset form fields after successful addition
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


# ── Config row widgets ─────────────────────────────────────────────────────────
class _DateRow(Vertical):
    """Single row in the dates list: formatted date text in timeline style + Remove button."""

    def __init__(self, date: Date, index: int, is_first: bool = False, is_last: bool = False) -> None:
        super().__init__(classes="timeline-row")
        self._date = date
        self._index = index  # 1-based
        self._is_first = is_first
        self._is_last = is_last

    def compose(self) -> ComposeResult:
        # Top connector line (if not first)
        if not self._is_first:
            with Horizontal(classes="timeline-line-row"):
                yield Static("", classes="timeline-date-spacer")
                yield Static("│", classes="timeline-line")
                yield Static("", classes="timeline-content-spacer")

        # Main row: Date, Circle, Type, Button
        with Horizontal(classes="timeline-main-row"):
            # Date on left
            match self._date.date:
                case DateRange():
                    date_text = f"{self._date.date.start} – {self._date.date.end}"
                case _:
                    date_text = str(self._date.date)
            yield Static(date_text, classes="timeline-date")

            # Circle
            yield Static("○", classes="timeline-dot")

            # Type label
            type_label = self._date.type.value.replace("_", " ").title()
            yield Static(type_label, classes="timeline-type")

            # Remove button
            yield Button("\u2715", variant="error", id=f"remove-date-{self._index}", classes="timeline-remove-btn")

        # Bottom connector line (if not last)
        if not self._is_last:
            with Horizontal(classes="timeline-line-row"):
                yield Static("", classes="timeline-date-spacer")
                yield Static("│", classes="timeline-line")
                yield Static("", classes="timeline-content-spacer")


class _TargetRow(Horizontal):
    """Single row in the targets list: formatted target text + Remove button."""

    def __init__(self, target: Target, index: int) -> None:
        super().__init__(classes="config-row")
        self._target = target
        self._index = index  # 1-based

    def compose(self) -> ComposeResult:
        text = f"[bold cyan]{self._target.data.category.upper()}[/bold cyan]  {self._target.data.name}"
        yield Static(text, classes="config-row-label", markup=True)
        yield Button("\u2715", variant="error", id=f"remove-target-{self._index}", classes="config-targets-remove-btn")


class _PersonRow(Horizontal):
    """Single row in the people list: type badge + name on first line, details on
    indented second line, remove button on right."""

    def __init__(self, person: Person, index: int) -> None:
        super().__init__(classes="person-row")
        self._person = person
        self._index = index  # 1-based

    def compose(self) -> ComposeResult:
        # Left side: Content (type badge, name, details)
        with Vertical(classes="person-content"):
            # First line: Type badge + Name
            with Horizontal(classes="person-header-row"):
                # Type badge
                type_label = self._person.type.value.replace("_", " ").title()
                yield Static(f"[bold cyan]{type_label}[/bold cyan]", classes="person-type-badge", markup=True)

                # Name
                name = self._person.name or "[dim](no name)[/dim]"
                yield Static(name, classes="person-name", markup=True)

            # Second line: Details (indented)
            details: list[str] = []
            if self._person.email:
                details.append(f"📧 {self._person.email}")
            if self._person.business_unit:
                details.append(f"🏢 {self._person.business_unit}")
            if self._person.role:
                details.append(f"👔 {self._person.role}")

            # Always show details line, even if empty
            detail_text = "  |  ".join(details) if details else "[dim](no details)[/dim]"
            yield Static(detail_text, classes="person-details", markup=True)

        # Right side: Remove button (spans full height, centered)
        yield Button("\u2715", variant="error", id=f"remove-person-{self._index}", classes="config-ppl-remove-btn")


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
                    prompt="Select render type…",
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
            stat_text = Text.assemble((f"{count}", _RISK_STYLE[risk]), f" {label}")
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
                    (target.data.category.upper(), "bold dark_magenta"),
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
