"""Enable torque and command a +10° position step."""

from __future__ import annotations

import time
from pathlib import Path

from harper_arm import units
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
) -> Path:
    with motor_test_run(
        test="power_on_response",
        schema="power_on_response",
        joint_name=joint,
        config_path=config_path,
        results_root=results_root,
        metadata={"delta_deg": POWER_ON_DELTA_DEG},
        on_status=on_status,
    ) as (connected_joint, recorder):
        connected_joint.configure_position_mode()
        start_ticks = int(connected_joint.motor.get_position())
        start_deg = units.ticks_to_degrees(start_ticks)
        goal_ticks = start_ticks + units.degrees_to_ticks(POWER_ON_DELTA_DEG)
        low, high = connected_joint.joint.position_limits
        goal_ticks = max(low, min(high, goal_ticks))

        connected_joint.motor.torque_enable()
        started = time.monotonic()
        reached, end_ticks = move_to_ticks(connected_joint.motor, goal_ticks)
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
                "success": reached,
            }
        )
        recorder.set_summary(
            success=reached,
            start_position_deg=start_deg,
            end_position_deg=end_deg,
            delta_deg=delta_deg,
            duration_s=duration_s,
        )
        return recorder.run_dir
