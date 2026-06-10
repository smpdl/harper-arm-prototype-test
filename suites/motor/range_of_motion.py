"""Sweep configured position limits and log measured positions."""

from __future__ import annotations

from pathlib import Path

from harper_arm import units
from harper_arm.config import resolve_position_profile_velocity_rpm
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.motor import move_to_ticks

from .helpers import (
    DEFAULT_RESULTS_ROOT,
    StatusCallback,
    motor_test_run,
    sweep_waypoints,
    utc_now,
)

DEFAULT_STEPS = 5


def run(
    *,
    joint: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    steps: int = DEFAULT_STEPS,
    on_status: StatusCallback | None = None,
    profile_velocity_rpm: float | None = None,
) -> Path:
    with motor_test_run(
        test="range_of_motion",
        schema="range_of_motion",
        joint_name=joint,
        config_path=config_path,
        results_root=results_root,
        metadata={"steps": steps, "profile_velocity_rpm": profile_velocity_rpm},
        on_status=on_status,
        profile_velocity_rpm=profile_velocity_rpm,
    ) as (connected_joint, recorder):
        applied_rpm = resolve_position_profile_velocity_rpm(
            connected_joint.joint,
            override_rpm=profile_velocity_rpm,
        )
        waypoints = sweep_waypoints(connected_joint.joint, steps=steps)
        reached_all = True

        for index, target_ticks in enumerate(waypoints):
            reached, measured_ticks = move_to_ticks(connected_joint, target_ticks)
            reached_all = reached_all and reached
            recorder.write_row(
                {
                    "timestamp_utc": utc_now().isoformat(),
                    "joint": joint,
                    "waypoint_index": index,
                    "target_ticks": target_ticks,
                    "measured_ticks": measured_ticks,
                    "measured_deg": units.ticks_to_degrees(measured_ticks),
                }
            )

        recorder.set_summary(
            success=reached_all,
            profile_velocity_rpm=applied_rpm,
            waypoint_count=len(waypoints),
        )
        return recorder.run_dir
