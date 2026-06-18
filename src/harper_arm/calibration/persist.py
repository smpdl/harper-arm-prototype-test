"""
Write calibration results and partial progress to yaml files.

Calibration stores the home position beside each joint in arm.yaml, 
and the limits in the same file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from harper_arm.calibration.session import CalibrationSession, JointCalibration
from harper_arm.config import load_arm_config

DEFAULT_PARTIAL_PATH = Path("calibration.partial.yaml")

def save_partial_session(
    session: CalibrationSession,
    path: Path | str = DEFAULT_PARTIAL_PATH,
    *,
    error: str | None = None,
) -> Path:
    """Save in-progress calibration to a file for recovery after abort or crash."""
    output_path = Path(path)
    document: dict[str, Any] = {"calibration": session.to_dict()}
    if error is not None:
        document["error"] = error
    output_path.write_text(
        yaml.safe_dump(document, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return output_path

def load_partial_session(path: Path | str = DEFAULT_PARTIAL_PATH) -> CalibrationSession | None:
    """Load in-progress calibration from a file for recovery after abort or crash."""
    partial_path = Path(path)
    if not partial_path.is_file():
        return None
    raw = yaml.safe_load(partial_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    calibration = raw.get("calibration")
    if not isinstance(calibration, dict):
        return None
    return CalibrationSession.from_dict(calibration)

def apply_joint_calibration(
    joint: JointCalibration,
    *,
    arm_path: Path | str,
) -> None:
    """Update arm.yaml with the recorded limits and home position for one joint."""
    if not joint.is_complete():
        raise ValueError(f"joint {joint.joint_name!r} calibration is incomplete")

    assert joint.min_position is not None
    assert joint.max_position is not None
    assert joint.home_position is not None

    _update_arm_joint_limits(
        arm_path,
        joint.joint_name,
        min_ticks=joint.min_position,
        max_ticks=joint.max_position,
        home_ticks=joint.home_position,
    )


def apply_session(
    session: CalibrationSession,
    *,
    arm_path: Path | str,
) -> list[str]:
    """Apply every complete joint in the session. Returns applied joint names."""
    applied: list[str] = []
    for name, joint in sorted(session.joints.items()):
        if joint.is_complete():
            apply_joint_calibration(joint, arm_path=arm_path)
            applied.append(name)
    return applied


def _load_yaml_mapping(path: Path | str) -> dict[str, Any]:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{config_path} root must be a mapping.")
    return raw

def _write_yaml(path: Path | str, document: dict[str, Any]) -> None:
    Path(path).write_text(
        yaml.safe_dump(document, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )

def _update_arm_joint_limits(
    arm_path: Path | str,
    joint_name: str,
    *,
    min_ticks: int,
    max_ticks: int,
    home_ticks: int,
) -> None:
    document = _load_yaml_mapping(arm_path)
    joints = document.get("joints")
    if not isinstance(joints, dict) or joint_name not in joints:
        raise ValueError(f"joint {joint_name!r} not found in {arm_path}")
    joint_entry = joints[joint_name]
    if not isinstance(joint_entry, dict):
        raise ValueError(f"joints.{joint_name} must be a mapping.")
    joint_entry["position_limits"] = [min_ticks, max_ticks]
    # The saved home tick is the zero point for all fraction-based e2e tests.
    # It is written atomically with the limits so tests cannot mix old home data
    # with a newly calibrated travel range.
    joint_entry["home_position"] = home_ticks
    joint_entry["calibrated"] = True
    _write_yaml(arm_path, document)
    load_arm_config(arm_path)
