"""Shared helpers for structural suite run() functions."""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harper_arm import units
from harper_arm.arm import FullArm
from harper_arm.config import load_arm_config, load_motions_config, resolve_pose
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.logging import TestRun
from harper_arm.motor import move_to_ticks
from harper_arm.safety import SafetyMonitor
from harper_arm.sampling import JointSample

DEFAULT_MOTIONS_PATH = Path("config/motions.yaml")
DEFAULT_RESULTS_ROOT = Path("results")


def utc_now() -> datetime:
    return datetime.now(UTC)

# Link name -> joints assessed together during point-load flex checks.
LINK_JOINTS: dict[str, tuple[str, ...]] = {
    "shoulder": ("r_sh_flex", "r_sh_abd", "r_sh_rot"),
    "elbow": ("r_elb_flex",),
    "forearm": ("r_farm_rot",),
    "wrist": ("r_wrist_flex",),
    "fingers": (
        "r_fin_thumb",
        "r_fin_index",
        "r_fin_middle",
        "r_fin_ring",
        "r_fin_pinky",
    ),
}


@contextmanager
def structural_test_run(
    *,
    test: str,
    schema: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    metadata: dict[str, Any] | None = None,
) -> Iterator[tuple[FullArm, TestRun]]:
    """Open the full arm, record a structural-suite run, and tear down on exit."""
    arm = FullArm.open(config_path=config_path)
    try:
        with TestRun(
            suite="structural",
            test=test,
            schema=schema,
            results_root=results_root,
            metadata=metadata or {},
        ) as recorder:
            yield arm, recorder
    finally:
        arm.close()


def require_interactive(test: str, interactive: bool) -> None:
    """Reject non-interactive runs for operator-assisted structural tests."""
    if not interactive:
        raise ValueError(
            f"{test} requires interactive=True so an operator can apply loads "
            "and respond to prompts."
        )


def load_pose_ticks(
    pose_name: str,
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    motions_path: Path | str = DEFAULT_MOTIONS_PATH,
) -> dict[str, int]:
    arm_config = load_arm_config(config_path)
    motions = load_motions_config(motions_path)
    return resolve_pose(motions, pose_name, arm=arm_config)


def move_to_pose(
    arm: FullArm,
    pose: Mapping[str, int],
) -> dict[str, tuple[bool, int]]:
    return {
        joint_name: move_to_ticks(arm, target_ticks, joint_name=joint_name)
        for joint_name, target_ticks in pose.items()
    }


def prepare_hold_pose(
    arm: FullArm,
    pose: Mapping[str, int],
) -> tuple[bool, dict[str, tuple[bool, int]]]:
    arm.configure_position_mode()
    arm.apply_position_profile_velocities()
    arm.torque_enable_all()
    move_results = move_to_pose(arm, pose)
    reached_all = all(reached for reached, _ in move_results.values())
    return reached_all, move_results


def make_safety_monitor(
    arm: FullArm,
    *,
    reference_positions: Mapping[str, int] | None = None,
    baseline_temperatures: Mapping[str, int] | None = None,
    abort_event: threading.Event | None = None,
) -> SafetyMonitor:
    return SafetyMonitor(
        current_limits=arm.current_limits(),
        reference_positions=reference_positions,
        baseline_temperatures=baseline_temperatures,
        abort_event=abort_event,
    )


def max_flex_deg(
    samples: Mapping[str, JointSample],
    reference: Mapping[str, int],
    joint_names: tuple[str, ...],
) -> float:
    """Largest absolute position error (degrees) across ``joint_names``."""
    peak = 0.0
    for name in joint_names:
        sample = samples[name]
        ref = reference[name]
        drift = units.position_error_deg(sample.position, ref)
        peak = max(peak, abs(drift))
    return peak
