"""Modal confirmation before structural pose approach moves."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class PoseConfirmScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    PoseConfirmScreen {
        align: center middle;
    }

    #pose-confirm-dialog {
        width: 72;
        height: auto;
        max-height: 80%;
        padding: 1 2;
    }

    #pose-confirm-preview {
        height: auto;
        max-height: 16;
        margin: 1 0;
    }
    """

    def __init__(self, *, pose: str, preview_lines: list[str]) -> None:
        super().__init__()
        self._pose = pose
        self._preview_lines = preview_lines

    def compose(self) -> ComposeResult:
        with Container(id="pose-confirm-dialog"):
            yield Label(f"Confirm approach to {self._pose!r}")
            yield Static(
                "Review targets below. The arm will move when you confirm.",
                id="pose-confirm-help",
            )
            with VerticalScroll(id="pose-confirm-preview"):
                yield Static("\n".join(self._preview_lines), id="pose-confirm-lines")
            with Horizontal(id="pose-confirm-actions"):
                yield Button("Cancel", classes="btn-black", id="pose-confirm-cancel")
                yield Button("Move", classes="btn-run", id="pose-confirm-ok")

    @on(Button.Pressed, "#pose-confirm-cancel")
    def cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#pose-confirm-ok")
    def confirm(self) -> None:
        self.dismiss(True)
