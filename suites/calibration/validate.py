"""Post-calibration validation at 25%, 50%, and 75% of recorded span."""

from __future__ import annotations

from pathlib import Path

from harper_arm.calibration.config import DEFAULT_CALIBRATION_PATH, load_calibration_settings
from harper_arm.calibration.session import JointCalibration
from harper_arm.calibration.validate import validate_joint
from harper_arm.config import load_arm_config
from harper_arm.joint import DEFAULT_CONFIG_PATH

from .helpers import DEFAULT_RESULTS_ROOT, calibration_test_run, utc_now


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
        home_position=None,
        max_position=joint_cfg.position_limits[1],
    )

    with calibration_test_run(
        test="validate",
        schema="calibration_validation",
        joint_name=joint,
        config_path=config_path,
        calibration_path=calibration_path,
        results_root=results_root,
    ) as (connected_joint, recorder, _session, abort_event):
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
        return recorder.run_dir
