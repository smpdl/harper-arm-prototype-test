"""
Present Temperature Test.

Reads the present temperature of a motor using the Present_Temperature control table.

Reads the present temperature of a motor and writes a row to the results CSV file with the timestamp, joint name, and temperature.
Sets the summary to the temperature. Returns the path to the results directory.
"""

from __future__ import annotations

from pathlib import Path

from harper_arm import units
from harper_arm.joint import DEFAULT_CONFIG_PATH

from .helpers import DEFAULT_RESULTS_ROOT, StatusCallback, run_single_read


def run(
    *,
    joint: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    on_status: StatusCallback | None = None,
) -> Path:
    return run_single_read(
        test="present_temperature",
        schema="present_temperature",
        joint=joint,
        config_path=config_path,
        results_root=results_root,
        on_status=on_status,
        row_fields=lambda sample, _arm: {
            "temperature_c": units.temperature_to_celsius(sample.temperature),
        },
        summary_fields=lambda sample, _arm: {
            "temperature_c": units.temperature_to_celsius(sample.temperature),
        },
    )
