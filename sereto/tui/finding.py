import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import frontmatter  # type: ignore
from jinja2 import Environment
from pydantic import DirectoryPath, ValidationError
from rich.markup import escape
from rich.syntax import Syntax
from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
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
from sereto.project import Project
from sereto.target import Target
from sereto.tui.search import (
    FINDING_SEARCH_FIELDS,
    FuzzyMatcher,
    ParsedSearchQuery,
    SearchDocument,
    SearchResult,
    build_matchers,
    parse_search_query,
    rank_documents,
    should_display_result,
    summarize_query,
    supported_operator_text,
)
from sereto.tui.widgets.input import InputWithLabel, ListWidget, SelectWithLabel

_NEW_GROUP_SENTINEL = "__new_group__"
_GROUP_HINT_SENTINEL = "__group_hint__"


@dataclass
class FindingMetadata:
    path: Path
    category: str
    name: str
    risk: Risk
    variables: list[VarsMetadataModel]
    keywords: list[str]
    group_hint: str | None
    text: dict[str, str]


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
        ("ctrl+s", "add_sub_finding", "Add sub-finding"),
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
        code_widget.border_subtitle = "^s to add sub-finding; Esc to close"

    def action_add_sub_finding(self) -> None:
        self.dismiss()
        app: SeretoApp = self.app  # type: ignore[assignment]
        app.query_one("#search", SearchWidget).action_add_sub_finding()


class AddSubFindingScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss", "Dismiss finding")]

    def __init__(self, templates: DirectoryPath, finding: FindingMetadata, title: str) -> None:
        super().__init__()
        self.templates = templates
        self.finding = finding
        self.title = title

    def compose(self) -> ComposeResult:
        app: SeretoApp = self.app  # type: ignore[assignment]
        all_targets = [t for v in app.project.config.versions for t in app.project.config.at_version(v).targets]

        with ScrollableContainer(id="add-sub-finding"):
            # Name
            self.input_name = Input(value=self.finding.name)
            yield InputWithLabel(self.input_name, label="Name")
            # Risk
            risks = [r.capitalize() for r in Risk]
            self.select_risk = SelectWithLabel[str](
                options=[(r, r) for r in risks], label="Risk", value=self.finding.risk.capitalize()
            )
            yield self.select_risk
            # Target
            self.select_target = SelectWithLabel[str](
                options=[(t.uname, t.uname) for t in all_targets],
                label="Target",
                allow_blank=False,
            )
            yield self.select_target
            # Finding Group
            initial_groups: list[tuple[str, str]] = []
            if all_targets:
                initial_groups = [(g.name, g.uname) for g in all_targets[0].findings.groups]
            self.select_group = SelectWithLabel[str](
                options=self._build_group_options(initial_groups, self.finding.group_hint),
                label="Group",
                allow_blank=False,
            )
            yield self.select_group
            # New group name input (shown when "Create new group" is selected)
            self.input_group_name = Input(value=self.finding.group_hint or self.finding.name, id="input-group-name")
            self.group_name_container = InputWithLabel(self.input_group_name, label="Group name")
            yield self.group_name_container
            # Store group unames for mapping select value -> uname
            self._group_unames: list[str] = [g_uname for _g_name, g_uname in initial_groups]
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

            self.btn_save_sub_finding = Button.success("Save", id="save-sub-finding", classes="m-1")
            yield self.btn_save_sub_finding

    def on_mount(self) -> None:
        add_sub_finding = self.query_one("#add-sub-finding")
        add_sub_finding.border_title = self.title
        add_sub_finding.border_subtitle = "Esc to close"

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select is self.select_target.query_one(Select):
            try:
                target = self._retrieve_target()
            except Exception:
                self._rebuild_group_options([])
                self.update_overwrite_warning()
                return

            groups = target.findings.groups
            self._rebuild_group_options([(g.name, g.uname) for g in groups])
            self.update_overwrite_warning()

        if event.select is self.select_group.query_one(Select):
            is_new_group = event.value == _NEW_GROUP_SENTINEL
            # show group name input only for explicit "Create new group"
            self.group_name_container.display = is_new_group
            if is_new_group:
                self.input_group_name.focus()

    @staticmethod
    def _build_group_options(
        groups: list[tuple[str, str]],
        group_hint: str | None = None,
    ) -> list[tuple[str, str]]:
        """Build options list for the group Select with 'Create new group' first."""
        options: list[tuple[str, str]] = [("\u2795 Create new group", _NEW_GROUP_SENTINEL)]
        if group_hint:
            options.append((f"\U0001f4a1 Suggested: {group_hint}", _GROUP_HINT_SENTINEL))
        options.extend((g_name, g_uname) for g_name, g_uname in groups)
        return options

    def _rebuild_group_options(self, groups: list[tuple[str, str]]) -> None:
        """Rebuild the group Select options."""
        group_select = cast(Select[str], self.select_group.query_one(Select))
        group_select.set_options(self._build_group_options(groups, self.finding.group_hint))
        self._group_unames = [g_uname for _, g_uname in groups]
        # Default to hint sentinel when a hint is present, otherwise "Create new group"
        if self.finding.group_hint:
            group_select.value = _GROUP_HINT_SENTINEL
            self.group_name_container.display = False
        else:
            group_select.value = _NEW_GROUP_SENTINEL
            self.group_name_container.display = True

    def _resolve_group_hint(self, target: Target) -> str | None:
        """Resolve the group hint to an existing group's uname.

        Args:
            target: The target to search for a matching group.

        Returns:
            The uname of the matching group, or None if no match is found.
        """
        hint = (self.finding.group_hint or "").strip()
        if not hint:
            return None
        group = target.findings.find_group_by_hint(hint)
        return group.uname if group is not None else None

    def update_overwrite_warning(self) -> None:
        """Update the overwrite warning and switch dynamically."""
        try:
            target = self._retrieve_target()
        except SeretoValueError:
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
                values: list[bool] | list[int] | list[str]

                match var.type:
                    case "boolean":
                        # get values, filter out NoSelection
                        bool_values: list[bool] = []
                        for widget in widgets:
                            if not isinstance(widget, Select):
                                continue
                            select_widget = cast(Select[bool], widget)
                            if isinstance(select_widget.value, NoSelection):
                                continue
                            bool_values.append(select_widget.value)
                        values = bool_values
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
                        value_select = cast(Select[bool], self.query_one(f"#var-{var.name}", Select))
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

        target_select = cast(Select[str], self.select_target.query_one(Select))
        all_targets = [t for v in app.project.config.versions for t in app.project.config.at_version(v).targets]

        matching_target = [t for t in all_targets if t.uname == target_select.value]
        if len(matching_target) != 1:
            raise SeretoValueError(f"target with uname {target_select.value!r} not found")

        return matching_target[0]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Save button press event."""
        if event.button is not self.btn_save_sub_finding:
            return

        app: SeretoApp = self.app  # type: ignore[assignment]

        # Retrieve the values from the inputs
        # - name
        sub_finding_name = self.input_name.value
        # - risk
        risk_select = cast(Select[str], self.select_risk.query_one(Select))
        risk = Risk(risk_select.value.lower()) if not isinstance(risk_select.value, NoSelection) else None
        # - target
        target = self._retrieve_target()
        # - Finding Group
        selected_group: str | None = None
        group_name: str | None = None
        group_select = cast(Select[str], self.select_group.query_one(Select))
        if not isinstance(group_select.value, NoSelection) and group_select.value == _NEW_GROUP_SENTINEL:
            # "Create new group" selected
            group_name = self.input_group_name.value.strip() or None
        elif not isinstance(group_select.value, NoSelection) and group_select.value == _GROUP_HINT_SENTINEL:
            # "Suggested" selected: append to existing group when possible; otherwise create it
            resolved_uname = self._resolve_group_hint(target)
            if resolved_uname is not None:
                selected_group = resolved_uname
            else:
                group_name = (self.finding.group_hint or "").strip() or None
        elif not isinstance(group_select.value, NoSelection):
            # Existing group selected
            selected_group = group_select.value

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
            sub_finding_name=sub_finding_name,
            risk=risk,
            variables=variables,
            overwrite=self.overwrite_switch.display and self.overwrite_switch.value,
            group_uname=selected_group,
            group_name=group_name,
        )

        # Navigate back, focus on the search input field
        self.dismiss()
        self.notify(message=sub_finding_name, title="Sub-finding successfully added")
        app.action_focus_search()


class SearchWidget(Widget):
    BINDINGS = [
        ("ctrl+s", "add_sub_finding", "Add sub-finding"),
        ("down", "cursor_down", "Next result"),
        ("up", "cursor_up", "Previous result"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.findings: list[FindingMetadata] = []
        self.documents: list[SearchDocument[FindingMetadata]] = []
        self.current_results: list[SearchResult[FindingMetadata]] = []
        self.current_query = ParsedSearchQuery(raw="")
        self.matchers: dict[str, FuzzyMatcher] = {}
        self._load_findings()

    def _load_findings(self) -> None:
        app: SeretoApp = self.app  # type: ignore[assignment]

        for category in app.categories:
            findings_path = app.project.settings.templates_path / "categories" / category.lower() / "findings"
            for finding in findings_path.glob("*.md.j2"):
                file_text = finding.read_text(encoding="utf-8")
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
                        risk=data.risk,
                        variables=data.variables,
                        keywords=data.keywords,
                        group_hint=data.group_hint,
                        text=extracted_text,
                    )
                )
                self.documents.append(
                    SearchDocument(
                        payload=self.findings[-1],
                        fields=self._build_document_fields(self.findings[-1]),
                    )
                )

    @staticmethod
    def _build_document_fields(finding: FindingMetadata) -> dict[str, list[str]]:
        fields: dict[str, list[str]] = {
            "name": [finding.name],
            "keyword": finding.keywords,
        }
        for field in FINDING_SEARCH_FIELDS.previewable_fields():
            value = finding.text.get(field.name, "").strip()
            if value:
                fields[field.name] = [value]
        return fields

    def compose(self) -> ComposeResult:
        app: SeretoApp = self.app  # type: ignore[assignment]

        self.input_field = Input(
            placeholder='Search by name or keyword. Try impact:rce or description:"sql injection".',
            classes="input-field",
        )
        self.query_summary = Static(classes="query-summary")
        self.search_hint = Static(classes="search-hint")
        self.result_meta = Static(classes="result-meta")
        self.category_filter = SelectionList[str](*[(category, category, True) for category in app.categories])

        class NoFocusOptionList(OptionList):
            """An OptionList subclass whose items are not focusable."""

            can_focus = False

        self.result_list = NoFocusOptionList(classes="search-result")

        with Horizontal(classes="search-panel"):
            with Vertical(), Container(classes="search-palette"):
                yield self.input_field
                yield self.query_summary
                yield self.search_hint
                yield self.result_meta
                yield self.result_list
            with Container(classes="category-filter"):
                yield self.category_filter

    def on_mount(self) -> None:
        self.input_field.focus()
        self.query_summary.update(summarize_query(self.current_query, FINDING_SEARCH_FIELDS))
        self.search_hint.update(supported_operator_text(FINDING_SEARCH_FIELDS))
        self.result_meta.update(Text(f"Loaded {len(self.findings)} finding templates.", style="dim"))

    @on(Input.Changed)
    @on(SelectionList.SelectedChanged)
    def update_results(self) -> None:
        query = self.input_field.value
        self.current_query = parse_search_query(query, FINDING_SEARCH_FIELDS)
        self.matchers = build_matchers(self.current_query, FINDING_SEARCH_FIELDS)
        self.query_summary.update(summarize_query(self.current_query, FINDING_SEARCH_FIELDS))

        self.result_list.clear_options()
        self.current_results = []

        if not query.strip():
            self.result_meta.update(Text(f"Loaded {len(self.findings)} finding templates.", style="dim"))
            return

        selected_categories = [c.lower() for c in self.category_filter.selected]
        filtered_documents = [
            document for document in self.documents if document.payload.category.lower() in selected_categories
        ]
        self.current_results = rank_documents(filtered_documents, self.current_query, FINDING_SEARCH_FIELDS)

        if not self.current_results:
            self.result_meta.update(
                Text("No matches. Try fewer terms or use one of the operators below.", style="yellow")
            )
            return

        options: list[FindingOption | None] = []
        visible_results = [result for result in self.current_results if should_display_result(result.score)]
        for index, result in enumerate(visible_results):
            options.append(FindingOption(result, self.matchers))
            if index < len(visible_results) - 1:
                options.append(None)

        self.result_list.clear_options()
        self.result_list.add_options(options)
        self.result_meta.update(
            Text(f"{len(visible_results)} matches across {len(selected_categories)} categories.", style="dim")
        )

        # highlight the first search result
        if options:
            first_index = self._find_selectable_index(0, 1)
            if first_index is not None:
                self.result_list.highlighted = first_index
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
            next_index = self._find_selectable_index(0, 1)
        else:
            next_index = self._find_selectable_index(self.result_list.highlighted + 1, 1)

        if next_index is not None:
            self.result_list.highlighted = next_index
            self.result_list.scroll_to_highlight(top=True)

    def action_cursor_up(self) -> None:
        if not self.result_list.options:
            return

        if self.result_list.highlighted is None:
            next_index = self._find_selectable_index(len(self.result_list.options) - 1, -1)
        else:
            next_index = self._find_selectable_index(self.result_list.highlighted - 1, -1)

        if next_index is not None:
            self.result_list.highlighted = next_index
            self.result_list.scroll_to_highlight(top=True)

    def _find_selectable_index(self, start: int, direction: int) -> int | None:
        if direction not in {-1, 1}:
            raise ValueError("direction must be -1 or 1")

        index = start
        while 0 <= index < len(self.result_list.options):
            option = self.result_list.get_option_at_index(index)
            if isinstance(option, FindingOption):
                return index
            index += direction
        return None

    def assemble_template(self, file: str) -> str | Text:
        """Highlight matching words in specific Jinja blocks and returns reconstructed template."""
        code = Text(file)
        found_match = False

        for field in FINDING_SEARCH_FIELDS.previewable_fields():
            matcher = self.matchers.get(field.name)
            if not matcher:
                continue
            # extract the full content of the block
            block_text, start, end = extract_block_from_jinja(file, field.name)
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
        file = option.result.document.payload.path.read_text(encoding="utf-8")
        final_code = self.assemble_template(file)

        app: SeretoApp = self.app  # type: ignore[assignment]
        app.push_screen(
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
        file = option.result.document.payload.path.read_text(encoding="utf-8")
        final_code = self.assemble_template(file)
        app: SeretoApp = self.app  # type: ignore[assignment]
        app.push_screen(
            FindingPreviewScreen(
                title="Finding preview",
                code=final_code,
            )
        )

    def action_add_sub_finding(self) -> None:
        if not self.input_field.has_focus:
            return

        if self.result_list.highlighted is None:
            return
        option = self.result_list.get_option_at_index(self.result_list.highlighted)
        if isinstance(option, FindingOption):
            app: SeretoApp = self.app  # type: ignore[assignment]
            app.push_screen(
                AddSubFindingScreen(
                    templates=app.project.settings.templates_path,
                    finding=option.result.document.payload,
                    title="Add sub-finding",
                )
            )


class FindingOption(Option):
    """An Option representing a finding, with name and keywords optionally highlighted."""

    def __init__(self, result: SearchResult[FindingMetadata], matchers: dict[str, FuzzyMatcher]) -> None:
        finding = result.document.payload
        name_matcher = matchers.get("name")
        keyword_matcher = matchers.get("keyword")

        name_text = name_matcher.highlight([finding.name]) if name_matcher else Text(finding.name)
        name_text.stylize("bold")

        support_text = Text(finding.category, style="bold cyan")
        keyword_preview = self._build_keyword_preview(finding.keywords, keyword_matcher)
        match_hint = self._build_match_hint(result)

        if keyword_preview is not None:
            support_text.append("  |  ", style="dim")
            support_text.append_text(keyword_preview)
        elif match_hint is not None:
            support_text.append("  |  ", style="dim")
            support_text.append_text(match_hint)

        text = Text.assemble(
            name_text + "\n",
            support_text,
        )
        super().__init__(text, id=str(finding.path))
        self.result = result

    @staticmethod
    def _build_keyword_preview(keywords: list[str], matcher: FuzzyMatcher | None) -> Text | None:
        if not keywords:
            return None

        preview_keywords = keywords[:3]
        preview = matcher.highlight(preview_keywords) if matcher else Text(", ".join(preview_keywords))
        preview.stylize("italic dim")
        if len(keywords) > len(preview_keywords):
            preview.append(", ...", style="italic dim")
        return preview

    @staticmethod
    def _build_match_hint(result: SearchResult[FindingMetadata]) -> Text | None:
        reason = next((reason for reason in result.reasons if reason.field_name not in {"name", "keyword"}), None)
        if reason is None:
            return None
        return Text(f"{reason.label.lower()} match", style="italic dim")


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
