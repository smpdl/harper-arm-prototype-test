"""Incremental payload test with safety stop conditions."""

from __future__ import annotations

import time
from pathlib import Path

from harper_arm import units
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.sampling import operator_abort_guard

from .helpers import (
    DEFAULT_MOTIONS_PATH,
    DEFAULT_RESULTS_ROOT,
    load_pose_ticks,
    make_safety_monitor,
    prepare_hold_pose,
    require_interactive,
    structural_test_run,
    utc_now,
)

DEFAULT_POSE = "home"
DEFAULT_PAYLOAD_STEPS_KG = (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
SETTLE_TIME_S = 3.0

def run(
    *,
    pose: str = DEFAULT_POSE,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    motions_path: Path | str = DEFAULT_MOTIONS_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    payload_steps_kg: tuple[float, ...] = DEFAULT_PAYLOAD_STEPS_KG,
    settle_time_s: float = SETTLE_TIME_S,
    interactive: bool = True,
) -> Path:
    require_interactive("max_payload", interactive)

    goals = load_pose_ticks(pose, config_path=config_path, motions_path=motions_path)

    with structural_test_run(
        test="max_payload",
        schema="max_payload",
        config_path=config_path,
        results_root=results_root,
        metadata={
            "pose": pose,
            "payload_steps_kg": list(payload_steps_kg),
            "settle_time_s": settle_time_s,
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
            models = arm.joint_models()

            limiting_joint: str | None = None
            stop_reason = ""
            max_payload_kg: float | None = None

            print(
                "\nIncremental payload test. At each step, attach the load and press Enter."
            )

            for default_payload_kg in payload_steps_kg:
                payload_kg = default_payload_kg
                entered = input(
                    f"Payload kg (Enter for {payload_kg:g}, q to stop): "
                ).strip()
                if entered.lower() == "q":
                    break
                if entered:
                    payload_kg = float(entered)
                input(f"Apply {payload_kg:g} kg and press Enter when settled...")

                time.sleep(settle_time_s)
                snapshot = arm.sample()
                result = monitor.evaluate(snapshot)
                limiting = result.triggering_joint if result.should_stop else None
                if result.should_stop:
                    limiting_joint = result.triggering_joint
                    stop_reason = result.reason

                for joint_name, sample in snapshot.items():
                    recorder.write_row(
                        {
                            "timestamp_utc": utc_now().isoformat(),
                            "payload_kg": payload_kg,
                            "joint": joint_name,
                            "position_deg": units.ticks_to_degrees(sample.position),
                            "current_ma": units.current_to_ma(
                                sample.current, model=models[joint_name]
                            ),
                            "temperature_c": units.temperature_to_celsius(
                                sample.temperature
                            ),
                            "limiting": joint_name == limiting,
                        }
                    )

                if result.should_stop:
                    break

                max_payload_kg = payload_kg

        recorder.set_summary(
            pose_reached=reached_all,
            max_payload_kg=max_payload_kg,
            limiting_joint=limiting_joint,
            stop_reason=stop_reason or None,
            rows=recorder.row_count,
        )
        return recorder.run_dir
