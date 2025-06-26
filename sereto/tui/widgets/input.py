from collections.abc import Callable, Iterable
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


W = TypeVar("W", bound=Widget)


class RemovableWidget(Generic[W], Widget):
    """A removable widget (e.g., Input, Select) with a remove button."""

    def __init__(self, widget: W, on_remove: Callable[["RemovableWidget[W]"], None] | None = None) -> None:
        super().__init__()
        self.widget = widget
        self.widget.add_class("widget")
        self.on_remove = on_remove

    def compose(self) -> ComposeResult:
        with Horizontal(classes="m-1"):
            yield self.widget
            self.remove_button = Button("Remove")
            yield self.remove_button

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is self.remove_button:
            if self.on_remove:
                self.on_remove(self)
            else:
                self.remove()


class ListWidget(Generic[W], Widget):
    """A list of widgets (e.g., Input, Select) with add and remove buttons."""

    def __init__(
        self,
        widget_factory: Callable[[], W],
        add_button_label: str = "Add item",
        id: str | None = None,
    ):
        """
        Args:
            widget_factory: Callable that returns a new widget instance (e.g., Input, Select).
            add_button_label: Label for the add button.
            id: Optional widget id.
        """
        super().__init__(id=id)
        self.widget_factory = widget_factory
        self.add_button_label = add_button_label

    def compose(self) -> ComposeResult:
        self.widget_list = Vertical(classes="widget-list")
        yield self.widget_list
        self.btn_add_list_item = Button(self.add_button_label, classes="hover-bg-accent")
        yield self.btn_add_list_item

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is self.btn_add_list_item:
            new_widget = self.widget_factory()
            new_row = RemovableWidget(widget=new_widget, on_remove=self._remove_row)
            self.widget_list.mount(new_row)

    def _remove_row(self, row: RemovableWidget[W]) -> None:
        row.remove()


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
