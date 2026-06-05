"""Read Present_Input_Voltage for one joint."""

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
        test="present_voltage",
        schema="present_voltage",
        joint=joint,
        config_path=config_path,
        results_root=results_root,
        on_status=on_status,
        row_fields=lambda sample, _arm: {
            "voltage_raw": sample.voltage,
            "voltage_v": units.voltage_to_volts(sample.voltage),
        },
        summary_fields=lambda sample, _arm: {
            "voltage_v": units.voltage_to_volts(sample.voltage),
        },
    )
