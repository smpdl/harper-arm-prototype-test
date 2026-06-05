"""Operator-assisted point-load flex assessment per arm link."""

from __future__ import annotations

from pathlib import Path

from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.sampling import operator_abort_guard

from .helpers import (
    DEFAULT_MOTIONS_PATH,
    DEFAULT_RESULTS_ROOT,
    LINK_JOINTS,
    load_pose_ticks,
    make_safety_monitor,
    max_flex_deg,
    prepare_hold_pose,
    require_interactive,
    structural_test_run,
    utc_now,
)


def _prompt(label: str) -> str:
    return input(f"{label}: ").strip()

def run(
    *,
    pose: str = "home",
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    motions_path: Path | str = DEFAULT_MOTIONS_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    interactive: bool = True,
) -> Path:
    require_interactive("point_load", interactive)

    goals = load_pose_ticks(pose, config_path=config_path, motions_path=motions_path)

    with structural_test_run(
        test="point_load",
        schema="point_load",
        config_path=config_path,
        results_root=results_root,
        metadata={"pose": pose, "motions_path": str(motions_path)},
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
            reference = {name: sample.position for name, sample in baseline.items()}

            limiting_joint: str | None = None
            stop_reason = ""
            links_tested = 0
            stopped_early = False

            for link, joint_names in LINK_JOINTS.items():
                print(f"\n--- Point load: {link} ({', '.join(joint_names)}) ---")
                print("Apply the test load, then press Enter to record flex.")
                _prompt("Press Enter when ready")
                load_description = _prompt("Load description")
                operator_notes = _prompt("Operator notes")

                snapshot = arm.sample()
                result = monitor.evaluate(snapshot)
                flex_deg = max_flex_deg(snapshot, reference, joint_names)
                primary_joint = joint_names[0]

                recorder.write_row(
                    {
                        "timestamp_utc": utc_now().isoformat(),
                        "joint": primary_joint,
                        "link": link,
                        "load_description": load_description,
                        "operator_notes": operator_notes,
                        "max_flex_deg": flex_deg,
                    }
                )
                links_tested += 1

                if result.should_stop:
                    stopped_early = True
                    stop_reason = result.reason
                    limiting_joint = result.triggering_joint
                    break

        recorder.set_summary(
            pose_reached=reached_all,
            links_tested=links_tested,
            stopped_early=stopped_early,
            stop_reason=stop_reason or None,
            limiting_joint=limiting_joint,
        )
        return recorder.run_dir
