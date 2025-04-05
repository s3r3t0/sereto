from collections.abc import Iterable
from typing import Generic, TypeVar

from rich.console import RenderableType
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select


class InputWithLabel(Widget):
    """An input with a label."""

    DEFAULT_CSS = """
    InputWithLabel {
        layout: horizontal;
        height: auto;
        & > Label {
            padding: 1;
            width: 12;
            text-align: right;
        }
        & > Input {
            width: 1fr;
        }
    }
    """

    def __init__(self, input: Input, label: str) -> None:
        """Initialize the widget from provided Input and label"""
        super().__init__()
        self.input = input
        self.label = label

    def compose(self) -> ComposeResult:
        yield Label(self.label)
        yield self.input


class RemovableInput(Widget):
    """A removable input with a remove button."""

    DEFAULT_CSS = """
    RemovableInput {
        height: 5;
        & > Horizontal {
            & > Input {width: 1fr;}
            & > Button {width: auto;}
        }
    }
    """

    def __init__(self, input: Input) -> None:
        super().__init__()
        self.input = input

    def compose(self) -> ComposeResult:
        with Horizontal(classes="m-1"):
            yield self.input
            self.remove_button = Button("Remove")
            yield self.remove_button

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is self.remove_button:
            self.remove()


class ListInput(Widget):
    """A list of inputs with add and remove buttons."""

    DEFAULT_CSS = """
    ListInput {
        height: 5;
        margin: 1;
        min-width: 50;
        padding: 1;
        & > Vertical.input-list {
            background: $boost;
            height: auto;
        }
    }
    """

    def __init__(self, id: str | None = None):
        super().__init__(id=id)
        # self.input_values: list[Input] = []

    def compose(self) -> ComposeResult:
        self.input_list = Vertical(classes="input-list")
        yield self.input_list
        self.btn_add_list_item = Button("Add item", classes="hover-bg-accent")
        yield self.btn_add_list_item

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is self.btn_add_list_item:
            new_input = Input()
            # self.input_values.append(new_input)
            new_row = RemovableInput(input=new_input)
            self.input_list.mount(new_row)


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
