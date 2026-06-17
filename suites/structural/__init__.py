"""Multi-joint structural hardware tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from harper_arm.joint import DEFAULT_CONFIG_PATH
from tui.catalog import STRUCTURAL_TEST_NAMES as ALL_TESTS

from . import max_payload, point_load, self_weight_hold
from .helpers import DEFAULT_RESULTS_ROOT

RunFn = Callable[..., Path]

STRUCTURAL_TESTS: dict[str, RunFn] = {
    "self_weight_hold": self_weight_hold.run,
    "point_load": point_load.run,
    "max_payload": max_payload.run,
}


def run(
    test: str,
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    **kwargs: object,
) -> Path:
    try:
        runner = STRUCTURAL_TESTS[test]
    except KeyError as exc:
        known = ", ".join(ALL_TESTS)
        raise ValueError(f"unknown structural test {test!r}; known: {known}") from exc
    return runner(
        config_path=config_path,
        results_root=results_root,
        **kwargs,
    )
