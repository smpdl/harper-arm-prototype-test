"""
Position Accuracy Test.

Moves a motor through target angle ranges and records the position error for each step.

Each trial sweeps 0 -> 45 -> 90 -> 135 -> 180, then repeats for the configured number
of trials (default 10).

Note that the target angles are not actual angles, but rather fractions of the configured
position range. For example, 45.0 means minimum position limit + 45/180 of the span.

Writes a row to the results CSV file with the timestamp, joint name, trial number, target angle, 
measured angle, and position error. Sets the summary to the maximum absolute position error, 
the mean absolute position error, and the success flag. Returns the path to the results directory.
"""

from __future__ import annotations

import time
from pathlib import Path

from harper_arm import units
from harper_arm.config import JointConfig, resolve_position_profile_velocity_rpm
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.motor import move_to_ticks

from .helpers import DEFAULT_RESULTS_ROOT, StatusCallback, motor_test_run, utc_now

DEFAULT_TRIALS = 10
STEP_PAUSE_S = 3.0
TARGET_ANGLES_DEG = (0.0, 45.0, 90.0, 135.0, 180.0)

def _target_ticks_for_angle(joint: JointConfig, angle_deg: float) -> int:
    low, high = joint.position_limits
    span = high - low
    if span == 0:
        return low
    ratio = angle_deg / 180.0
    return int(round(low + ratio * span))

def run(
    *,
    joint: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    trials: int = DEFAULT_TRIALS,
    on_status: StatusCallback | None = None,
    profile_velocity_rpm: float | None = None,
) -> Path:
    with motor_test_run(
        test="position_accuracy",
        schema="position_accuracy",
        joint_name=joint,
        config_path=config_path,
        results_root=results_root,
        metadata={
            "trials_per_target": trials,
            "step_pause_s": STEP_PAUSE_S,
            "profile_velocity_rpm": profile_velocity_rpm,
        },
        on_status=on_status,
        profile_velocity_rpm=profile_velocity_rpm,
    ) as (connected_joint, recorder):
        applied_rpm = resolve_position_profile_velocity_rpm(
            connected_joint.joint,
            override_rpm=profile_velocity_rpm,
        )
        errors: list[float] = []
        reached_all = True

        for trial in range(1, trials + 1):
            for target_deg in TARGET_ANGLES_DEG:
                goal_ticks = _target_ticks_for_angle(connected_joint.joint, target_deg)
                reached, measured_ticks = move_to_ticks(connected_joint, goal_ticks)
                reached_all = reached_all and reached
                error_deg = units.position_error_deg(measured_ticks, goal_ticks)
                measured_deg = target_deg + error_deg
                errors.append(abs(error_deg))
                recorder.write_row(
                    {
                        "timestamp_utc": utc_now().isoformat(),
                        "joint": joint,
                        "trial": trial,
                        "target_deg": target_deg,
                        "measured_deg": measured_deg,
                        "error_deg": error_deg,
                    }
                )
                time.sleep(STEP_PAUSE_S)

        recorder.set_summary(
            success=reached_all,
            profile_velocity_rpm=applied_rpm,
            max_abs_error_deg=max(errors) if errors else None,
            mean_abs_error_deg=(sum(errors) / len(errors)) if errors else None,
        )
        return recorder.run_dir
