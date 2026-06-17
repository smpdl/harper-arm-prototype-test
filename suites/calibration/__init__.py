"""Operator-supervised arm calibration tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from harper_arm.joint import DEFAULT_CONFIG_PATH
from tui.catalog import CALIBRATION_TEST_NAMES as ALL_TESTS

from . import backdriveable, non_backdriveable, validate
from .helpers import DEFAULT_RESULTS_ROOT

RunFn = Callable[..., Path]

CALIBRATION_TESTS: dict[str, RunFn] = {
    "non_backdriveable": non_backdriveable.run,
    "backdriveable": backdriveable.run,
    "validate": validate.run,
}


def run(
    test: str,
    *,
    joint: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    calibration_path: Path | str = Path("config/calibration.yaml"),
    results_root: Path = DEFAULT_RESULTS_ROOT,
    **kwargs: object,
) -> Path:
    try:
        runner = CALIBRATION_TESTS[test]
    except KeyError as exc:
        known = ", ".join(ALL_TESTS)
        raise ValueError(f"unknown calibration test {test!r}; known: {known}") from exc
    return runner(
        joint=joint,
        config_path=config_path,
        calibration_path=calibration_path,
        results_root=results_root,
        **kwargs,
    )
