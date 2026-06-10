"""
Velocity Tracking Test.

Steps through a velocity profile and compares measured RPM. 

Writes a row to the results CSV file with the timestamp, joint name, step index, target RPM, measured RPM, and error RPM.
Sets the summary to the maximum absolute error RPM and the mean absolute error RPM. Returns the path to the results directory.
"""

from __future__ import annotations

import time
from pathlib import Path

from harper_arm import units
from harper_arm.joint import DEFAULT_CONFIG_PATH

from .helpers import DEFAULT_RESULTS_ROOT, StatusCallback, motor_test_run, utc_now

STEP_HOLD_S = 3
TARGET_RPMS = (0.0, 5.0, 10.0, -5.0, 0.0)


def run(
    *,
    joint: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    step_hold_s: float = STEP_HOLD_S,
    on_status: StatusCallback | None = None,
) -> Path:
    with motor_test_run(
        test="velocity_tracking",
        schema="velocity_tracking",
        joint_name=joint,
        config_path=config_path,
        results_root=results_root,
        metadata={"step_hold_s": step_hold_s},
        on_status=on_status,
    ) as (connected_joint, recorder):
        connected_joint.configure_velocity_mode()
        errors: list[float] = []

        for index, target_rpm in enumerate(TARGET_RPMS):
            connected_joint.set_velocity(units.rpm_to_velocity(target_rpm))
            time.sleep(step_hold_s)
            measured_velocity = connected_joint.read_present_velocity()
            measured_rpm = units.velocity_to_rpm(measured_velocity)
            error_rpm = measured_rpm - target_rpm
            errors.append(abs(error_rpm))
            recorder.write_row(
                {
                    "timestamp_utc": utc_now().isoformat(),
                    "joint": joint,
                    "step_index": index,
                    "target_rpm": target_rpm,
                    "measured_rpm": measured_rpm,
                    "error_rpm": error_rpm,
                }
            )

        connected_joint.set_velocity(0)
        recorder.set_summary(
            max_abs_error_rpm=max(errors) if errors else None,
            mean_abs_error_rpm=(sum(errors) / len(errors)) if errors else None,
        )
        return recorder.run_dir
