"""Settings modal for the test runner TUI."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from tui.core.paths import RunPaths


class SettingsScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    SettingsScreen {
        align: center middle;
    }

    #settings-dialog {
        width: 72;
        height: auto;
        max-height: 80%;
        padding: 1 2;
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
            yield Label("E2E motion config")
            yield Input(str(self._paths.e2e_config_path), id="e2e-config-path")
            yield Label("Results root")
            yield Input(str(self._paths.results_root), id="results-root")
            with Horizontal(id="settings-actions"):
                yield Button("Cancel", classes="btn-black", id="cancel")
                yield Button("Save", classes="btn-run", id="save")

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        self._paths.config_path = Path(self.query_one("#config-path", Input).value.strip())
        self._paths.e2e_config_path = Path(
            self.query_one("#e2e-config-path", Input).value.strip()
        )
        self._paths.results_root = Path(self.query_one("#results-root", Input).value.strip())
        self.dismiss(True)
