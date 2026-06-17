"""Sequential whole-arm homing in motor-id order."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from harper_arm.arm import FullArm
from harper_arm.config import (
    ArmConfig,
    joint_names_sorted_by_motor_id,
    load_arm_config,
)
from harper_arm.joint import DEFAULT_CONFIG_PATH, Joint
from harper_arm.motor import move_to_ticks

if TYPE_CHECKING:
    from harper_arm.safety import SafetyMonitor

SEQUENTIAL_HOME_PAUSE_S = 0.5

# After elbow tests, shoulder rotation is parked at max; retract elbow before shoulder.
ELBOW_TEST_JOINT = "r_elb_flex"
ELBOW_TEST_SUPPORT_JOINT = "r_sh_rot"
_ELBOW_TEST_HOME_PRIORITY = (ELBOW_TEST_JOINT, ELBOW_TEST_SUPPORT_JOINT)


def ordered_home_targets(arm: ArmConfig) -> tuple[tuple[str, int], ...]:
    """Return ``(joint_name, home_ticks)`` for joints with a recorded home, by motor ID."""
    return tuple(
        (name, int(arm.joints[name].home_position))
        for name in joint_names_sorted_by_motor_id(arm)
        if arm.joints[name].home_position is not None
    )


def ordered_home_targets_for_joint(
    arm: ArmConfig,
    joint_under_test: str | None = None,
) -> tuple[tuple[str, int], ...]:
    """Return homing targets, using elbow-safe order when ``joint_under_test`` is the elbow."""
    targets = ordered_home_targets(arm)
    if joint_under_test != ELBOW_TEST_JOINT:
        return targets

    by_name = dict(targets)
    ordered: list[tuple[str, int]] = []
    for name in _ELBOW_TEST_HOME_PRIORITY:
        if name in by_name:
            ordered.append((name, by_name[name]))
    for name, ticks in targets:
        if name not in _ELBOW_TEST_HOME_PRIORITY:
            ordered.append((name, ticks))
    return tuple(ordered)


def return_joint_to_home(joint: Joint) -> None:
    """Move one joint to its recorded home position when configured."""
    home_ticks = joint.joint.home_position
    if home_ticks is None:
        return
    move_to_ticks(joint, int(home_ticks), joint_name=joint.joint_name)


def move_arm_to_home_sequential(
    arm: FullArm,
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    arm_config: ArmConfig | None = None,
    joint_under_test: str | None = None,
    pause_s: float = SEQUENTIAL_HOME_PAUSE_S,
    prepare_bus: bool = True,
    profile_velocity_rpm: float | None = None,
    profile_acceleration_rpm2: float | None = None,
    monitor: SafetyMonitor | None = None,
) -> tuple[dict[str, tuple[bool, int]], str, str | None]:
    """Torque every joint, then move homed joints to home starting at motor ID 1.

    Joints without a recorded ``home_position`` are torqued but not commanded.
    Each homed joint is moved in ascending motor-ID order, except after elbow
    tests where the elbow homes first, then shoulder rotation, then the rest.
    The arm waits ``pause_s`` between joint moves (not after the last).
    """
    resolved_config = arm_config or arm.config or load_arm_config(config_path)
    if prepare_bus:
        arm.prepare_motion_bus(
            joint_name=None,
            profile_velocity_rpm=profile_velocity_rpm,
            profile_acceleration_rpm2=profile_acceleration_rpm2,
        )
    else:
        arm.torque_enable_all()

    targets = ordered_home_targets_for_joint(resolved_config, joint_under_test)
    results: dict[str, tuple[bool, int]] = {}
    last_index = len(targets) - 1
    for index, (joint_name, target_ticks) in enumerate(targets):
        reached, measured = move_to_ticks(arm, target_ticks, joint_name=joint_name)
        results[joint_name] = (reached, measured)
        if monitor is not None:
            safety = monitor.evaluate(arm.sample())
            if safety.should_stop:
                return results, safety.reason, safety.triggering_joint
        if pause_s > 0 and index < last_index:
            time.sleep(pause_s)
    return results, "", None
