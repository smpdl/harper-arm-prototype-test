"""Hold a pose under end-effector load and sample telemetry."""

from __future__ import annotations

from pathlib import Path

from harper_arm import units
from harper_arm.config import load_arm_config, require_arm_calibrated
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.sampling import operator_abort_guard, sample_until
from suites.e2e.config import DEFAULT_E2E_CONFIG_PATH

from .helpers import (
    DEFAULT_HOME_NAME,
    DEFAULT_RESULTS_ROOT,
    make_safety_monitor,
    prepare_hold_pose,
    require_pose_approach_confirmed,
    return_arm_home,
    structural_test_run,
    utc_now,
)

DEFAULT_POSE = "home"
DEFAULT_HOLD_TIME_S = 30.0
DEFAULT_INTERVAL_S = 0.5


def run(
    *,
    pose: str = DEFAULT_POSE,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    hold_time_s: float = DEFAULT_HOLD_TIME_S,
    interval_s: float = DEFAULT_INTERVAL_S,
    payload_kg: float | None = None,
    pose_confirmed: bool = False,
    **_: object,
) -> Path:
    arm_config = load_arm_config(config_path)
    require_arm_calibrated(arm_config)
    require_pose_approach_confirmed(pose=pose, pose_confirmed=pose_confirmed)

    with structural_test_run(
        test="max_payload",
        schema="max_payload",
        config_path=config_path,
        results_root=results_root,
        metadata={
            "pose": pose,
            "hold_time_s": hold_time_s,
            "interval_s": interval_s,
            "payload_kg": payload_kg,
            "e2e_config_path": str(e2e_config_path),
        },
    ) as (arm, recorder):
        returned_home = pose == DEFAULT_HOME_NAME
        monitor = None
        reached_all = False
        stopped = False
        reason = ""
        limiting_joint = None
        try:
            with operator_abort_guard() as abort_event:
                reached_home, _, home_stop, home_limit = prepare_hold_pose(
                    arm,
                    DEFAULT_HOME_NAME,
                    config_path=config_path,
                    e2e_config_path=e2e_config_path,
                )
                if home_stop:
                    recorder.set_summary(
                        pose_reached=False,
                        payload_kg=payload_kg,
                        stopped_early=True,
                        stop_reason=home_stop,
                        limiting_joint=home_limit,
                        hold_time_s=hold_time_s,
                        sample_count=0,
                        returned_home=False,
                    )
                    return recorder.run_dir

                reached_all = reached_home
                move_stop_reason = ""
                move_limiting_joint = None
                if pose != DEFAULT_HOME_NAME:
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

                stopped = bool(move_stop_reason)
                reason = move_stop_reason
                limiting_joint = move_limiting_joint

                if not stopped:

                    def on_sample(snapshot: dict) -> None:
                        for joint_name, sample in snapshot.items():
                            recorder.write_row(
                                {
                                    "timestamp_utc": utc_now().isoformat(),
                                    "payload_kg": payload_kg if payload_kg is not None else "",
                                    "joint": joint_name,
                                    "position_deg": units.ticks_to_degrees(sample.position),
                                    "current_ma": units.current_to_ma(
                                        sample.current,
                                        model=arm.joint_models()[joint_name],
                                    ),
                                    "temperature_c": units.temperature_to_celsius(
                                        sample.temperature
                                    ),
                                    "limiting": joint_name == limiting_joint,
                                }
                            )

                    _, (stopped, reason, limiting_joint) = sample_until(
                        arm.sample,
                        should_stop=monitor.as_stop_check(),
                        interval_s=interval_s,
                        max_duration_s=hold_time_s,
                        on_sample=on_sample,
                    )
        finally:
            if pose != DEFAULT_HOME_NAME and not returned_home:
                reached, home_reason, _ = return_arm_home(
                    arm,
                    pose=pose,
                    config_path=config_path,
                    e2e_config_path=e2e_config_path,
                    monitor=monitor,
                )
                returned_home = reached and not home_reason

        recorder.set_summary(
            pose_reached=reached_all,
            payload_kg=payload_kg,
            stopped_early=stopped,
            stop_reason=reason or None,
            limiting_joint=limiting_joint,
            hold_time_s=hold_time_s,
            sample_count=recorder.row_count,
            returned_home=returned_home,
        )
        return recorder.run_dir
