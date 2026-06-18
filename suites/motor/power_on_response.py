"""
Power On Response Test.

Homes the whole arm, then commands a 10deg step toward the joint's semantic max
limit on the joint under test.

Writes start/end position, delta, duration, and success flag.
Sets the summary to the applied profile velocity and movement result.
"""

from __future__ import annotations

import time
from pathlib import Path

from harper_arm import units
from harper_arm.config import offset_ticks_toward_max, resolve_position_profile_velocity_rpm
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.motor import move_to_ticks

from .helpers import DEFAULT_RESULTS_ROOT, StatusCallback, motor_test_run, utc_now

POWER_ON_DELTA_DEG = 10.0

def run(
    *,
    joint: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    on_status: StatusCallback | None = None,
    profile_velocity_rpm: float | None = None,
) -> Path:
    with motor_test_run(
        test="power_on_response",
        schema="power_on_response",
        joint_name=joint,
        config_path=config_path,
        results_root=results_root,
        metadata={
            "delta_deg": POWER_ON_DELTA_DEG,
            "delta_direction": "toward_max",
            "profile_velocity_rpm": profile_velocity_rpm,
        },
        on_status=on_status,
        profile_velocity_rpm=profile_velocity_rpm,
    ) as (connected_joint, recorder):
        joint_cfg = connected_joint.joint
        applied_rpm = resolve_position_profile_velocity_rpm(
            joint_cfg,
            override_rpm=profile_velocity_rpm,
        )
        extended_position = units.joint_uses_extended_position(joint_cfg.position_limits)
        start_ticks = connected_joint.get_position()
        start_deg = units.ticks_to_degrees(start_ticks)
        goal_ticks = offset_ticks_toward_max(
            joint_cfg.position_limits,
            start_ticks,
            POWER_ON_DELTA_DEG,
        )

        started = time.monotonic()
        reached, end_ticks = move_to_ticks(connected_joint, goal_ticks)
        duration_s = time.monotonic() - started
        end_deg = units.ticks_to_degrees(end_ticks)
        delta_deg = units.position_error_deg(
            end_ticks,
            start_ticks,
            extended_position=extended_position,
        )

        recorder.write_row(
            {
                "timestamp_utc": utc_now().isoformat(),
                "joint": joint,
                "start_position_deg": start_deg,
                "end_position_deg": end_deg,
                "delta_deg": delta_deg,
                "duration_s": duration_s,
                "profile_velocity_rpm": applied_rpm,
                "success": reached,
            }
        )
        recorder.set_summary(
            profile_velocity_rpm=applied_rpm,
            success=reached,
            start_position_deg=start_deg,
            end_position_deg=end_deg,
            delta_deg=delta_deg,
            duration_s=duration_s,
        )
        return recorder.run_dir
