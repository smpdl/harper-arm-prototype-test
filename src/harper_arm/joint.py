from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dynio import DynamixelIO, DynamixelMotor

from harper_arm import units
from harper_arm.config import ArmConfig, JointConfig, load_arm_config
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


def configure_joint_position_mode(motor: DynamixelMotor, joint: JointConfig) -> None:
    """Configure the joint in position mode.

    If the joint's position limits are outside the range of 0 to 4095,
    the joint is configured in extended position mode. Otherwise, it is
    configured in single-turn position mode.

    Args:
        motor: The motor to configure.
        joint: The joint to configure.
    """
    low, high = joint.position_limits
    if low < 0 or high > 4095:
        motor.set_extended_position_mode()
    else:
        motor.set_position_mode(min_limit=low, max_limit=high)


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

    def set_profile_velocity_rpm(self, rpm: float) -> None:
        """Set Profile_Velocity for position-mode moves (lower rpm = slower motion)."""
        with self.bus_lock:
            self.motor.set_velocity(units.rpm_to_velocity(rpm))

    def configure_velocity_mode(self, *, enable_torque: bool = True) -> None:
        """Switch to velocity mode. Torque is disabled while mode registers are written."""
        with self.bus_lock:
            self.motor.torque_disable()
            self.motor.set_velocity_mode()
            if enable_torque:
                self.motor.torque_enable()

    def apply_thermal_load(self, *, load_fraction: float) -> Mapping[str, Any]:
        """Apply sustained load at ``load_fraction`` of arm.yaml ``current_limit``.

        XM/XC motors use current control mode (Goal Current). XL430 uses PWM mode
        because it has no Goal Current register.
        """
        if not 0 < load_fraction <= 1:
            raise ValueError("load_fraction must be in (0, 1].")

        with self.bus_lock:
            self.motor.torque_disable()
            if "Hardware_Error_Status" in self.motor.CONTROL_TABLE:
                error = _read_register(self.motor, "Hardware_Error_Status")
                if error:
                    raise RuntimeError(
                        f"{self.joint_name}: hardware error status 0x{error:02x}; "
                        "power-cycle the motor before running thermal rise"
                    )
            table = self.motor.CONTROL_TABLE

            if "Goal_Current" in table:
                goal_current = int(round(self.joint.current_limit * load_fraction))
                self.motor.write_control_table("Operating_Mode", CURRENT_CONTROL_MODE)
                self.motor.torque_enable()
                self.motor.write_control_table("Goal_Current", goal_current)
                _require_register(
                    self.motor,
                    "Operating_Mode",
                    CURRENT_CONTROL_MODE,
                    joint_name=self.joint_name,
                )
                _require_register(
                    self.motor,
                    "Torque_Enable",
                    1,
                    joint_name=self.joint_name,
                )
                _require_register(
                    self.motor,
                    "Goal_Current",
                    goal_current,
                    joint_name=self.joint_name,
                )
                return {"mode": "current", "goal_current": goal_current}

            if "Goal_PWM" in table:
                pwm_limit = int(self.motor.read_control_table("PWM_Limit"))
                goal_pwm = int(round(load_fraction * pwm_limit))
                self.motor.write_control_table("Operating_Mode", PWM_CONTROL_MODE)
                self.motor.torque_enable()
                self.motor.write_control_table("Goal_PWM", goal_pwm)
                _require_register(
                    self.motor,
                    "Operating_Mode",
                    PWM_CONTROL_MODE,
                    joint_name=self.joint_name,
                )
                _require_register(
                    self.motor,
                    "Torque_Enable",
                    1,
                    joint_name=self.joint_name,
                )
                _require_register(
                    self.motor,
                    "Goal_PWM",
                    goal_pwm,
                    joint_name=self.joint_name,
                )
                return {
                    "mode": "pwm",
                    "goal_pwm": goal_pwm,
                    "pwm_limit": pwm_limit,
                }

            raise RuntimeError(
                f"joint {self.joint_name!r} ({self.joint.model}) does not support thermal load"
            )

    def release_thermal_load(self) -> None:
        with self.bus_lock:
            table = self.motor.CONTROL_TABLE
            if "Goal_Current" in table:
                self.motor.write_control_table("Goal_Current", 0)
            elif "Goal_PWM" in table:
                self.motor.write_control_table("Goal_PWM", 0)

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


