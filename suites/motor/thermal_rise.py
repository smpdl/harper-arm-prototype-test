"""Hold ~50% goal current and sample temperature periodically."""

from __future__ import annotations

import time
from pathlib import Path

from harper_arm import units
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.sampling import read_joint_sample

from .helpers import DEFAULT_RESULTS_ROOT, StatusCallback, motor_test_run, utc_now

DEFAULT_DURATION_S = 120.0
DEFAULT_INTERVAL_S = 1.0
LOAD_FRACTION = 0.5


def run(
    *,
    joint: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    duration_s: float = DEFAULT_DURATION_S,
    interval_s: float = DEFAULT_INTERVAL_S,
    load_fraction: float = LOAD_FRACTION,
    on_status: StatusCallback | None = None,
) -> Path:
    with motor_test_run(
        test="thermal_rise",
        schema="thermal_rise",
        joint_name=joint,
        config_path=config_path,
        results_root=results_root,
        metadata={
            "duration_s": duration_s,
            "interval_s": interval_s,
            "load_fraction": load_fraction,
        },
        on_status=on_status,
    ) as (connected_joint, recorder):
        goal_current = int(round(connected_joint.joint.current_limit * load_fraction))
        connected_joint.configure_velocity_mode(goal_current=goal_current)
        connected_joint.torque_enable()
        connected_joint.set_velocity(units.rpm_to_velocity(5.0))

        started = time.monotonic()
        deadline = started + duration_s
        next_tick = started
        peak_temp = float("-inf")

        while time.monotonic() < deadline:
            elapsed_s = time.monotonic() - started
            sample = read_joint_sample(connected_joint)
            temp_c = units.temperature_to_celsius(sample.temperature)
            current_ma = units.current_to_ma(
                sample.current, model=connected_joint.joint.model
            )
            peak_temp = max(peak_temp, temp_c)
            recorder.write_row(
                {
                    "timestamp_utc": utc_now().isoformat(),
                    "elapsed_s": elapsed_s,
                    "joint": joint,
                    "temperature_c": temp_c,
                    "current": sample.current,
                    "current_ma": current_ma,
                }
            )
            next_tick += interval_s
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)

        connected_joint.set_velocity(0)
        recorder.set_summary(
            peak_temperature_c=peak_temp if peak_temp != float("-inf") else None,
            goal_current=goal_current,
            duration_s=duration_s,
        )
        return recorder.run_dir
