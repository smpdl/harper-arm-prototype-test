"""Sweep configured position limits and log measured positions."""

from __future__ import annotations

from pathlib import Path

from harper_arm import units
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.motor import move_to_ticks

from .helpers import DEFAULT_RESULTS_ROOT, StatusCallback, motor_test_run, sweep_waypoints, utc_now

DEFAULT_STEPS = 5


def run(
    *,
    joint: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    steps: int = DEFAULT_STEPS,
    on_status: StatusCallback | None = None,
) -> Path:
    with motor_test_run(
        test="range_of_motion",
        schema="range_of_motion",
        joint_name=joint,
        config_path=config_path,
        results_root=results_root,
        metadata={"steps": steps},
        on_status=on_status,
    ) as (connected_joint, recorder):
        connected_joint.configure_position_mode()
        connected_joint.motor.torque_enable()
        waypoints = sweep_waypoints(connected_joint.joint, steps=steps)
        reached_all = True

        for index, target_ticks in enumerate(waypoints):
            reached, measured_ticks = move_to_ticks(connected_joint.motor, target_ticks)
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

        recorder.set_summary(success=reached_all, waypoint_count=len(waypoints))
        return recorder.run_dir
