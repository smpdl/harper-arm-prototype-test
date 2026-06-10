"""
Power On Response Test. 

Enables torque and commands a +10deg position step.

Writes a row to the results CSV file with the timestamp, joint name, start position, end position, delta position, duration, and success flag.
Sets the summary to the profile velocity, success flag, start position, end position, and delta position. Returns the path to the results directory.
"""

from __future__ import annotations

import time
from pathlib import Path

from harper_arm import units
from harper_arm.config import resolve_position_profile_velocity_rpm
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.motor import move_to_ticks

from .helpers import DEFAULT_RESULTS_ROOT, StatusCallback, motor_test_run, utc_now

POWER_ON_DELTA_DEG = 10.0
PRE_RETURN_PAUSE_S = 3.0


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
            "pre_return_pause_s": PRE_RETURN_PAUSE_S,
            "profile_velocity_rpm": profile_velocity_rpm,
        },
        on_status=on_status,
        profile_velocity_rpm=profile_velocity_rpm,
    ) as (connected_joint, recorder):
        applied_rpm = resolve_position_profile_velocity_rpm(
            connected_joint.joint,
            override_rpm=profile_velocity_rpm,
        )
        start_ticks = connected_joint.get_position()
        start_deg = units.ticks_to_degrees(start_ticks)
        goal_ticks = start_ticks + units.degrees_to_ticks(POWER_ON_DELTA_DEG)
        low, high = connected_joint.joint.position_limits
        goal_ticks = max(low, min(high, goal_ticks))

        started = time.monotonic()
        reached, end_ticks = move_to_ticks(connected_joint, goal_ticks)
        duration_s = time.monotonic() - started
        end_deg = units.ticks_to_degrees(end_ticks)
        delta_deg = end_deg - start_deg

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
        time.sleep(PRE_RETURN_PAUSE_S)
        return recorder.run_dir
