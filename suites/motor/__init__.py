"""Per-joint motor hardware tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.status import MotorStatus
from tui.catalog import MOTOR_TEST_NAMES as ALL_TESTS

from . import (
    current_no_load,
    ping,
    position_accuracy,
    power_on_response,
    present_temperature,
    present_voltage,
)
from .helpers import DEFAULT_RESULTS_ROOT

RunFn = Callable[..., Path]

MOTOR_TESTS: dict[str, RunFn] = {
    "ping": ping.run,
    "present_voltage": present_voltage.run,
    "present_temperature": present_temperature.run,
    "current_no_load": current_no_load.run,
    "power_on_response": power_on_response.run,
    "position_accuracy": position_accuracy.run,
}

def run(
    test: str,
    *,
    joint: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    on_status: Callable[[MotorStatus], None] | None = None,
    **kwargs: object,
) -> Path:
    try:
        runner = MOTOR_TESTS[test]
    except KeyError as exc:
        known = ", ".join(ALL_TESTS)
        raise ValueError(f"unknown motor test {test!r}; known: {known}") from exc
    return runner(
        joint=joint,
        config_path=config_path,
        results_root=results_root,
        on_status=on_status,
        **kwargs,
    )
