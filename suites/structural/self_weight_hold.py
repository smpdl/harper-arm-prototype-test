"""Hold a configured pose and sample drift, current, and temperature."""

from __future__ import annotations

import time
from pathlib import Path

from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.sampling import operator_abort_guard, sample_until

from .helpers import (
    DEFAULT_MOTIONS_PATH,
    DEFAULT_RESULTS_ROOT,
    load_pose_ticks,
    make_safety_monitor,
    prepare_hold_pose,
    structural_test_run,
)

DEFAULT_POSE = "home"
DEFAULT_DURATION_S = 60.0
DEFAULT_INTERVAL_S = 0.5


def run(
    *,
    pose: str = DEFAULT_POSE,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    motions_path: Path | str = DEFAULT_MOTIONS_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    duration_s: float = DEFAULT_DURATION_S,
    interval_s: float = DEFAULT_INTERVAL_S,
) -> Path:
    goals = load_pose_ticks(pose, config_path=config_path, motions_path=motions_path)

    with structural_test_run(
        test="self_weight_hold",
        schema="self_weight_hold",
        config_path=config_path,
        results_root=results_root,
        metadata={
            "pose": pose,
            "duration_s": duration_s,
            "interval_s": interval_s,
            "motions_path": str(motions_path),
        },
    ) as (arm, recorder):
        with operator_abort_guard() as abort_event:
            reached_all, _ = prepare_hold_pose(arm, goals)
            baseline = arm.sample()
            monitor = make_safety_monitor(
                arm,
                reference_positions={name: s.position for name, s in baseline.items()},
                baseline_temperatures={name: s.temperature for name, s in baseline.items()},
                abort_event=abort_event,
            )

            started = time.monotonic()

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

        recorder.set_summary(
            pose_reached=reached_all,
            stopped_early=stopped,
            stop_reason=reason or None,
            triggering_joint=triggering_joint,
            duration_s=duration_s,
            sample_count=recorder.row_count,
        )
        return recorder.run_dir
