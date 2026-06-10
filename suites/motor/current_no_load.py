"""
Current No Load Test.

Reads the present current of a motor with torque disabled and writes a row to the results CSV file with the timestamp, joint name, and current.
Sets the summary to the current. Returns the path to the results directory.
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
        test="current_no_load",
        schema="current_no_load",
        joint=joint,
        config_path=config_path,
        results_root=results_root,
        on_status=on_status,
        setup=lambda connected_joint: connected_joint.torque_disable(),
        row_fields=lambda sample, connected_joint: {
            "current": sample.current,
            "current_ma": units.current_to_ma(
                sample.current, model=connected_joint.joint.model
            ),
        },
        summary_fields=lambda sample, connected_joint: {
            "current_ma": units.current_to_ma(
                sample.current, model=connected_joint.joint.model
            ),
        },
    )
