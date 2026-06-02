"""Config loading and validation for the arm definition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_MODEL_FAMILIES = ("xc330", "xl430", "xm430", "xm540")


class ConfigError(Exception):
    """Base class for config-layer failures."""


class ConfigValidationError(ConfigError):
    """Raised when the arm config is missing keys or has invalid values."""


@dataclass(frozen=True)
class SerialConfig:
    port: str
    baud_rate: int


@dataclass(frozen=True)
class JointConfig:
    name: str
    id: int
    model: str
    protocol: int
    position_limits: tuple[int, int]
    current_limit: int

    @property
    def model_family(self) -> str:
        return model_to_family(self.model)


@dataclass(frozen=True)
class ArmConfig:
    serial: SerialConfig
    joints: dict[str, JointConfig]


def load_arm_config(path: str | Path) -> ArmConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file does not exist: {config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse YAML config: {config_path}") from exc

    if not isinstance(raw, dict):
        raise ConfigValidationError("Top-level config must be a mapping.")

    serial = _parse_serial(raw.get("serial"))
    joints = _parse_joints(raw.get("joints"))
    return ArmConfig(serial=serial, joints=joints)


def model_to_family(model: str) -> str:
    normalized = model.strip().lower().replace("_", "-")
    prefix = normalized.split("-", maxsplit=1)[0]
    if prefix not in SUPPORTED_MODEL_FAMILIES:
        supported = ", ".join(SUPPORTED_MODEL_FAMILIES)
        raise ConfigValidationError(
            f"Unsupported model '{model}'. Expected one of: {supported}."
        )
    return prefix


def _parse_serial(raw_serial: Any) -> SerialConfig:
    if not isinstance(raw_serial, dict):
        raise ConfigValidationError("serial must be a mapping.")

    port = raw_serial.get("port")
    baud_rate = raw_serial.get("baud_rate")
    if not isinstance(port, str) or not port.strip():
        raise ConfigValidationError("serial.port must be a non-empty string.")
    if not isinstance(baud_rate, int) or baud_rate <= 0:
        raise ConfigValidationError("serial.baud_rate must be a positive integer.")

    return SerialConfig(port=port.strip(), baud_rate=baud_rate)


def _parse_joints(raw_joints: Any) -> dict[str, JointConfig]:
    if not isinstance(raw_joints, dict) or not raw_joints:
        raise ConfigValidationError("joints must be a non-empty mapping.")

    parsed: dict[str, JointConfig] = {}
    seen_ids: set[int] = set()

    for joint_name, joint_values in raw_joints.items():
        if not isinstance(joint_name, str) or not joint_name:
            raise ConfigValidationError("All joint names must be non-empty strings.")
        if not isinstance(joint_values, dict):
            raise ConfigValidationError(f"Joint '{joint_name}' config must be a mapping.")

        joint_id = joint_values.get("id")
        if not isinstance(joint_id, int) or joint_id <= 0:
            raise ConfigValidationError(f"Joint '{joint_name}' has invalid id.")
        if joint_id in seen_ids:
            raise ConfigValidationError(f"Duplicate motor id detected: {joint_id}")
        seen_ids.add(joint_id)

        model = joint_values.get("model")
        if not isinstance(model, str) or not model.strip():
            raise ConfigValidationError(f"Joint '{joint_name}' has invalid model.")
        model_to_family(model)

        protocol = joint_values.get("protocol", 2)
        if not isinstance(protocol, int) or protocol <= 0:
            raise ConfigValidationError(f"Joint '{joint_name}' has invalid protocol.")

        limits = joint_values.get("position_limits")
        if (
            not isinstance(limits, list)
            or len(limits) != 2
            or not all(isinstance(x, int) for x in limits)
            or limits[0] >= limits[1]
        ):
            raise ConfigValidationError(
                f"Joint '{joint_name}' position_limits must be [min, max] with min < max."
            )

        current_limit = joint_values.get("current_limit")
        if not isinstance(current_limit, int) or current_limit <= 0:
            raise ConfigValidationError(
                f"Joint '{joint_name}' current_limit must be a positive integer."
            )

        parsed[joint_name] = JointConfig(
            name=joint_name,
            id=joint_id,
            model=model.strip().lower(),
            protocol=protocol,
            position_limits=(limits[0], limits[1]),
            current_limit=current_limit,
        )

    return parsed
