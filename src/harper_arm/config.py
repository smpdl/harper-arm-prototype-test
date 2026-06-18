"""
Defines the configuration for the arm, including the joints, and the serial communication parameters.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from harper_arm import units
from harper_arm.motor import normalize_model, supported_models

DEFAULT_POSITION_PROFILE_VELOCITY_RPM = 23.0


def clamp_to_position_limits(min_tick: int, max_tick: int, target: int) -> int:
    """Clamp ``target`` to the inclusive range between semantic min and max ticks.

    ``min_tick`` and ``max_tick`` keep their recorded meaning even when the max
    tick value is numerically smaller than the min tick value.
    """
    if min_tick <= max_tick:
        return max(min_tick, min(target, max_tick))
    return max(max_tick, min(target, min_tick))


def target_within_position_limits(limits: tuple[int, int], target: int) -> bool:
    """Return whether ``target`` lies between semantic position limits."""
    min_tick, max_tick = limits
    return clamp_to_position_limits(min_tick, max_tick, target) == target


def limit_position_at_fraction(limits: tuple[int, int], fraction: float) -> int:
    """Return encoder ticks at ``fraction`` along semantic ``[min, max]`` limits."""
    min_tick, max_tick = limits
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be in [0, 1]")
    return int(round(min_tick + fraction * (max_tick - min_tick)))


def position_at_fraction_from_home(joint: JointConfig, fraction: float) -> int:
    """Return encoder ticks at ``fraction`` from home toward semantic limits.

    ``fraction`` is in ``[-1, 1]``: 0 = calibrated home, 1 = max, -1 = min.
    """
    if not -1.0 <= fraction <= 1.0:
        raise ValueError("fraction must be in [-1, 1]")
    home = require_home_position(joint)
    min_tick, max_tick = joint.position_limits
    if fraction >= 0:
        return int(round(home + fraction * (max_tick - home)))
    return int(round(home + fraction * (home - min_tick)))


def offset_ticks_toward_max(
    limits: tuple[int, int],
    start_ticks: int,
    delta_deg: float,
) -> int:
    """Return a tick target ``delta_deg`` toward semantic max from ``start_ticks``."""
    min_tick, max_tick = limits
    toward_max_sign = 1 if max_tick >= min_tick else -1
    goal = start_ticks + toward_max_sign * units.degrees_to_ticks(delta_deg)
    return clamp_to_position_limits(min_tick, max_tick, goal)

@dataclass(frozen=True)
class JointConfig:
    name: str
    id: int
    model: str
    protocol: int
    position_limits: tuple[int, int]
    current_limit: int
    home_position: int | None = None
    calibrated: bool = False
    direction: int = 1
    position_profile_velocity_rpm: float | None = None
    position_profile_acceleration_rpm2: float | None = None


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


def resolve_position_profile_acceleration_rpm2(
    joint: JointConfig,
    *,
    override_rpm2: float | None = None,
) -> float | None:
    """Return profile acceleration, or None to leave the register unchanged."""
    if override_rpm2 is not None:
        return override_rpm2 if override_rpm2 > 0 else None
    return joint.position_profile_acceleration_rpm2


def require_home_position(joint: JointConfig) -> int:
    """Return a joint's calibrated home position or fail with an actionable error."""
    if joint.home_position is None:
        raise ValueError(
            f"joint {joint.name!r} is missing home_position; calibrate it before "
            "running home-relative motion tests"    
        )
    return joint.home_position


def require_joint_calibrated(joint: JointConfig) -> None:
    """Reject motion when a joint has not been saved from a calibration session."""
    if not joint.calibrated:
        raise ValueError(
            f"joint {joint.name!r} is not calibrated; complete calibration and save "
            "before running motion tests"
        )
    require_home_position(joint)


def require_arm_calibrated(
    arm: ArmConfig,
    *,
    joint_names: tuple[str, ...] | None = None,
) -> None:
    """Reject motion when any requested joint lacks a saved calibration."""
    names = joint_names or tuple(arm.joints)
    unknown = sorted(set(names) - set(arm.joints))
    if unknown:
        raise ValueError(f"unknown joints requested for calibration check: {unknown}")
    uncalibrated = [name for name in names if not arm.joints[name].calibrated]
    if uncalibrated:
        joined = ", ".join(uncalibrated)
        raise ValueError(
            f"uncalibrated joints: {joined}; calibrate and save every joint before "
            "running motion tests"
        )
    for name in names:
        require_home_position(arm.joints[name])

@dataclass(frozen=True)
class ArmConfig:
    serial_port: str
    baud_rate: int
    joints: Mapping[str, JointConfig]

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

    home_raw = joint.get("home_position")
    home_position: int | None
    if home_raw is None:
        home_position = None
    else:
        home_position = int(home_raw)

    calibrated = bool(joint.get("calibrated", False))
    if calibrated and home_position is None:
        raise ValueError(
            f"joint {name!r} is marked calibrated but home_position is missing"
        )

    # direction is the sign of positive degrees for higher-level tests. 
    direction = int(joint.get("direction", 1))
    if direction not in {-1, 1}:
        raise ValueError(f"joint {name!r} direction must be -1 or 1.")

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

    profile_accel_raw = joint.get("position_profile_acceleration_rpm2")
    position_profile_acceleration_rpm2: float | None
    if profile_accel_raw is None:
        position_profile_acceleration_rpm2 = None
    else:
        position_profile_acceleration_rpm2 = float(profile_accel_raw)
        if position_profile_acceleration_rpm2 <= 0:
            raise ValueError(
                f"joint {name!r} position_profile_acceleration_rpm2 must be positive."
            )

    return JointConfig(
        name=name,
        id=motor_id,
        model=model,
        protocol=protocol,
        position_limits=(low, high),
        current_limit=current_limit,
        home_position=home_position,
        calibrated=calibrated,
        direction=direction,
        position_profile_velocity_rpm=position_profile_velocity_rpm,
        position_profile_acceleration_rpm2=position_profile_acceleration_rpm2,
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


def joint_names_sorted_by_motor_id(arm: ArmConfig) -> tuple[str, ...]:
    """Return joint names ordered by ascending Dynamixel motor ID."""
    return tuple(
        name for name, _ in sorted(arm.joints.items(), key=lambda item: item[1].id)
    )


def resolve_home_pose(
    arm: ArmConfig,
    *,
    joint_names: tuple[str, ...] | None = None,
) -> dict[str, int]:
    """Return calibrated home ticks for the requested joints."""
    names = joint_names or joint_names_sorted_by_motor_id(arm)
    unknown = sorted(set(names) - set(arm.joints))
    if unknown:
        raise ValueError(f"unknown joints requested for home pose: {unknown}")
    return {name: require_home_position(arm.joints[name]) for name in names}
