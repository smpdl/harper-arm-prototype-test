"""Move to nominal angles and record position error (10 trials per target)."""

from __future__ import annotations

from pathlib import Path

from harper_arm import units
from harper_arm.config import JointConfig
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.motor import move_to_ticks

from .helpers import DEFAULT_RESULTS_ROOT, StatusCallback, motor_test_run, utc_now

DEFAULT_TRIALS = 10
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
) -> Path:
    with motor_test_run(
        test="position_accuracy",
        schema="position_accuracy",
        joint_name=joint,
        config_path=config_path,
        results_root=results_root,
        metadata={"trials_per_target": trials},
        on_status=on_status,
    ) as (connected_joint, recorder):
        connected_joint.configure_position_mode()
        connected_joint.motor.torque_enable()
        errors: list[float] = []
        reached_all = True

        for target_deg in TARGET_ANGLES_DEG:
            goal_ticks = _target_ticks_for_angle(connected_joint.joint, target_deg)
            for trial in range(1, trials + 1):
                reached, measured_ticks = move_to_ticks(connected_joint.motor, goal_ticks)
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

        recorder.set_summary(
            success=reached_all,
            max_abs_error_deg=max(errors) if errors else None,
            mean_abs_error_deg=(sum(errors) / len(errors)) if errors else None,
        )
        return recorder.run_dir
