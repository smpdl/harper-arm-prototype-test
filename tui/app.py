"""Main Textual application for hardware test suites."""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

from textual.app import App
from textual.binding import Binding

from tui.core.paths import RunPaths
from tui.screens.home import HomeScreen


class HarperApp(App[None]):
    TITLE = "Harper Arm Prototype Test"
    CSS_PATH = "styles/app.tcss"

    BINDINGS: ClassVar[Sequence[Binding]] = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.paths = RunPaths()

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())


__all__ = ["HarperApp"]
