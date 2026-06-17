"""Shared helpers for structural suite run() functions."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harper_arm import units
from harper_arm.arm import FullArm
from harper_arm.config import ArmConfig, load_arm_config, require_arm_calibrated, resolve_home_pose
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.home import SEQUENTIAL_HOME_PAUSE_S, move_arm_to_home_sequential
from harper_arm.logging import TestRun
from harper_arm.motion import ResolvedKeyframe, resolve_plan
from harper_arm.motor import (
    POSITION_TOLERANCE_TICKS,
    move_to_ticks,
    write_positions_sequential,
)
from harper_arm.safety import SafetyMonitor
from harper_arm.sampling import JointSample
from harper_arm.trajectory import Trajectory, synchronized_scurve_trajectory
from suites.e2e.config import DEFAULT_E2E_CONFIG_PATH, load_e2e_config

DEFAULT_HOME_NAME = "home"
DEFAULT_RESULTS_ROOT = Path("results")
STRUCTURAL_E2E_POSES: tuple[str, ...] = ("reach_sideways", "reach_overhead")


def utc_now() -> datetime:
    return datetime.now(UTC)


# Link name -> joints assessed together during point-load flex checks.
LINK_JOINTS: dict[str, tuple[str, ...]] = {
    "shoulder": ("r_sh_flex", "r_sh_abd", "r_sh_rot"),
    "elbow": ("r_elb_flex",),
    "forearm": ("r_farm_rot",),
    "wrist": ("r_wrist_flex",),
    "fingers": (
        "r_fin_thumb",
        "r_fin_index",
        "r_fin_middle",
        "r_fin_ring",
        "r_fin_pinky",
    ),
}


@dataclass(frozen=True)
class StructuralMotionConfig:
    profile_velocity_rpm: float
    profile_acceleration_rpm2: float | None
    scurve_max_velocity_deg_s: float
    scurve_max_acceleration_deg_s2: float
    scurve_sample_period_s: float


@contextmanager
def structural_test_run(
    *,
    test: str,
    schema: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    metadata: dict[str, Any] | None = None,
) -> Iterator[tuple[FullArm, TestRun]]:
    """Open the full arm, record a structural-suite run, and tear down on exit."""
    arm = FullArm.open(config_path=config_path)
    try:
        with TestRun(
            suite="structural",
            test=test,
            schema=schema,
            results_root=results_root,
            metadata=metadata or {},
        ) as recorder:
            yield arm, recorder
    finally:
        if not arm._closed:
            arm.close()


def structural_pose_names(
    *,
    e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH,
) -> tuple[str, ...]:
    """Pose names available to structural tests."""
    names = [DEFAULT_HOME_NAME]
    e2e = load_e2e_config(e2e_config_path)
    for pose_name in STRUCTURAL_E2E_POSES:
        if pose_name in e2e.tests:
            names.append(pose_name)
    return tuple(names)


def load_motion_config(
    pose: str,
    *,
    e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH,
) -> StructuralMotionConfig:
    """Return S-curve execution defaults for a structural pose."""
    e2e = load_e2e_config(e2e_config_path)
    if pose in e2e.tests:
        test = e2e.tests[pose]
        return StructuralMotionConfig(
            profile_velocity_rpm=test.profile_velocity_rpm,
            profile_acceleration_rpm2=test.profile_acceleration_rpm2,
            scurve_max_velocity_deg_s=test.scurve_max_velocity_deg_s,
            scurve_max_acceleration_deg_s2=test.scurve_max_acceleration_deg_s2,
            scurve_sample_period_s=test.scurve_sample_period_s,
        )
    # Fall back to the first configured e2e test for shared document defaults.
    fallback = next(iter(e2e.tests.values()))
    return StructuralMotionConfig(
        profile_velocity_rpm=fallback.profile_velocity_rpm,
        profile_acceleration_rpm2=fallback.profile_acceleration_rpm2,
        scurve_max_velocity_deg_s=fallback.scurve_max_velocity_deg_s,
        scurve_max_acceleration_deg_s2=fallback.scurve_max_acceleration_deg_s2,
        scurve_sample_period_s=fallback.scurve_sample_period_s,
    )


def pose_approach_preview_lines(
    pose: str,
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH,
) -> list[str]:
    """Human-readable targets for a structural pose approach move."""
    if pose == DEFAULT_HOME_NAME:
        return ["Move all joints to calibrated home."]
    arm_config = load_arm_config(config_path)
    keyframe = _resolved_hold_keyframe(
        pose,
        arm_config,
        e2e_config_path=e2e_config_path,
    )
    assert keyframe is not None
    lines = [f"Approach pose {pose!r} — keyframe {keyframe.name!r}:"]
    for target in keyframe.targets.values():
        lines.append(
            f"  {target.joint}: {target.offset_deg:+.1f} deg "
            f"-> {target.target_ticks} ticks"
        )
    return lines


def require_pose_approach_confirmed(*, pose: str, pose_confirmed: bool) -> None:
    """Reject non-home structural approaches until the operator confirms targets."""
    if pose == DEFAULT_HOME_NAME:
        return
    if not pose_confirmed:
        raise ValueError(
            f"structural pose {pose!r} requires operator confirmation before approach; "
            "set pose_confirmed=True after reviewing targets"
        )


def return_arm_home(
    arm: FullArm,
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH,
    monitor: SafetyMonitor | None = None,
) -> tuple[bool, str, str | None]:
    """Return every joint to calibrated home."""
    motion = load_motion_config(DEFAULT_HOME_NAME, e2e_config_path=e2e_config_path)
    prepare_motion_bus(arm, motion)
    return move_home_scurve(
        arm,
        config_path=config_path,
        e2e_config_path=e2e_config_path,
        motion=motion,
        monitor=monitor,
    )


def _resolved_hold_keyframe(
    pose: str,
    arm_config: ArmConfig,
    *,
    e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH,
) -> ResolvedKeyframe | None:
    if pose == DEFAULT_HOME_NAME:
        return None
    e2e = load_e2e_config(e2e_config_path)
    try:
        test = e2e.tests[pose]
    except KeyError as exc:
        known = ", ".join(sorted(e2e.tests))
        raise ValueError(
            f"unknown structural pose {pose!r}; known: home, {known}"
        ) from exc
    resolved = resolve_plan(arm_config, test.plan)
    return resolved[0]


def load_pose_ticks(
    pose_name: str,
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH,
) -> dict[str, int]:
    """Return encoder targets for a structural hold pose."""
    arm_config = load_arm_config(config_path)
    home = resolve_home_pose(arm_config)
    if pose_name == DEFAULT_HOME_NAME:
        return home

    keyframe = _resolved_hold_keyframe(
        pose_name,
        arm_config,
        e2e_config_path=e2e_config_path,
    )
    assert keyframe is not None
    pose = dict(home)
    for joint_name, target in keyframe.targets.items():
        pose[joint_name] = target.target_ticks
    return pose


def prepare_motion_bus(
    arm: FullArm,
    motion: StructuralMotionConfig,
) -> None:
    arm.prepare_motion_bus(
        joint_name=None,
        profile_velocity_rpm=motion.profile_velocity_rpm,
        profile_acceleration_rpm2=motion.profile_acceleration_rpm2,
    )
    arm.torque_enable_all()


def execute_trajectory(
    arm: FullArm,
    trajectory: Trajectory,
    monitor: SafetyMonitor | None = None,
) -> tuple[str, str | None]:
    """Stream sampled S-curve setpoints, optionally checking safety between samples."""
    started = time.monotonic()
    for point in trajectory.points:
        remaining_s = started + point.elapsed_s - time.monotonic()
        if remaining_s > 0:
            time.sleep(remaining_s)

        write_positions_sequential(arm, point.targets)

        if monitor is None:
            continue
        snapshot = arm.sample()
        safety = monitor.evaluate(snapshot)
        if safety.should_stop:
            return safety.reason, safety.triggering_joint

    return "", None


def move_keyframe_scurve(
    arm: FullArm,
    keyframe: ResolvedKeyframe,
    motion: StructuralMotionConfig,
    monitor: SafetyMonitor | None = None,
) -> tuple[dict[str, tuple[bool, int]], str, str | None]:
    """Stream one synchronized S-curve keyframe."""
    start_snapshot = arm.sample()
    starts = {
        joint_name: start_snapshot[joint_name].position
        for joint_name in keyframe.targets
    }
    targets = {
        joint_name: target.target_ticks
        for joint_name, target in keyframe.targets.items()
    }
    trajectory = synchronized_scurve_trajectory(
        starts,
        targets,
        max_velocity_deg_s=motion.scurve_max_velocity_deg_s,
        max_acceleration_deg_s2=motion.scurve_max_acceleration_deg_s2,
        sample_period_s=motion.scurve_sample_period_s,
    )
    stop_reason, limiting_joint = execute_trajectory(arm, trajectory, monitor)
    snapshot = arm.sample()
    reached = {
        joint_name: (
            abs(snapshot[joint_name].position - target_ticks)
            <= POSITION_TOLERANCE_TICKS,
            snapshot[joint_name].position,
        )
        for joint_name, target_ticks in targets.items()
    }
    return reached, stop_reason, limiting_joint


def move_home_scurve(
    arm: FullArm,
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH,
    motion: StructuralMotionConfig | None = None,
    monitor: SafetyMonitor | None = None,
) -> tuple[bool, str, str | None]:
    """Return the arm to calibrated home, one joint at a time in motor-ID order."""
    _ = e2e_config_path
    _ = motion
    results, stop_reason, limiting_joint = move_arm_to_home_sequential(
        arm,
        config_path=config_path,
        prepare_bus=False,
        pause_s=SEQUENTIAL_HOME_PAUSE_S,
        monitor=monitor,
    )
    reached_all = all(reached for reached, _ in results.values())
    return reached_all, stop_reason, limiting_joint


def prepare_hold_pose(
    arm: FullArm,
    pose: str,
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH,
    monitor: SafetyMonitor | None = None,
) -> tuple[bool, dict[str, tuple[bool, int]], str, str | None]:
    """Configure the bus, stream to ``pose``, and return reach results."""
    motion = load_motion_config(pose, e2e_config_path=e2e_config_path)
    prepare_motion_bus(arm, motion)

    arm_config = load_arm_config(config_path)
    keyframe = _resolved_hold_keyframe(
        pose,
        arm_config,
        e2e_config_path=e2e_config_path,
    )

    if keyframe is None:
        results, stop_reason, limiting_joint = move_arm_to_home_sequential(
            arm,
            config_path=config_path,
            prepare_bus=False,
            pause_s=SEQUENTIAL_HOME_PAUSE_S,
            monitor=monitor,
        )
        reached_all = all(reached for reached, _ in results.values())
        return reached_all, results, stop_reason, limiting_joint

    reached, stop_reason, limiting_joint = move_keyframe_scurve(
        arm,
        keyframe,
        motion,
        monitor,
    )
    reached_all = all(flag for flag, _ in reached.values())
    return reached_all, reached, stop_reason, limiting_joint


def make_safety_monitor(
    arm: FullArm,
    *,
    reference_positions: Mapping[str, int] | None = None,
    baseline_temperatures: Mapping[str, int] | None = None,
    abort_event: threading.Event | None = None,
) -> SafetyMonitor:
    return SafetyMonitor(
        current_limits=arm.current_limits(),
        reference_positions=reference_positions,
        baseline_temperatures=baseline_temperatures,
        abort_event=abort_event,
    )


def max_flex_deg(
    samples: Mapping[str, JointSample],
    reference: Mapping[str, int],
    joint_names: tuple[str, ...],
) -> float:
    """Largest absolute position error (degrees) across ``joint_names``."""
    peak = 0.0
    for name in joint_names:
        sample = samples[name]
        ref = reference[name]
        drift = units.position_error_deg(sample.position, ref)
        peak = max(peak, abs(drift))
    return peak
