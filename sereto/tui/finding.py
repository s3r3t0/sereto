import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter  # type: ignore
from jinja2 import Environment
from pydantic import DirectoryPath, ValidationError
from rapidfuzz import fuzz
from rich.markup import escape
from rich.syntax import Syntax
from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.fuzzy import Matcher
from textual.screen import ModalScreen
from textual.types import NoSelection
from textual.widget import Widget
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    OptionList,
    Rule,
    Select,
    SelectionList,
    Static,
    Switch,
)
from textual.widgets.option_list import Option

from sereto.enums import Risk
from sereto.exceptions import SeretoValueError
from sereto.extract import extract_block_from_jinja, extract_text_from_jinja
from sereto.models.finding import FindingTemplateFrontmatterModel, VarsMetadataModel
from sereto.parsing import parse_query
from sereto.project import Project
from sereto.target import Target
from sereto.tui.widgets.input import InputWithLabel, ListWidget, SelectWithLabel


@dataclass
class FindingMetadata:
    path: Path
    category: str
    name: str
    variables: list[VarsMetadataModel]
    keywords: list[str]
    text: dict[str, str]
    search_similarity: float = 0.0


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
        ("ctrl+s", "add_finding", "Add finding"),
        ("escape", "dismiss", "Dismiss preview"),
    ]

    def __init__(self, title: str, code: str | Text) -> None:
        super().__init__()
        self.code = code
        self.title = title

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="code"):
            if isinstance(self.code, str):
                syntax = Syntax(self.code, lexer="markdown", indent_guides=True, line_numbers=True)
                yield Static(syntax, expand=True)
            else:
                yield Static(self.code, expand=True)

    def on_mount(self) -> None:
        code_widget = self.query_one("#code")
        code_widget.border_title = self.title
        code_widget.border_subtitle = "^s to add finding; Esc to close"

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

            # Existing finding warning + overwrite switch
            self.overwrite_switch = Switch(value=False, name="overwrite", id="overwrite-switch")
            self.overwrite_warning = Horizontal(
                self.overwrite_switch,
                Static(
                    "[b red]Warning:[/b red] A finding with this name already exists in the selected target.\n"
                    "  [b]Switch OFF:[/b] Keep the original and create a new one with a random suffix.\n"
                    "  [b]Switch ON:[/b] Overwrite the existing finding."
                ),
                id="overwrite-warning",
            )
            self.overwrite_warning.display = False
            yield self.overwrite_warning

            yield Static("[b]Variables", classes="section-header")
            yield Rule()

            for var in self.finding.variables:
                yield Static(f"[b]{var.name}:[/b] {escape(var.type_annotation)}\n  {var.description}", classes="pl-1")
                if var.is_list:
                    match var.type:
                        case "boolean":
                            yield ListWidget(
                                widget_factory=lambda var=var: Select(  # type: ignore[misc]
                                    options=[
                                        ("True", True),
                                        ("False", False),
                                    ],
                                    allow_blank=not var.required,
                                ),
                                id=f"var-{var.name}",
                            )
                        case "integer":
                            yield ListWidget(
                                widget_factory=lambda: Input(type="integer", classes="m-1"),
                                id=f"var-{var.name}",
                            )
                        case _:
                            yield ListWidget(
                                widget_factory=lambda: Input(classes="m-1"),
                                id=f"var-{var.name}",
                            )
                else:
                    match var.type:
                        case "boolean":
                            yield Select(
                                options=[
                                    ("True", True),
                                    ("False", False),
                                ],
                                allow_blank=not var.required,
                                id=f"var-{var.name}",
                            )
                        case "integer":
                            yield Input(id=f"var-{var.name}", type="integer", classes="m-1")
                        case _:
                            yield Input(id=f"var-{var.name}", classes="m-1")
                yield Rule()

            self.btn_save_finding = Button.success("Save", id="save-finding", classes="m-1")
            yield self.btn_save_finding

    def on_mount(self) -> None:
        add_finding = self.query_one("#add-finding")
        add_finding.border_title = self.title
        add_finding.border_subtitle = "Esc to close"

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select is self.select_target.query_one(Select):
            self.update_overwrite_warning()

    def update_overwrite_warning(self) -> None:
        """Update the overwrite warning and switch dynamically."""
        try:
            target = self._retrieve_target()
        except Exception:
            self.overwrite_warning.display = False
            return

        finding_path = target.findings.get_path(
            name=self.finding.path.name.removesuffix(".md.j2"),
            category=self.finding.category.lower(),
        )
        self.overwrite_warning.display = finding_path.is_file()

    def _load_variables(self) -> dict[str, Any]:
        """Load variables from the inputs.
        Raises:
            SeretoValueError: If a required variable is not set.
        """
        variables: dict[str, Any] = {}

        for var in self.finding.variables:
            if var.is_list:
                widgets = list(self.query_one(f"#var-{var.name}", ListWidget).query(".widget").results())

                match var.type:
                    case "boolean":
                        # get values, filter out NoSelection
                        values = [
                            w.value for w in widgets if isinstance(w, Select) and not isinstance(w.value, NoSelection)
                        ]
                    case "integer":
                        values_str = [
                            w.value.strip() for w in widgets if isinstance(w, Input) and len(w.value.strip()) > 0
                        ]
                        try:
                            values = [int(v) for v in values_str]
                        except ValueError:
                            raise SeretoValueError(f"variable '{var.name}' must be an integer") from None
                    case _:
                        values = [
                            w.value.strip() for w in widgets if isinstance(w, Input) and len(w.value.strip()) > 0
                        ]

                if var.required and len(values) == 0:
                    raise SeretoValueError(f"variable '{var.name}' is required")
                elif len(values) == 0:
                    # don't set the variable if not required and empty
                    continue
                # always set list variables, even if empty
                variables[var.name] = values
                continue
            else:
                match var.type:
                    case "boolean":
                        value_select: Select[bool] = self.query_one(f"#var-{var.name}", Select)
                        value: int | str | None = (
                            value_select.value if not isinstance(value_select.value, NoSelection) else None
                        )
                    case "integer":
                        value_str = self.query_one(f"#var-{var.name}", Input).value.strip()
                        if len(value_str) == 0:
                            if var.required:
                                raise SeretoValueError(f"variable '{var.name}' is required")
                            else:
                                continue
                        try:
                            value = int(value_str)
                        except ValueError:
                            raise SeretoValueError(f"variable '{var.name}' must be an integer") from None
                    case _:
                        value = self.query_one(f"#var-{var.name}", Input).value.strip()
                        if len(value) == 0:
                            if var.required:
                                raise SeretoValueError(f"variable '{var.name}' is required")
                            else:
                                # don't set the variable if not required and empty
                                continue
                variables[var.name] = value

        return variables

    def _retrieve_target(self) -> Target:
        """Retrieve the target from the select input.

        Returns:
            The target object corresponding to the selected value.

        Raises:
            SeretoValueError: If the target is not found.
        """
        app: SeretoApp = self.app  # type: ignore[assignment]

        target_select: Select[str] = self.select_target.query_one(Select)
        all_targets = [t for v in app.project.config.versions for t in app.project.config.at_version(v).targets]

        matching_target = [t for t in all_targets if t.uname == target_select.value]
        if len(matching_target) != 1:
            raise SeretoValueError(f"target with uname {target_select.value!r} not found")

        return matching_target[0]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Save button press event."""
        if event.button is not self.btn_save_finding:
            return

        app: SeretoApp = self.app  # type: ignore[assignment]

        # Retrieve the values from the inputs
        # - name
        name = self.input_name.value
        # - risk
        risk_select: Select[str] = self.select_risk.query_one(Select)
        risk = Risk(risk_select.value.lower()) if not isinstance(risk_select.value, NoSelection) else None
        # - target
        target = self._retrieve_target()

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
            overwrite=self.overwrite_switch.display and self.overwrite_switch.value,
        )

        # Navigate back, focus on the search input field
        self.dismiss()
        self.notify(message=name, title="Finding successfully added")
        app.action_focus_search()


class FuzzyMatcher:
    def __init__(self, query: list[str]) -> None:
        self.query = [q.lower() for q in query]

    def max_score(self, values: list[str]) -> float:
        """Calculate the average fuzzy match score between the query and the given values."""
        if not self.query:
            return 0.0

        combined = "; ".join(values).lower()
        scores: list[float] = []

        for q in self.query:
            raw_score = fuzz.partial_ratio(q, combined)
            # Bonus for matching first letter
            bonus = 5 if combined and combined[0] == q[0] else 0
            scores.append(raw_score + bonus)
        return round(sum(scores) / len(scores), 2)

    def highlight(self, text: list[str]) -> Text:
        """Highlight all fuzzy matches of the query in the given text (used in names and keywords)."""
        combined = "; ".join(text)
        combined_lower = combined.lower()
        result_text = Text(combined)

        for q in self.query:
            if q in combined_lower:
                start = 0
                while True:
                    idx = combined_lower.find(q, start)
                    if idx == -1:
                        break
                    end = idx + len(q)
                    result_text.stylize("bold yellow", idx, end)
                    start = end
            else:
                for span in Matcher(q).highlight(combined).spans:
                    span_text = combined[span.start : span.end]
                    if len(span_text) <= len(q) + 2:
                        result_text.stylize("bold yellow", span.start, span.end)

        return result_text


class SearchWidget(Widget):
    BINDINGS = [
        ("ctrl+s", "add_finding", "Add finding"),
        ("down", "cursor_down", "Next result"),
        ("up", "cursor_up", "Previous result"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.findings: list[FindingMetadata] = []
        self.filtered_findings: list[FindingMetadata] = []
        self._load_findings()

    def _load_findings(self) -> None:
        app: SeretoApp = self.app  # type: ignore[assignment]

        for category in app.categories:
            findings_path = app.project.settings.templates_path / "categories" / category.lower() / "findings"
            for finding in findings_path.glob("*.md.j2"):
                file_text = finding.read_text()
                metadata, content = frontmatter.parse(file_text)
                # Extract clean text from the template file
                env = Environment()
                ast = env.parse(content)
                extracted_text = extract_text_from_jinja(ast)

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
                        text=extracted_text,
                    )
                )

    def compose(self) -> ComposeResult:
        app: SeretoApp = self.app  # type: ignore[assignment]

        self.input_field = Input(placeholder="Type to search...", classes="input-field")
        self.category_filter = SelectionList[str](*[(category, category, True) for category in app.categories])

        class NoFocusOptionList(OptionList):
            """An OptionList subclass whose items are not focusable."""

            can_focus = False

        self.result_list = NoFocusOptionList(classes="search-result")

        with Horizontal(classes="search-panel"):
            with Vertical(), Container(classes="search-palette"):
                yield self.input_field
                yield self.result_list
            with Container(classes="category-filter"):
                yield self.category_filter

    def on_mount(self) -> None:
        self.input_field.focus()

    @on(Input.Changed)
    @on(SelectionList.SelectedChanged)
    def update_results(self) -> None:
        query = self.input_field.value.strip()
        keys = {
            "name": "n",
            "keyword": "k",
            "description": "d",
            "likelihood": "l",
            "impact": "i",
            "recommendation": "r",
        }
        parsed = parse_query(query, keys)

        self.result_list.clear_options()

        if len(query) == 0:
            return

        selected_categories = [c.lower() for c in self.category_filter.selected]
        filtered_findings = [f for f in self.findings if f.category.lower() in selected_categories]

        # reusable fuzzy matchers for scoring and highlighting
        self.matcher_dict = {key: FuzzyMatcher(parsed[key]) for key in keys if parsed[key]}
        if not self.matcher_dict:
            return

        # compute search similarity
        for f in filtered_findings:
            scores: list[float] = []

            for key, _ in self.matcher_dict.items():
                matcher = self.matcher_dict[key]

                if key == "name":
                    name_score = matcher.max_score([f.name]) or 0
                    scores.append(name_score)
                elif key == "keyword":
                    name_score = matcher.max_score(f.keywords) or 0
                    scores.append(name_score)
                else:
                    if key in f.text:
                        name_score = matcher.max_score([f.text[key]]) or 0
                        scores.append(name_score)

            f.search_similarity = sum(scores) / len(scores) if scores else 0.0

        # display matching findings
        result_item = [
            f
            for f in sorted(
                filtered_findings,
                key=lambda f: f.search_similarity,
                reverse=True,
            )
            if f.search_similarity > 80.0
        ]

        options: list[FindingOption | None] = []
        for f in result_item:
            options.append(FindingOption(f, self.matcher_dict))
            options.append(None)  # insert a separator line

        self.result_list.clear_options()
        self.result_list.add_options(options)

        # highlight the first search result
        if options:
            self.result_list.highlighted = 0
            self.result_list.scroll_to_highlight()

    def on_key(self, event: events.Key) -> None:
        """Intercepts key presses and handles the Enter key."""
        if event.key == "enter":
            if self.category_filter.has_focus:
                return

            if self.input_field.has_focus:
                self.action_select_item()
            return

    # up/down scrolling without focusing the OptionList
    def action_cursor_down(self) -> None:
        if not self.result_list.options:
            return

        if self.result_list.highlighted is None:
            self.result_list.highlighted = 0
        else:
            if self.result_list.highlighted < len(self.result_list.options) - 1:
                self.result_list.highlighted += 1
        self.result_list.scroll_to_highlight(top=True)

    def action_cursor_up(self) -> None:
        if not self.result_list.options:
            return

        if self.result_list.highlighted is None:
            self.result_list.highlighted = 0
        else:
            if self.result_list.highlighted > 0:
                self.result_list.highlighted -= 1
        self.result_list.scroll_to_highlight(top=True)

    def assemble_template(self, file: str) -> str | Text:
        """Highlight matching words in specific Jinja blocks and returns reconstructed template."""
        code = Text(file)
        found_match = False

        for key in ("likelihood", "description", "impact", "recommendation"):
            matcher = self.matcher_dict.get(key)
            if not matcher:
                continue
            # extract the full content of the block
            block_text, start, end = extract_block_from_jinja(file, key)
            highlighted_block = matcher.highlight([block_text])
            if highlighted_block.spans:
                found_match = True
                # reassemble template
                code = code[:start] + highlighted_block + code[end:]

        final_code = code if found_match else file
        return final_code

    @on(OptionList.OptionSelected)
    def select_item(self, event: OptionList.OptionSelected) -> None:
        option = event.option
        if not isinstance(option, FindingOption):
            return
        file = option.finding.path.read_text()
        final_code = self.assemble_template(file)

        self.app.push_screen(
            FindingPreviewScreen(
                title="Finding preview",
                code=final_code,
            )
        )

    def action_select_item(self) -> None:
        if self.result_list.highlighted is None:
            return

        option = self.result_list.get_option_at_index(self.result_list.highlighted)
        if not isinstance(option, FindingOption):
            return
        file = option.finding.path.read_text()
        final_code = self.assemble_template(file)
        self.app.push_screen(
            FindingPreviewScreen(
                title="Finding preview",
                code=final_code,
            )
        )

    def action_add_finding(self) -> None:
        if not self.input_field.has_focus:
            return

        if self.result_list.highlighted is None:
            return
        option = self.result_list.get_option_at_index(self.result_list.highlighted)
        if isinstance(option, FindingOption):
            self.app.push_screen(
                AddFindingScreen(
                    templates=self.app.project.settings.templates_path,  # type: ignore[attr-defined]
                    finding=option.finding,
                    title="Add finding",
                )
            )


class FindingOption(Option):
    """An Option representing a finding, with name and keywords optionally highlighted."""

    def __init__(self, finding: FindingMetadata, matchers: dict[str, FuzzyMatcher]) -> None:
        name_matcher = matchers.get("name")
        keyword_matcher = matchers.get("keyword")

        name_text = name_matcher.highlight([finding.name]) if name_matcher else Text(finding.name)

        keywords_text = (
            keyword_matcher.highlight(finding.keywords) if keyword_matcher else Text(", ".join(finding.keywords))
        )

        text = Text.assemble(name_text + "\n", Text(style="italic dim") + keywords_text)
        super().__init__(text, id=str(finding.path))
        self.finding = finding


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

        search = SearchWidget()
        search.id = "search"
        search.classes = "dropdown"

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
