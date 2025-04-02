from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

import frontmatter  # type: ignore
from pydantic import DirectoryPath, ValidationError
from rapidfuzz import fuzz
from rich.console import RenderableType
from rich.syntax import Syntax
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.types import NoSelection
from textual.widget import Widget
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Select, SelectionList, Static

from sereto.enums import Risk
from sereto.exceptions import SeretoValueError
from sereto.models.finding import FindingTemplateFrontmatterModel
from sereto.project import Project


@dataclass
class FindingMetadata:
    path: Path
    category: str
    name: str
    variables: dict[str, Any]
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


class InputWithLabel(Widget):
    """An input with a label."""

    DEFAULT_CSS = """
    InputWithLabel {
        layout: horizontal;
        height: auto;
    }
    InputWithLabel Label {
        padding: 1;
        width: 12;
        text-align: right;
    }
    InputWithLabel Input {
        width: 1fr;
    }
    """

    def __init__(self, input_label: str, value: str | None = None, id: str | None = None) -> None:
        super().__init__(id=id)
        self.input_label = input_label
        self.value = value

    def compose(self) -> ComposeResult:
        yield Label(self.input_label)
        yield Input(value=self.value)


T = TypeVar("T")


class SelectWithLabel(Generic[T], Widget):
    """A select with a label."""

    DEFAULT_CSS = """
    SelectWithLabel {
        layout: horizontal;
        height: auto;
    }
    SelectWithLabel Label {
        padding: 1;
        width: 12;
        text-align: right;
    }
    SelectWithLabel Input {
        width: 1fr;
    }
    """

    def __init__(
        self, options: Iterable[tuple[RenderableType, T]], label: str, id: str | None = None, allow_blank: bool = True
    ) -> None:
        super().__init__(id=id)
        self.options = options
        self.label = label
        self.allow_blank = allow_blank

    def compose(self) -> ComposeResult:
        yield Label(self.label)
        yield Select(options=self.options, allow_blank=self.allow_blank)


class AddFindingScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    AddFindingScreen {
        #add-finding {
            border: heavy $accent;
            margin: 2 4;
            scrollbar-gutter: stable;
            Static {
                width: auto;
            }
        }
    }
    """
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
            yield InputWithLabel("Name", value=self.finding.name, id="name-input")
            risks = [r.capitalize() for r in Risk]
            yield SelectWithLabel[str](options=[(r, r) for r in risks], label="Risk", id="risk-select")
            yield SelectWithLabel[str](
                options=[(t.uname, t.uname) for t in all_targets],
                label="Target",
                id="target-select",
                allow_blank=False,
            )
            yield Button.success("Save")

    def on_mount(self) -> None:
        add_finding = self.query_one("#add-finding")
        add_finding.border_title = self.title
        add_finding.border_subtitle = "Esc to close"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app: SeretoApp = self.app  # type: ignore[assignment]
        name_input = self.query_one("#name-input Input", Input)
        name = name_input.value.strip()
        risk_select: Select[str] = self.query_one("#risk-select Select", Select)
        risk = Risk(risk_select.value.lower()) if not isinstance(risk_select.value, NoSelection) else None
        target_select: Select[str] = self.query_one("#target-select Select", Select)

        all_targets = [t for v in app.project.config.versions for t in app.project.config.at_version(v).targets]
        matching_target = [t for t in all_targets if t.uname == target_select.value]
        if len(matching_target) != 1:
            raise SeretoValueError(f"target with uname {target_select.value!r} not found")
        target = matching_target[0]

        target.findings.add_from_template(
            templates=self.templates,
            template_path=self.finding.path,
            category=self.finding.category.lower(),
            name=name,
            risk=risk,
            variables=self.finding.variables,
        )

        # navigate back, focus on the search input field
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
                        variables={v.name: v.descriptive_value for v in data.variables},
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
        #  settings: Settings,
        project: Project,
        categories: list[str],
    ) -> None:
        super().__init__()
        # self.settings = settings
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


if __name__ == "__main__":
    project = Project()
    categories = sorted([c.upper() for c in project.settings.categories])
    app = SeretoApp(project=project, categories=categories)
    app.run()
