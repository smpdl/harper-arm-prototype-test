"""Settings modal for the test runner TUI."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from tui.runner import RunPaths


class SettingsScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    SettingsScreen {
        align: center middle;
    }

    #settings-dialog {
        width: 72;
        height: auto;
        max-height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }

    #settings-dialog Input {
        margin-bottom: 1;
    }

    #settings-actions {
        height: auto;
        margin-top: 1;
        align: right middle;
    }
    """

    def __init__(self, paths: RunPaths) -> None:
        super().__init__()
        self._paths = paths

    def compose(self) -> ComposeResult:
        with Container(id="settings-dialog"):
            yield Label("Paths", id="settings-title")
            yield Label("Arm config")
            yield Input(str(self._paths.config_path), id="config-path")
            yield Label("Motions config")
            yield Input(str(self._paths.motions_path), id="motions-path")
            yield Label("Results root")
            yield Input(str(self._paths.results_root), id="results-root")
            with Horizontal(id="settings-actions"):
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Save", variant="primary", id="save")

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        self._paths.config_path = Path(self.query_one("#config-path", Input).value)
        self._paths.motions_path = Path(self.query_one("#motions-path", Input).value)
        self._paths.results_root = Path(self.query_one("#results-root", Input).value)
        self.dismiss(True)
