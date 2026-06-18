"""Shared helpers for motor suite run() functions."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harper_arm.arm import FullArm
from harper_arm.calibration.config import DEFAULT_CALIBRATION_PATH, load_calibration_settings
from harper_arm.calibration.validate import prepare_validation_support_joints
from harper_arm.config import (
    load_arm_config,
    require_arm_calibrated,
    require_joint_calibrated,
    resolve_home_pose,
    resolve_position_profile_acceleration_rpm2,
    resolve_position_profile_velocity_rpm,
)
from harper_arm import units
from harper_arm.home import SEQUENTIAL_HOME_PAUSE_S, move_arm_to_home_sequential
from harper_arm.joint import DEFAULT_CONFIG_PATH, Joint
from harper_arm.logging import TestRun
from harper_arm.motor import POSITION_TOLERANCE_TICKS, move_to_ticks
from harper_arm.sampling import JointSample, read_joint_sample
from harper_arm.status import MotorStatus, _motor_status_unlocked
from tui.catalog import MOTOR_MOTION_TESTS, MOTOR_POSITION_TESTS, MOTOR_WHOLE_ARM_TESTS

DEFAULT_BASE_POSE = "home"
DEFAULT_RESULTS_ROOT = Path("results")
STATUS_POLL_INTERVAL_S = 0.1
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
    connected_joint.set_position_profile_rpm(
        rpm,
        acceleration_rpm2=resolve_position_profile_acceleration_rpm2(connected_joint.joint),
    )
    return rpm


def load_base_pose_ticks(
    pose_name: str = DEFAULT_BASE_POSE,
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> dict[str, int]:
    """Return home ticks from ``arm.yaml`` for whole-arm setup/teardown."""
    if pose_name != DEFAULT_BASE_POSE:
        raise ValueError("only the calibrated home base pose is supported")
    arm_config = load_arm_config(config_path)
    return resolve_home_pose(arm_config)


def _position_tolerance_failures(
    arm: FullArm,
    pose: Mapping[str, int],
    *,
    tolerance_ticks: int = POSITION_TOLERANCE_TICKS,
) -> list[str]:
    """Return human-readable per-joint errors when pose targets are not met."""
    samples = arm.sample()
    failures: list[str] = []
    for joint_name, target_ticks in pose.items():
        joint_cfg = arm.config.joints[joint_name]
        measured_ticks = samples[joint_name].position
        error_ticks = units.position_error_ticks(
            measured_ticks,
            target_ticks,
            extended_position=units.joint_uses_extended_position(joint_cfg.position_limits),
        )
        if abs(error_ticks) > tolerance_ticks:
            failures.append(
                f"{joint_name}: measured={measured_ticks} target={target_ticks} "
                f"error={error_ticks} ticks (tolerance={tolerance_ticks})"
            )
    return failures


def at_base_position(
    arm: FullArm,
    pose: Mapping[str, int],
    *,
    tolerance_ticks: int = POSITION_TOLERANCE_TICKS,
) -> bool:
    return not _position_tolerance_failures(arm, pose, tolerance_ticks=tolerance_ticks)


def move_arm_to_pose(
    arm: FullArm,
    pose: Mapping[str, int],
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    joint_under_test: str | None = None,
) -> dict[str, tuple[bool, int]]:
    arm_config = load_arm_config(config_path)
    home = resolve_home_pose(arm_config)
    if dict(pose) != home:
        raise ValueError("only the calibrated home pose is supported for whole-arm moves")
    return move_arm_to_home_sequential(
        arm,
        config_path=config_path,
        prepare_bus=False,
        joint_under_test=joint_under_test,
    )[0]


def ensure_base_position(
    arm: FullArm,
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    pose_name: str = DEFAULT_BASE_POSE,
    joint_under_test: str | None = None,
) -> None:
    """Verify the arm is at base pose, moving there first when needed."""
    pose = load_base_pose_ticks(pose_name, config_path=config_path)
    if at_base_position(arm, pose):
        return
    move_arm_to_pose(arm, pose, config_path=config_path, joint_under_test=joint_under_test)
    failures = _position_tolerance_failures(arm, pose)
    if failures:
        details = "; ".join(failures)
        raise RuntimeError(
            f"failed to reach base position before motion test: {details}"
        )


def return_to_base_position(
    arm: FullArm,
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    pose_name: str = DEFAULT_BASE_POSE,
    joint_under_test: str | None = None,
) -> None:
    """Reconfigure position mode and move every joint back to base pose."""
    arm.configure_position_mode()
    arm.apply_position_profile_velocities()
    arm.torque_enable_all()
    pose = load_base_pose_ticks(pose_name, config_path=config_path)
    move_arm_to_pose(arm, pose, config_path=config_path, joint_under_test=joint_under_test)
    failures = _position_tolerance_failures(arm, pose)
    if failures:
        details = "; ".join(failures)
        raise RuntimeError(
            f"failed to return to base position after motion test: {details}"
        )


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
                    # Caller already holds bus_lock; read_motor_status would re-acquire and deadlock.
                    on_status(_motor_status_unlocked(connected_joint))
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

    Position accuracy and power on response open the full bus, torque every
    joint, move to base pose, and return there on teardown. Read-only tests
    open only the joint under test without motion setup.
    """
    arm_config = load_arm_config(config_path)
    if test in MOTOR_WHOLE_ARM_TESTS:
        require_arm_calibrated(arm_config)
    elif test in MOTOR_MOTION_TESTS:
        require_joint_calibrated(arm_config.joints[joint_name])

    if test in MOTOR_WHOLE_ARM_TESTS:
        arm = FullArm.open(config_path=config_path)
        try:
            arm.prepare_motion_bus(
                joint_name=joint_name,
                profile_velocity_rpm=profile_velocity_rpm,
            )
            ensure_base_position(
                arm,
                config_path=config_path,
                joint_under_test=joint_name,
            )
            calibration_settings = load_calibration_settings(DEFAULT_CALIBRATION_PATH)
            prepare_validation_support_joints(
                arm,
                joint_name,
                arm_config,
                calibration_settings,
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
            arm.close(joint_under_test=joint_name)
        return

    connected_joint = Joint.open(joint_name=joint_name, config_path=config_path)
    try:
        if test in MOTOR_MOTION_TESTS and test in MOTOR_POSITION_TESTS:
            configure_position_motion(
                connected_joint,
                profile_velocity_rpm=profile_velocity_rpm,
            )
            connected_joint.torque_enable()
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
