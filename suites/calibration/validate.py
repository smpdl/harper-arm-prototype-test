"""Post-calibration validation at 25%, 50%, and 75% of recorded span."""

from __future__ import annotations

from pathlib import Path

from harper_arm.arm import FullArm
from harper_arm.calibration.config import DEFAULT_CALIBRATION_PATH, load_calibration_settings
from harper_arm.calibration.session import JointCalibration
from harper_arm.calibration.validate import prepare_validation_support_joints, validate_joint
from harper_arm.config import load_arm_config
from harper_arm.home import move_arm_to_home_sequential
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.logging import TestRun
from harper_arm.sampling import operator_abort_guard

from .helpers import DEFAULT_RESULTS_ROOT, utc_now


def run(
    *,
    joint: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    calibration_path: Path | str = DEFAULT_CALIBRATION_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    **_: object,
) -> Path:
    settings = load_calibration_settings(calibration_path)
    arm_config = load_arm_config(config_path)
    joint_cfg = arm_config.joints[joint]
    calibration = JointCalibration(
        joint_name=joint,
        min_position=joint_cfg.position_limits[0],
        home_position=joint_cfg.home_position,
        max_position=joint_cfg.position_limits[1],
    )

    arm = FullArm.open(config_path=config_path)
    skip_homing = False
    try:
        with operator_abort_guard() as abort_event:
            with TestRun(
                suite="calibration",
                test="validate",
                schema="calibration_validation",
                results_root=results_root,
                joint=joint,
                metadata={
                    "profile_velocity_rpm": settings.profile_velocity_rpm,
                    "step_small_deg": settings.step_small_deg,
                    "step_large_deg": settings.step_large_deg,
                },
            ) as recorder:
                move_arm_to_home_sequential(
                    arm,
                    config_path=config_path,
                    profile_velocity_rpm=settings.profile_velocity_rpm,
                    profile_acceleration_rpm2=settings.profile_acceleration_rpm2,
                )
                prepare_validation_support_joints(
                    arm,
                    joint,
                    arm_config,
                    settings,
                    abort_event=abort_event,
                )
                connected_joint = arm.joint_view(joint)
                result = validate_joint(
                    connected_joint,
                    calibration,
                    settings,
                    abort_event=abort_event,
                )
                for fraction_result in result.fraction_results:
                    recorder.write_row(
                        {
                            "timestamp_utc": utc_now().isoformat(),
                            "joint": joint,
                            "fraction": fraction_result.fraction,
                            "target_ticks": fraction_result.target_ticks,
                            "measured_ticks": fraction_result.measured_ticks,
                            "error_deg": fraction_result.error_deg,
                            "reached": fraction_result.reached,
                        }
                    )
                recorder.set_summary(
                    passed=result.passed,
                    repeatability_error_deg=result.repeatability_error_deg,
                    joint=joint,
                    message=result.message,
                )
                skip_homing = abort_event.is_set()
                return recorder.run_dir
    finally:
        arm.close(skip_homing=skip_homing, joint_under_test=joint)
