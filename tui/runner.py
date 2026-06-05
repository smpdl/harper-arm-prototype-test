"""Dispatch hardware test suites."""

from __future__ import annotations

import sys
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.status import MotorStatus
from tui.suite_catalog import INTERACTIVE_STRUCTURAL_TESTS, TestSpec

DEFAULT_MOTIONS_PATH = Path("config/motions.yaml")
DEFAULT_RESULTS_ROOT = Path("results")
REPO_ROOT = Path(__file__).resolve().parents[1]


def ensure_repo_on_path() -> Path:
    """Make repo-root ``suites/`` importable. Call once at process startup."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    return REPO_ROOT


@dataclass
class RunPaths:
    config_path: Path = DEFAULT_CONFIG_PATH
    motions_path: Path = DEFAULT_MOTIONS_PATH
    results_root: Path = DEFAULT_RESULTS_ROOT


class _StreamToCallback:
    def __init__(self, write: Callable[[str], None]) -> None:
        self._write = write
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._write(line)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self._write(self._buffer)
            self._buffer = ""


@contextmanager
def _capture_stdio(log_line: Callable[[str], None] | None):
    if log_line is None:
        yield
        return

    writer = _StreamToCallback(log_line)
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = writer
    sys.stderr = writer
    try:
        yield
    finally:
        writer.flush()
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def run_test(
    spec: TestSpec,
    paths: RunPaths,
    *,
    log_line: Callable[[str], None] | None = None,
    on_motor_status: Callable[[MotorStatus], None] | None = None,
    **kwargs: object,
) -> Path:
    """Run one catalog test and return the results directory."""
    ensure_repo_on_path()

    if (
        spec.suite == "structural"
        and spec.name in INTERACTIVE_STRUCTURAL_TESTS
        and kwargs.get("interactive") is False
    ):
        raise ValueError(
            f"{spec.name} requires interactive=True for operator prompts and load application. "
            "Enable Interactive prompts or call run(interactive=True) from a terminal."
        )

    with _capture_stdio(log_line):
        if spec.suite == "motor":
            import suites.motor as motor_suite

            return motor_suite.run(  # type: ignore[arg-type]
                spec.name,
                config_path=paths.config_path,
                results_root=paths.results_root,
                on_status=on_motor_status,
                **kwargs,
            )

        import suites.structural as structural_suite

        return structural_suite.run(  # type: ignore[arg-type]
            spec.name,
            config_path=paths.config_path,
            motions_path=paths.motions_path,
            results_root=paths.results_root,
            **kwargs,
        )
