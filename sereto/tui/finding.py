import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter  # type: ignore
from pydantic import DirectoryPath, ValidationError
from rich.markup import escape
from rich.syntax import Syntax
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.fuzzy import Matcher
from textual.screen import ModalScreen
from textual.types import NoSelection
from textual.widget import Widget
from textual.widgets import Button, Footer, Header, Input, ListItem, ListView, Rule, Select, SelectionList, Static

from sereto.enums import Risk
from sereto.exceptions import SeretoValueError
from sereto.models.finding import FindingTemplateFrontmatterModel, VarsMetadataModel
from sereto.parsing import parse_query
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
        self.app.query_one("#search", SearchWidget).action_add_finding()


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


class FuzzyMatcher:
    def __init__(self, query:list[str])->None:
        self.query = [q.lower() for q in query]

    def max_score(self, values: list[str]) -> int:
        """
        Calculate the average fuzzy match score between the query and the given values.
        """
        if not self.query:
            return 0

        combined = '; '.join(values)
        scores=[Matcher(q).match(combined) for q in self.query]
        result_score=(sum(scores)/len(scores))*100 if scores else 0

        return result_score

    def highlight(self, text: list[str]) -> Text:
        """
        Highlight all fuzzy matches of the query in the given text.
        """
        combined = '; '.join(text)
        result_text = Text(combined)

        for q in self.query:
            for span in Matcher(q).highlight(combined).spans:
                result_text.stylize('bold yellow', span.start, span.end)

        return result_text


class SearchWidget(Widget):
    BINDINGS = [("a", "add_finding", "Add finding")]
    def __init__(self):
        super().__init__()
        self.findings: list[FindingMetadata] = []
        self.filtered_findings: list[FindingMetadata] = []
        self._load_findings()

    def _load_findings(self):
        app: SeretoApp = self.app  # type: ignore[assignment]

        for category in app.categories:
            for finding in (app.project.settings.templates_path / "categories" / category.lower() / "findings").glob(
                    "*.md.j2"
            ):
                file_text = finding.read_text()
                metadata, _ = frontmatter.parse(file_text)

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

    def compose(self) -> ComposeResult:
        app: SeretoApp = self.app  # type: ignore[assignment]

        self.input_field = Input(placeholder="Type to search...", classes='input-field')
        self.category_filter = SelectionList[str](*[(category, category, True) for category in app.categories])
        self.result_list=ListView(classes='search-result')

        with Horizontal(classes="search-panel"):
            with Vertical(), Container(classes="search-palette"):
                    yield self.input_field
                    yield self.result_list
            with Container(classes="category-filter"):
                yield self.category_filter

    def on_mount(self) -> None:
        self.input_field.focus()
        self.update_results()

    @on(Input.Changed)
    @on(SelectionList.SelectedChanged)
    def update_results(self) -> None:
        query = self.input_field.value.strip()
        keys={'name':'n', 'keyword':'k'}
        parsed=parse_query(query, keys)

        self.result_list.clear()

        if len(query) == 0:
            return

        selected_categories = [c.lower() for c in self.category_filter.selected]
        filtered_findings = [f for f in self.findings if f.category.lower() in selected_categories]

        # reusable fuzzy matchers for scoring and highlighting
        matcher_dict = {
            key: FuzzyMatcher(parsed[key])
            for key in keys
        }

        # compute search similarity
        for f in filtered_findings:
            scores=[]

            if parsed['name']:
                scores.append(matcher_dict['name'].max_score([f.name]))

            if parsed['keyword']:
                scores.append(matcher_dict['keyword'].max_score(f.keywords))

            f.search_similarity=sum(scores)/len(scores) if scores else 0

        # display matching findings
        for f in sorted(
            filtered_findings,
            key=lambda f: f.search_similarity if f.search_similarity is not None else 0,
            reverse=True,
        ):
            if f.search_similarity > 50:
                self.result_list.index=0
                self.result_list.append(ResultItem(f, matcher_dict))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ResultItem):
            self.selected_finding = item.finding
            self.app.push_screen(
                FindingPreviewScreen(
                    'Finding preview',
                    self.selected_finding.path.read_text()
                )
            )

    def action_add_finding(self) -> None:
        item = self.result_list.children[self.result_list.index]
        if isinstance(item, ResultItem):
            self.app.push_screen(
                AddFindingScreen(
                    self.app.project.settings.templates_path,
                    item.finding,
                    'Add finding'
                )
            )


class ResultItem(ListItem):
    def __init__(self, finding: FindingMetadata, matchers:dict[str, FuzzyMatcher]):
        super().__init__(classes='result-item')
        self.finding = finding
        self.matchers = matchers

    def compose(self) -> ComposeResult:
        if self.matchers['name']:
            name_text=self.matchers['name'].highlight([self.finding.name])
        else:
            name_text=Text(self.finding.name)

        if self.matchers['keyword']:
            keywords_text = self.matchers['keyword'].highlight(self.finding.keywords)
        else:
            keywords_text = Text(";".join(self.finding.keywords))


        text=Text.assemble(
            name_text+'\n',
            Text(style='italic dim')+keywords_text
        )
        yield Static(text, expand=True)


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

        search=SearchWidget()
        search.id='search'
        search.classes='dropdown'

        yield Header()
        yield search
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
