"""
ArmConfig and JointConfig, plus YAML loaders for arm and motion configuration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from harper_arm.motor import normalize_model, supported_models

# Used when a joint omits position_profile_velocity_rpm in arm.yaml (~factory X-series default).
DEFAULT_POSITION_PROFILE_VELOCITY_RPM = 23.0


@dataclass(frozen=True)
class JointConfig:
    name: str
    id: int
    model: str
    protocol: int
    position_limits: tuple[int, int]
    current_limit: int
    position_profile_velocity_rpm: float | None = None


def resolve_position_profile_velocity_rpm(
    joint: JointConfig,
    *,
    override_rpm: float | None = None,
) -> float:
    """Return profile velocity for position-mode moves (override > joint config > default)."""
    if override_rpm is not None:
        return override_rpm
    if joint.position_profile_velocity_rpm is not None:
        return joint.position_profile_velocity_rpm
    return DEFAULT_POSITION_PROFILE_VELOCITY_RPM

@dataclass(frozen=True)
class ArmConfig:
    serial_port: str
    baud_rate: int
    joints: Mapping[str, JointConfig]

@dataclass(frozen=True)
class MotionsConfig:
    poses: Mapping[str, Mapping[str, int]]

def _require_mapping(data: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a mapping.")
    return data

def _parse_joint(name: str, raw: Any) -> JointConfig:
    joint = _require_mapping(raw, label=f"joints.{name}")
    try:
        motor_id = int(joint["id"])
        model = str(joint["model"])
        protocol = int(joint.get("protocol", 2))
        limits = joint["position_limits"]
        current_limit = int(joint["current_limit"])
    except KeyError as exc:
        raise ValueError(f"joint {name!r} missing field: {exc}") from exc

    if not isinstance(limits, list) or len(limits) != 2:
        raise ValueError(f"joint {name!r} position_limits must be [min, max].")

    low, high = int(limits[0]), int(limits[1])
    if low > high:
        raise ValueError(f"joint {name!r} position_limits min must be <= max.")

    if protocol not in {1, 2}:
        raise ValueError(f"joint {name!r} protocol must be 1 or 2.")

    normalized_model = normalize_model(model)
    if normalized_model not in supported_models():
        known = ", ".join(supported_models())
        raise ValueError(f"joint {name!r} has unknown model {model!r}; known: {known}")

    profile_velocity_raw = joint.get("position_profile_velocity_rpm")
    position_profile_velocity_rpm: float | None
    if profile_velocity_raw is None:
        position_profile_velocity_rpm = None
    else:
        position_profile_velocity_rpm = float(profile_velocity_raw)
        if position_profile_velocity_rpm <= 0:
            raise ValueError(
                f"joint {name!r} position_profile_velocity_rpm must be positive."
            )

    return JointConfig(
        name=name,
        id=motor_id,
        model=model,
        protocol=protocol,
        position_limits=(low, high),
        current_limit=current_limit,
        position_profile_velocity_rpm=position_profile_velocity_rpm,
    )


def load_arm_config(path: Path | str = Path("config/arm.yaml")) -> ArmConfig:
    """Load the arm configuration from the YAML file.
    
    Args:
        path: The path to the YAML file. Defaults to the default configuration path.

    Returns:
        An ArmConfig object.
    """
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    document = _require_mapping(raw, label="arm config root")

    serial = _require_mapping(document.get("serial"), label="serial")
    try:
        serial_port = str(serial["port"])
        baud_rate = int(serial["baud_rate"])
    except KeyError as exc:
        raise ValueError(f"serial section missing field: {exc}") from exc

    joints_raw = _require_mapping(document.get("joints"), label="joints")
    if not joints_raw:
        raise ValueError("joints must contain at least one entry.")

    joints = {name: _parse_joint(name, value) for name, value in joints_raw.items()}

    seen_ids: dict[int, str] = {}
    for name, joint in joints.items():
        previous = seen_ids.get(joint.id)
        if previous is not None:
            raise ValueError(
                f"duplicate motor id {joint.id} on joints {previous!r} and {name!r}"
            )
        seen_ids[joint.id] = name

    return ArmConfig(serial_port=serial_port, baud_rate=baud_rate, joints=joints)


def load_motions_config(path: Path | str = Path("config/motions.yaml")) -> MotionsConfig:
    """Load the named poses from the YAML file.
    
    Args:
        path: The path to the YAML file. Defaults to the default configuration path.

    Returns:
        A MotionsConfig object.
    """
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    document = _require_mapping(raw, label="motions config root")

    poses_raw = document.get("poses")
    if poses_raw is None:
        return MotionsConfig(poses={})
    poses_section = _require_mapping(poses_raw, label="poses")

    poses: dict[str, dict[str, int]] = {}
    for pose_name, joints_raw in poses_section.items():
        joints = _require_mapping(joints_raw, label=f"poses.{pose_name}")
        poses[pose_name] = {joint: int(ticks) for joint, ticks in joints.items()}

    return MotionsConfig(poses=poses)

def resolve_pose(
    motions: MotionsConfig,
    pose_name: str,
    *,
    arm: ArmConfig,
) -> dict[str, int]:
    """Return the tick goals for the pose name, validating joint names against the arm.
    
    Args:
        motions: The motions configuration.
        pose_name: The name of the pose.
        arm: The arm configuration.

    Returns:
        A dictionary of the tick goals.
    """
    try:
        raw_pose = motions.poses[pose_name]
    except KeyError as exc:
        known = ", ".join(sorted(motions.poses))
        raise ValueError(f"unknown pose {pose_name!r}; known: {known}") from exc

    unknown = sorted(set(raw_pose) - set(arm.joints))
    if unknown:
        raise ValueError(f"pose {pose_name!r} references unknown joints: {unknown}")

    missing = sorted(set(arm.joints) - set(raw_pose))
    if missing:
        raise ValueError(f"pose {pose_name!r} missing joints: {missing}")

    out_of_range: list[str] = []
    for joint_name, ticks in raw_pose.items():
        low, high = arm.joints[joint_name].position_limits
        if ticks < low or ticks > high:
            out_of_range.append(f"{joint_name}={ticks} (limits [{low}, {high}])")
    if out_of_range:
        raise ValueError(f"pose {pose_name!r} has out-of-range ticks: {out_of_range}")

    return dict(raw_pose)
