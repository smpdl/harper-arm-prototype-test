"""Shared helpers for motor suite run() functions."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harper_arm.config import JointConfig
from harper_arm.joint import DEFAULT_CONFIG_PATH, Joint
from harper_arm.logging import TestRun
from harper_arm.sampling import JointSample, read_joint_sample
from harper_arm.status import MotorStatus, read_motor_status

DEFAULT_RESULTS_ROOT = Path("results")
STATUS_POLL_INTERVAL_S = 0.25
# Quick single-shot reads; live polling would race on the serial port.
_TESTS_WITHOUT_LIVE_STATUS = frozenset(
    {"ping", "present_voltage", "present_temperature", "current_no_load"}
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def sweep_waypoints(joint: JointConfig, *, steps: int) -> list[int]:
    low, high = joint.position_limits
    if steps < 2:
        return [low]
    return [
        int(round(low + index * (high - low) / (steps - 1)))
        for index in range(steps)
    ]

RowFields = Callable[[JointSample, Joint], dict[str, object]]
SummaryFields = Callable[[JointSample, Joint], dict[str, object]]
SetupFn = Callable[[Joint], None]
StatusCallback = Callable[[MotorStatus], None]


def _start_status_poller(
    connected_joint: Joint,
    on_status: StatusCallback,
    stop_event: threading.Event,
) -> threading.Thread:
    def poll() -> None:
        while not stop_event.is_set():
            if connected_joint.bus_lock.acquire(blocking=False):
                try:
                    on_status(read_motor_status(connected_joint))
                except Exception:
                    pass
                finally:
                    connected_joint.bus_lock.release()
            stop_event.wait(STATUS_POLL_INTERVAL_S)

    thread = threading.Thread(target=poll, daemon=True, name="motor-status")
    thread.start()
    return thread


@contextmanager
def motor_test_run(
    *,
    test: str,
    schema: str,
    joint_name: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    metadata: dict[str, Any] | None = None,
    on_status: StatusCallback | None = None,
) -> Iterator[tuple[Joint, TestRun]]:
    """Open one joint, record a motor-suite run, and tear down on exit."""
    connected_joint = Joint.open(joint_name=joint_name, config_path=config_path)
    stop_event = threading.Event()
    poller: threading.Thread | None = None
    try:
        with TestRun(
            suite="motor",
            test=test,
            schema=schema,
            results_root=results_root,
            joint=joint_name,
            metadata=metadata or {},
        ) as recorder:
            if on_status is not None and test not in _TESTS_WITHOUT_LIVE_STATUS:
                poller = _start_status_poller(connected_joint, on_status, stop_event)
            yield connected_joint, recorder
    finally:
        stop_event.set()
        if poller is not None:
            poller.join(timeout=STATUS_POLL_INTERVAL_S * 2)
        connected_joint.close()


def run_single_read(
    *,
    test: str,
    schema: str,
    joint: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    setup: SetupFn | None = None,
    on_status: StatusCallback | None = None,
    row_fields: RowFields,
    summary_fields: SummaryFields,
) -> Path:
    """Read one register snapshot, write a CSV row, and return the run directory."""
    with motor_test_run(
        test=test,
        schema=schema,
        joint_name=joint,
        config_path=config_path,
        results_root=results_root,
        on_status=on_status,
    ) as (connected_joint, recorder):
        if setup is not None:
            setup(connected_joint)
        sample = read_joint_sample(connected_joint.motor, joint=joint)
        recorder.write_row(
            {
                "timestamp_utc": utc_now().isoformat(),
                "joint": joint,
                **row_fields(sample, connected_joint),
            }
        )
        recorder.set_summary(**summary_fields(sample, connected_joint))
        return recorder.run_dir
