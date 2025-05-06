import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter  # type: ignore
from pydantic import DirectoryPath, ValidationError
from rapidfuzz import fuzz
from rich.markup import escape
from rich.syntax import Syntax
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.types import NoSelection
from textual.widget import Widget
from textual.widgets import Button, DataTable, Footer, Header, Input, Rule, Select, SelectionList, Static

from sereto.enums import Risk
from sereto.exceptions import SeretoValueError
from sereto.models.finding import FindingTemplateFrontmatterModel, VarsMetadataModel
from sereto.project import Project
from sereto.tui.widgets.input import InputWithLabel, ListInput, SelectWithLabel


@dataclass
class FindingMetadata:
    path: Path
    category: str
    name: str
    variables: list[VarsMetadataModel]
    keywords: list[str]
    search_similarity: float | None = None


class FindingPreviewScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    FindingPreviewScreen {
        #code {
            border: heavy $accent;
            margin: 2 4;
            scrollbar-gutter: stable;
            Static {
                width: auto;
            }
        }
    }
    """
    BINDINGS = [
        ("a", "add_finding", "Add finding"),
        ("escape", "dismiss", "Dismiss preview"),
    ]

    def __init__(self, title: str, code: str) -> None:
        super().__init__()
        self.code = code
        self.title = title

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="code"):
            yield Static(
                Syntax(self.code, lexer="markdown", indent_guides=True, line_numbers=True),
                expand=True,
            )

    def on_mount(self) -> None:
        code_widget = self.query_one("#code")
        code_widget.border_title = self.title
        code_widget.border_subtitle = "A to add finding; Esc to close"

    def action_add_finding(self) -> None:
        self.dismiss()
        self.app.query_one("#results", ResultsWidget).action_add_finding()


class AddFindingScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Dismiss finding")]

    def __init__(self, templates: DirectoryPath, finding: FindingMetadata, title: str) -> None:
        super().__init__()
        self.templates = templates
        self.finding = finding
        self.title = title

    def compose(self) -> ComposeResult:
        app: SeretoApp = self.app  # type: ignore[assignment]
        all_targets = [t for v in app.project.config.versions for t in app.project.config.at_version(v).targets]

        with ScrollableContainer(id="add-finding"):
            # Name
            self.input_name = Input(value=self.finding.name)
            yield InputWithLabel(self.input_name, label="Name")
            # Risk
            risks = [r.capitalize() for r in Risk]
            self.select_risk = SelectWithLabel[str](options=[(r, r) for r in risks], label="Risk")
            yield self.select_risk
            # Target
            self.select_target = SelectWithLabel[str](
                options=[(t.uname, t.uname) for t in all_targets],
                label="Target",
                allow_blank=False,
            )
            yield self.select_target

            yield Static("[b]Variables", classes="section-header")
            yield Rule()

            for var in self.finding.variables:
                yield Static(f"[b]{var.name}:[/b] {escape(var.type_annotation)}\n  {var.description}", classes="pl-1")
                if var.is_list:
                    yield ListInput(id=f"var-{var.name}")
                else:
                    yield Input(id=f"var-{var.name}", classes="m-1")

                yield Rule()

            self.btn_save_finding = Button.success("Save", id="save-finding", classes="m-1")
            yield self.btn_save_finding

    def on_mount(self) -> None:
        add_finding = self.query_one("#add-finding")
        add_finding.border_title = self.title
        add_finding.border_subtitle = "Esc to close"

    def _load_variables(self) -> dict[str, Any]:
        """Load variables from the inputs.

        Returns:
            A dictionary of variables with their values.

        Raises:
            SeretoValueError: If a required variable is not set.
        """
        variables: dict[str, Any] = {}

        for var in self.finding.variables:
            if var.is_list:
                all_inputs = self.query_one(f"#var-{var.name}", ListInput).query(Input).results()
                input_values = [input.value.strip() for input in all_inputs if len(input.value.strip()) > 0]
                if var.required and len(input_values) == 0:
                    raise SeretoValueError(f"variable '{var.name}' is required")
                else:
                    # always set list variables, even if empty
                    variables[var.name] = input_values
            else:
                value = self.query_one(f"#var-{var.name}", Input).value.strip()
                if len(value) == 0:
                    if var.required:
                        raise SeretoValueError(f"variable '{var.name}' is required")
                    else:
                        # don't set the variable if not required and empty
                        continue
                else:
                    variables[var.name] = value

        return variables

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Save button press event."""
        if event.button is not self.btn_save_finding:
            return

        app: SeretoApp = self.app  # type: ignore[assignment]

        # Retrieve the values from the inputs
        # - name
        name = self.input_name.value  # TODO: check for None, report "Name is required"
        # - risk
        risk_select: Select[str] = self.select_risk.query_one(Select)
        risk = Risk(risk_select.value.lower()) if not isinstance(risk_select.value, NoSelection) else None
        # - target
        target_select: Select[str] = self.select_target.query_one(Select)
        all_targets = [t for v in app.project.config.versions for t in app.project.config.at_version(v).targets]
        matching_target = [t for t in all_targets if t.uname == target_select.value]
        if len(matching_target) != 1:
            raise SeretoValueError(f"target with uname {target_select.value!r} not found")
        target = matching_target[0]

        # - variables
        try:
            variables = self._load_variables()
        except SeretoValueError as ex:
            self.notify(title="Validation error", message=str(ex), severity="error")
            return

        # Create the sub-finding
        target.findings.add_from_template(
            templates=self.templates,
            template_path=self.finding.path,
            category=self.finding.category.lower(),
            name=name,
            risk=risk,
            variables=variables,
        )

        # Navigate back, focus on the search input field
        self.dismiss()
        self.notify(message=name, title="Finding successfully added")
        app.action_focus_search()


class SearchWidget(Widget):
    def compose(self) -> ComposeResult:
        app: SeretoApp = self.app  # type: ignore[assignment]
        self.input_field = Input(placeholder="Type to search...")
        self.category_filter = SelectionList[str](*[(category, category, True) for category in app.categories])

        with Horizontal():
            with Container(classes="input-field"):
                yield self.input_field
            with Container(classes="category-filter"):
                yield self.category_filter

    def on_mount(self) -> None:
        self.input_field.focus()

    @on(Input.Changed)
    @on(SelectionList.SelectedChanged)
    def update_results(self) -> None:
        query = self.input_field.value.strip()
        results_widget = self.app.query_one("#results", ResultsWidget)
        results_table: DataTable[str] = results_widget.query_one("DataTable", DataTable)
        results_table.clear()

        selected_categories = [c.lower() for c in self.category_filter.selected]
        filtered_findings = [f for f in results_widget.findings if f.category.lower() in selected_categories]

        if len(query) == 0:
            return

        # compute search similarity
        for f in filtered_findings:
            name_score = fuzz.partial_ratio(query, f.name, processor=lambda x: x.lower())
            keywords_scores = [
                fuzz.partial_ratio(query, keyword, processor=lambda x: x.lower()) for keyword in f.keywords
            ]
            max_keywords_score = max(keywords_scores) if keywords_scores else 0
            f.search_similarity = 0.7 * name_score + 0.3 * max_keywords_score

        # display matching findings
        for f in sorted(
            filtered_findings,
            key=lambda f: f.search_similarity if f.search_similarity is not None else 0,
            reverse=True,
        ):
            ix = results_widget.findings.index(f)  # index in the list of all findings
            results_table.add_row(
                f.category, f.name, "; ".join(f.keywords), label=f"{f.search_similarity:.2f}", key=str(ix)
            )


class ResultsWidget(Widget):
    BINDINGS = [("a", "add_finding", "Add finding")]

    def compose(self) -> ComposeResult:
        # load data
        self.findings: list[FindingMetadata] = []
        app: SeretoApp = self.app  # type: ignore[assignment]

        for category in app.categories:
            for finding in (app.project.settings.templates_path / "categories" / category.lower() / "findings").glob(
                "*.md.j2"
            ):
                metadata, _ = frontmatter.parse(finding.read_text())

                try:
                    data = FindingTemplateFrontmatterModel.model_validate(metadata)
                except ValidationError as ex:
                    raise SeretoValueError(f"invalid template metadata in '{finding}'") from ex

                self.findings.append(
                    FindingMetadata(
                        path=finding,
                        category=category,
                        name=data.name,
                        variables=data.variables,
                        keywords=data.keywords,
                    )
                )

        # display results table
        self.results_table: DataTable[str] = DataTable[str](cursor_type="row")
        self.results_table.add_columns("Category", "Name", "Keywords")

        yield Vertical(self.results_table, classes="results")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value is None:
            return
        self.selected_finding = self.findings[int(event.row_key.value)]
        self.app.push_screen(FindingPreviewScreen("Finding preview", self.selected_finding.path.read_text()))

    def action_add_finding(self) -> None:
        # Get the keys for the row under the cursor.
        row_key, _ = self.results_table.coordinate_to_cell_key(self.results_table.cursor_coordinate)

        if row_key.value is None:
            return

        self.app.push_screen(
            AddFindingScreen(
                templates=self.app.project.settings.templates_path,  # type: ignore[attr-defined]
                finding=self.findings[int(row_key.value)],
                title="Add finding",
            )
        )


class SeretoApp(App[None]):
    """A SeReTo Textual CLI interface."""

    CSS_PATH = "finding.tcss"
    TITLE = "SeReTo"
    SUB_TITLE = "Security Reporting Tool"
    BINDINGS = [("/", "focus_search", "Focus on search")]

    def __init__(
        self,
        project: Project,
        categories: list[str],
    ) -> None:
        super().__init__()
        self.project = project
        self.categories = categories

    def compose(self) -> ComposeResult:
        """Add widgets to the app."""
        # adding findings only works if there is at least one target
        if len(self.project.config.last_config.targets) == 0:
            raise SeretoValueError("no targets found in the configuration")

        yield Header()
        yield SearchWidget(id="search")
        yield ResultsWidget(id="results")
        yield Footer()

    def action_focus_search(self) -> None:
        """Focus on the search input field."""
        self.query_one("#search", SearchWidget).input_field.focus()


async def launch_finding_tui(project: Project | None = None) -> None:
    if project is None:
        project = Project()
    categories = sorted([c.upper() for c in project.settings.categories])
    app = SeretoApp(project=project, categories=categories)
    await app.run_async()


if __name__ == "__main__":
    asyncio.run(launch_finding_tui())
