"""Initial launcher screen for calibration or test catalogue."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from tui.screens._helpers import app_paths
from tui.screens.suites.calibration import CalibrationScreen
from tui.screens.suites.tests import TestsRunnerScreen


class HomeScreen(Screen[None]):
    DEFAULT_CSS = """
    HomeScreen {
        align: center middle;
    }

    #home-panel {
        width: 52;
        height: auto;
        align: center middle;
    }

    #home-title {
        text-style: bold;
        text-align: center;
        margin-bottom: 2;
    }

    #home-actions {
        width: 100%;
        height: auto;
        align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="home-panel"):
            yield Static("Harper Arm Prototype Test", id="home-title")
            with Vertical(id="home-actions"):
                yield Button("Calibration", classes="btn-black", id="open-calibration")
                yield Button("Tests", classes="btn-black", id="open-tests")
        yield Footer()

    @on(Button.Pressed, "#open-calibration")
    def open_calibration(self) -> None:
        self.app.push_screen(CalibrationScreen(app_paths(self)))

    @on(Button.Pressed, "#open-tests")
    def open_tests(self) -> None:
        self.app.push_screen(TestsRunnerScreen(app_paths(self)))
