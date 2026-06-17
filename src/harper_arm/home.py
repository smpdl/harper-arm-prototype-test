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

SEQUENTIAL_HOME_PAUSE_S = 3.0


def ordered_home_targets(arm: ArmConfig) -> tuple[tuple[str, int], ...]:
    """Return ``(joint_name, home_ticks)`` for joints with a recorded home, by motor ID."""
    return tuple(
        (name, int(arm.joints[name].home_position))
        for name in joint_names_sorted_by_motor_id(arm)
        if arm.joints[name].home_position is not None
    )


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
    pause_s: float = SEQUENTIAL_HOME_PAUSE_S,
    prepare_bus: bool = True,
    profile_velocity_rpm: float | None = None,
    profile_acceleration_rpm2: float | None = None,
    monitor: SafetyMonitor | None = None,
) -> tuple[dict[str, tuple[bool, int]], str, str | None]:
    """Torque every joint, then move homed joints to home starting at motor ID 1.

    Joints without a recorded ``home_position`` are torqued but not commanded.
    Each homed joint is moved in ascending motor-ID order. The arm waits
    ``pause_s`` after every joint move, including the last.
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

    results: dict[str, tuple[bool, int]] = {}
    for joint_name, target_ticks in ordered_home_targets(resolved_config):
        reached, measured = move_to_ticks(arm, target_ticks, joint_name=joint_name)
        results[joint_name] = (reached, measured)
        if monitor is not None:
            safety = monitor.evaluate(arm.sample())
            if safety.should_stop:
                return results, safety.reason, safety.triggering_joint
        if pause_s > 0:
            time.sleep(pause_s)
    return results, "", None
