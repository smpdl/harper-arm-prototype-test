"""Non-backdriveable joint calibration."""

from __future__ import annotations

from pathlib import Path

from harper_arm.calibration.config import DEFAULT_CALIBRATION_PATH
from harper_arm.joint import DEFAULT_CONFIG_PATH

from .helpers import DEFAULT_RESULTS_ROOT, require_interactive
from .operator import CalibrationOperator, run_stdin_loop


def run(
    *,
    joint: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    calibration_path: Path | str = DEFAULT_CALIBRATION_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    interactive: bool = True,
    **_: object,
) -> Path:
    require_interactive("non_backdriveable", interactive)

    with CalibrationOperator(
        test="non_backdriveable",
        joint_name=joint,
        backdriveable=False,
        config_path=config_path,
        calibration_path=calibration_path,
        results_root=results_root,
    ) as operator:
        run_stdin_loop(operator)
        return operator.run_dir
