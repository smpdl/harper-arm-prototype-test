from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dynio import DynamixelIO, DynamixelMotor

from harper_arm import units
from harper_arm.config import ArmConfig, JointConfig, clamp_to_position_limits, load_arm_config
from harper_arm.motor import connect_io, disconnect_io, new_motor

DEFAULT_CONFIG_PATH = Path("config/arm.yaml")

CURRENT_CONTROL_MODE = 0
PWM_CONTROL_MODE = 16

def _read_register(motor: DynamixelMotor, name: str) -> int:
    return int(motor.read_control_table(name))


def _require_register(
    motor: DynamixelMotor,
    name: str,
    expected: int,
    *,
    joint_name: str,
) -> None:
    actual = _read_register(motor, name)
    if actual != expected:
        raise RuntimeError(
            f"{joint_name}: failed to set {name} to {expected} (read back {actual})"
        )


def apply_motor_position_profile(
    motor: DynamixelMotor,
    *,
    velocity_rpm: float,
    acceleration_rpm2: float | None = None,
) -> None:
    """Configure Profile_Velocity and optionally Profile_Acceleration.

    When ``acceleration_rpm2`` is a positive value, the servo uses a trapezoidal
    velocity-based profile (both registers non-zero). When it is ``None``, only
    Profile_Velocity is written and acceleration is left unchanged. When it is
    ``0``, Profile_Acceleration is cleared for a rectangular profile.
    """
    motor.set_velocity(units.rpm_to_velocity(velocity_rpm))
    if acceleration_rpm2 is None:
        return
    motor.set_acceleration(
        0 if acceleration_rpm2 <= 0 else units.rpm2_to_acceleration(acceleration_rpm2)
    )


def configure_joint_position_mode(motor: DynamixelMotor, joint: JointConfig) -> None:
    """Configure the joint in position mode.

    If the joint's position limits are outside the range of 0 to 4095,
    the joint is configured in extended position mode. Otherwise, it is
    configured in single-turn position mode.

    Args:
        motor: The motor to configure.
        joint: The joint to configure.
    """
    min_tick, max_tick = joint.position_limits
    if min(min_tick, max_tick) < 0 or max(min_tick, max_tick) > 4095:
        motor.set_extended_position_mode()
    else:
        # Dynamixel registers require numeric min <= max; semantic labels are unchanged in config.
        motor.set_position_mode(
            min_limit=min(min_tick, max_tick),
            max_limit=max(min_tick, max_tick),
        )


@dataclass
class Joint:
    config: ArmConfig
    joint_name: str
    io: DynamixelIO
    motor: DynamixelMotor
    joint: JointConfig
    bus_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _owns_bus: bool = field(default=True, repr=False) 

    @classmethod
    def open(
        cls,
        *,
        joint_name: str,
        config_path: Path | str = DEFAULT_CONFIG_PATH,
    ) -> Joint:
        config = load_arm_config(config_path)
        try:
            joint = config.joints[joint_name]
        except KeyError as exc:
            known = ", ".join(sorted(config.joints))
            raise ValueError(f"unknown joint {joint_name!r}; known: {known}") from exc

        io = connect_io(config.serial_port, config.baud_rate)
        motor = new_motor(io, joint.id, joint.model, protocol=joint.protocol)
        return cls(config=config, joint_name=joint_name, io=io, motor=motor, joint=joint)

    def close(self) -> None:
        if not self._owns_bus:
            return
        with self.bus_lock:
            try:
                self.motor.torque_disable()
            except Exception:
                pass
        disconnect_io(self.io)

    def configure_position_mode(self) -> None:
        with self.bus_lock:
            self.motor.torque_disable()
            configure_joint_position_mode(self.motor, self.joint)

    def set_position_profile_rpm(
        self,
        velocity_rpm: float,
        *,
        acceleration_rpm2: float | None = None,
    ) -> None:
        """Set position-mode profile registers (trapezoidal when acceleration is set)."""
        with self.bus_lock:
            apply_motor_position_profile(
                self.motor,
                velocity_rpm=velocity_rpm,
                acceleration_rpm2=acceleration_rpm2,
            )

    def set_profile_velocity_rpm(self, rpm: float) -> None:
        """Set Profile_Velocity for position-mode moves (lower rpm = slower motion)."""
        self.set_position_profile_rpm(rpm)

    def configure_velocity_mode(self, *, enable_torque: bool = True) -> None:
        """Switch to velocity mode. Torque is disabled while mode registers are written."""
        with self.bus_lock:
            self.motor.torque_disable()
            self.motor.set_velocity_mode()
            if enable_torque:
                self.motor.torque_enable()

    def torque_enable(self) -> None:
        with self.bus_lock:
            self.motor.torque_enable()

    def torque_disable(self) -> None:
        with self.bus_lock:
            self.motor.torque_disable()

    def get_position(self) -> int:
        with self.bus_lock:
            return int(self.motor.get_position())

    def set_velocity(self, velocity: int) -> None:
        with self.bus_lock:
            self.motor.set_velocity(velocity)

    def read_present_velocity(self) -> int:
        with self.bus_lock:
            return int(self.motor.read_control_table("Present_Velocity"))


