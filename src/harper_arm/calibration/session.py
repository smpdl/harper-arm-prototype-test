"""Per-joint calibration state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from harper_arm.config import clamp_to_position_limits


@dataclass
class JointCalibration:
    """Recorded encoder positions for one joint."""

    joint_name: str
    min_position: int | None = None
    home_position: int | None = None
    max_position: int | None = None

    def record_min(self, ticks: int) -> None:
        self.min_position = ticks

    def record_home(self, ticks: int) -> None:
        self.home_position = ticks

    def record_max(self, ticks: int) -> None:
        self.max_position = ticks

    def is_complete(self) -> bool:
        return (
            self.min_position is not None
            and self.home_position is not None
            and self.max_position is not None
        )

    def span_ticks(self) -> int | None:
        if self.min_position is None or self.max_position is None:
            return None
        return self.max_position - self.min_position

    def position_at_fraction(self, fraction: float) -> int:
        """
        Calculate the position at a given fraction of the span.

        Fraction is a float between 0 and 1, where 0 is the min position and 1 is the max position.
        """
        if self.min_position is None or self.max_position is None:
            raise ValueError(f"joint {self.joint_name!r} min/max not recorded")
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("fraction must be in [0, 1]")
        span = self.max_position - self.min_position
        return int(round(self.min_position + fraction * span))

    def clamp_target(self, target_ticks: int) -> int:
        """Clamp a jog target to operator-confirmed limits when recorded."""
        min_tick = self.min_position
        max_tick = self.max_position
        if min_tick is not None and max_tick is not None:
            return clamp_to_position_limits(min_tick, max_tick, target_ticks)
        return target_ticks

    def to_dict(self) -> dict[str, Any]:
        return {
            "joint_name": self.joint_name,
            "min_position": self.min_position,
            "home_position": self.home_position,
            "max_position": self.max_position,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JointCalibration:
        return cls(
            joint_name=str(data["joint_name"]),
            min_position=_optional_int(data.get("min_position")),
            home_position=_optional_int(data.get("home_position")),
            max_position=_optional_int(data.get("max_position")),
        )

@dataclass
class CalibrationSession:
    """Calibration progress for one or more joints."""

    joints: dict[str, JointCalibration] = field(default_factory=dict)

    def joint(self, joint_name: str) -> JointCalibration:
        if joint_name not in self.joints:
            self.joints[joint_name] = JointCalibration(joint_name=joint_name)
        return self.joints[joint_name]

    def to_dict(self) -> dict[str, Any]:
        return {
            "joints": {
                name: joint.to_dict() for name, joint in sorted(self.joints.items())
            }
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CalibrationSession:
        joints_raw = data.get("joints", {})
        if not isinstance(joints_raw, dict):
            raise ValueError("session joints must be a mapping.")
        joints = {
            name: JointCalibration.from_dict({"joint_name": name, **value})
            if isinstance(value, dict)
            else JointCalibration(joint_name=name)
            for name, value in joints_raw.items()
        }
        return cls(joints=joints)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("position value must be an integer, not bool")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value)
    raise ValueError(f"position value must be numeric, got {type(value).__name__}")
