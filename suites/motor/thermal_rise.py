"""
Thermal Rise Test.

Applies sustained load at a fraction of the joint current limit and samples
temperature and current periodically for five minutes by default.

XM/XC motors use current control mode (Goal Current). XL430 uses PWM mode
because it has no Goal Current register.

Writes a row to the results CSV file with the timestamp, joint name, elapsed time,
temperature, current, and current in mA. Sets the summary to the peak temperature,
applied load settings, and duration. Returns the path to the results directory.
"""

from __future__ import annotations

import time
from pathlib import Path

from harper_arm import units
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.sampling import read_joint_sample

from .helpers import DEFAULT_RESULTS_ROOT, StatusCallback, motor_test_run, utc_now

DEFAULT_DURATION_S = 300.0  # 5 minutes
DEFAULT_INTERVAL_S = 1.0  # 1 second
LOAD_FRACTION = 0.8  # 80% of the joint current limit


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
        load_settings = connected_joint.apply_thermal_load(load_fraction=load_fraction)
        recorder.set_summary(**load_settings)

        started = time.monotonic()
        deadline = started + duration_s
        next_tick = started
        peak_temp = float("-inf")
        current_limit = connected_joint.joint.current_limit
        model = connected_joint.joint.model

        try:
            while time.monotonic() < deadline:
                elapsed_s = time.monotonic() - started
                sample = read_joint_sample(connected_joint)
                temp_c = units.temperature_to_celsius(sample.temperature)
                current_ma = units.thermal_sample_current_ma(
                    sample.current,
                    model=model,
                    current_limit=current_limit,
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
        finally:
            connected_joint.release_thermal_load()

        recorder.set_summary(
            peak_temperature_c=peak_temp if peak_temp != float("-inf") else None,
            duration_s=duration_s,
        )
        return recorder.run_dir
