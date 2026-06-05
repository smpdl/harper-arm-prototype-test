"""Textual TUI for hardware test suites."""

from tui.app import TestRunnerApp


def run_tui() -> None:
    TestRunnerApp().run()


def main() -> None:
    from tui.runner import ensure_repo_on_path

    ensure_repo_on_path()
    run_tui()


__all__ = ["TestRunnerApp", "main", "run_tui"]
