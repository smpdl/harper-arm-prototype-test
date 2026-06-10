"""Shared helpers for motor suite run() functions."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harper_arm.arm import FullArm
from harper_arm.config import JointConfig, resolve_position_profile_velocity_rpm
from harper_arm.joint import DEFAULT_CONFIG_PATH, Joint
from harper_arm.logging import TestRun
from harper_arm.sampling import JointSample, read_joint_sample
from harper_arm.status import MotorStatus, read_motor_status
from tui.suite_catalog import MOTOR_MOTION_TESTS

DEFAULT_RESULTS_ROOT = Path("results")
STATUS_POLL_INTERVAL_S = 0.25
# Quick single-shot reads; live polling would race on the serial port.
_TESTS_WITHOUT_LIVE_STATUS = frozenset(
    {"ping", "present_voltage", "present_temperature", "current_no_load"}
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def configure_position_motion(
    connected_joint: Joint,
    *,
    profile_velocity_rpm: float | None = None,
) -> float:
    """Configure position mode and apply per-joint profile velocity (rpm)."""
    rpm = resolve_position_profile_velocity_rpm(
        connected_joint.joint,
        override_rpm=profile_velocity_rpm,
    )
    connected_joint.configure_position_mode()
    connected_joint.set_profile_velocity_rpm(rpm)
    return rpm


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


def _run_with_joint(
    *,
    connected_joint: Joint,
    test: str,
    schema: str,
    joint_name: str,
    results_root: Path,
    metadata: dict[str, Any] | None,
    on_status: StatusCallback | None,
) -> Iterator[tuple[Joint, TestRun]]:
    stop_event = threading.Event()
    poller: threading.Thread | None = None
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
        try:
            yield connected_joint, recorder
        finally:
            stop_event.set()
            if poller is not None:
                poller.join(timeout=STATUS_POLL_INTERVAL_S * 2)


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
    profile_velocity_rpm: float | None = None,
) -> Iterator[tuple[Joint, TestRun]]:
    """Open hardware, record a motor-suite run, and tear down on exit.

    Motion tests open the full bus, ensure torque on every servo, and torque
    off all servos on teardown. Read-only tests open only the joint under test.
    """
    if test in MOTOR_MOTION_TESTS:
        arm = FullArm.open(config_path=config_path)
        try:
            arm.prepare_motion_bus(
                joint_name=joint_name,
                profile_velocity_rpm=profile_velocity_rpm,
            )
            connected_joint = arm.joint_view(joint_name)
            yield from _run_with_joint(
                connected_joint=connected_joint,
                test=test,
                schema=schema,
                joint_name=joint_name,
                results_root=results_root,
                metadata=metadata,
                on_status=on_status,
            )
        finally:
            arm.close()
        return

    connected_joint = Joint.open(joint_name=joint_name, config_path=config_path)
    try:
        yield from _run_with_joint(
            connected_joint=connected_joint,
            test=test,
            schema=schema,
            joint_name=joint_name,
            results_root=results_root,
            metadata=metadata,
            on_status=on_status,
        )
    finally:
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
        sample = read_joint_sample(connected_joint)
        recorder.write_row(
            {
                "timestamp_utc": utc_now().isoformat(),
                "joint": joint,
                **row_fields(sample, connected_joint),
            }
        )
        recorder.set_summary(**summary_fields(sample, connected_joint))
        return recorder.run_dir
