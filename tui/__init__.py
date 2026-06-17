"""Textual TUI for hardware test suites."""

from __future__ import annotations

import warnings

warnings.filterwarnings(
    "ignore",
    message="pkg_resources is deprecated as an API.*",
    category=UserWarning,
)

from tui.app import HarperApp
from tui.core import RunPaths, ensure_repo_on_path, run_test
from tui.screens import (
    CalibrationScreen,
    E2ERunnerScreen,
    HomeScreen,
    MotorRunnerScreen,
    StructuralRunnerScreen,
    StructuralTestsScreen,
    SuiteRunnerScreen,
    TestsRunnerScreen,
)


def run_tui() -> None:
    HarperApp().run()


def main() -> None:
    ensure_repo_on_path()
    run_tui()


__all__ = [
    "CalibrationScreen",
    "E2ERunnerScreen",
    "HarperApp",
    "HomeScreen",
    "MotorRunnerScreen",
    "RunPaths",
    "StructuralRunnerScreen",
    "StructuralTestsScreen",
    "SuiteRunnerScreen",
    "TestsRunnerScreen",
    "ensure_repo_on_path",
    "main",
    "run_test",
    "run_tui",
]
