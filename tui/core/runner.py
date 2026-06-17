"""Dispatch hardware test suites from the TUI."""

from __future__ import annotations

import sys
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from harper_arm.status import MotorStatus
from tui.catalog import TestSpec
from tui.core.paths import REPO_ROOT, RunPaths


def ensure_repo_on_path() -> Path:
    """Make repo-root ``suites/`` importable. Call once at process startup."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    return REPO_ROOT


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

        if spec.suite == "structural":
            import suites.structural as structural_suite

            return structural_suite.run(  # type: ignore[arg-type]
                spec.name,
                config_path=paths.config_path,
                e2e_config_path=paths.e2e_config_path,
                results_root=paths.results_root,
                **kwargs,
            )

        if spec.suite == "e2e":
            import suites.e2e as e2e_suite

            return e2e_suite.run(
                spec.name,
                config_path=paths.config_path,
                e2e_config_path=paths.e2e_config_path,
                results_root=paths.results_root,
                **kwargs,
            )

        import suites.calibration as calibration_suite

        return calibration_suite.run(  # type: ignore[arg-type]
            spec.name,
            config_path=paths.config_path,
            results_root=paths.results_root,
            **kwargs,
        )
