"""Hold a configured pose and sample drift, current, and temperature."""

from __future__ import annotations

import time
from pathlib import Path

from harper_arm.config import load_arm_config, require_arm_calibrated
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.sampling import operator_abort_guard, sample_until
from suites.e2e.config import DEFAULT_E2E_CONFIG_PATH

from .helpers import (
    DEFAULT_RESULTS_ROOT,
    make_safety_monitor,
    prepare_hold_pose,
    require_pose_approach_confirmed,
    return_arm_home,
    structural_test_run,
)

DEFAULT_POSE = "home"
DEFAULT_DURATION_S = 60.0
DEFAULT_INTERVAL_S = 0.5


def run(
    *,
    pose: str = DEFAULT_POSE,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    duration_s: float = DEFAULT_DURATION_S,
    interval_s: float = DEFAULT_INTERVAL_S,
    pose_confirmed: bool = False,
) -> Path:
    arm_config = load_arm_config(config_path)
    require_arm_calibrated(arm_config)
    require_pose_approach_confirmed(pose=pose, pose_confirmed=pose_confirmed)

    with structural_test_run(
        test="self_weight_hold",
        schema="self_weight_hold",
        config_path=config_path,
        results_root=results_root,
        metadata={
            "pose": pose,
            "duration_s": duration_s,
            "interval_s": interval_s,
            "e2e_config_path": str(e2e_config_path),
        },
    ) as (arm, recorder):
        returned_home = False
        monitor = None
        reached_all = False
        stopped = False
        reason = ""
        triggering_joint = None
        try:
            with operator_abort_guard() as abort_event:
                reached_home, _, home_stop, home_limit = prepare_hold_pose(
                    arm,
                    DEFAULT_POSE,
                    config_path=config_path,
                    e2e_config_path=e2e_config_path,
                )
                if home_stop:
                    recorder.set_summary(
                        pose_reached=False,
                        stopped_early=True,
                        stop_reason=home_stop,
                        triggering_joint=home_limit,
                        duration_s=duration_s,
                        sample_count=0,
                    )
                    return recorder.run_dir

                reached_all = reached_home
                move_stop_reason = ""
                move_limiting_joint = None
                if pose != DEFAULT_POSE:
                    reached_all, _, move_stop_reason, move_limiting_joint = prepare_hold_pose(
                        arm,
                        pose,
                        config_path=config_path,
                        e2e_config_path=e2e_config_path,
                    )

                baseline = arm.sample()
                monitor = make_safety_monitor(
                    arm,
                    reference_positions={name: s.position for name, s in baseline.items()},
                    baseline_temperatures={
                        name: s.temperature for name, s in baseline.items()
                    },
                    abort_event=abort_event,
                )

                started = time.monotonic()
                stopped = bool(move_stop_reason)
                reason = move_stop_reason
                triggering_joint = move_limiting_joint

                if not stopped:

                    def on_sample(snapshot: dict) -> None:
                        elapsed = time.monotonic() - started
                        recorder.record_snapshot(
                            snapshot,
                            models=arm.joint_models(),
                            elapsed_s=elapsed,
                        )

                    _, (stopped, reason, triggering_joint) = sample_until(
                        arm.sample,
                        should_stop=monitor.as_stop_check(),
                        interval_s=interval_s,
                        max_duration_s=duration_s,
                        on_sample=on_sample,
                    )
        finally:
            if pose != DEFAULT_POSE and not returned_home:
                _, home_reason, _ = return_arm_home(
                    arm,
                    config_path=config_path,
                    e2e_config_path=e2e_config_path,
                    monitor=monitor,
                )
                returned_home = not home_reason

        recorder.set_summary(
            pose_reached=reached_all,
            stopped_early=stopped,
            stop_reason=reason or None,
            triggering_joint=triggering_joint,
            duration_s=duration_s,
            sample_count=recorder.row_count,
            returned_home=returned_home,
        )
        return recorder.run_dir
