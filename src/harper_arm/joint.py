from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from dynio import DynamixelIO, DynamixelMotor

from harper_arm import units
from harper_arm.config import ArmConfig, JointConfig, load_arm_config
from harper_arm.motor import connect_io, disconnect_io, new_motor

DEFAULT_CONFIG_PATH = Path("config/arm.yaml")


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

    def configure_velocity_mode(
        self,
        *,
        goal_current: int | None = None,
        enable_torque: bool = True,
    ) -> None:
        """Switch to velocity mode. Torque is disabled while mode registers are written."""
        with self.bus_lock:
            self.motor.torque_disable()
            self.motor.set_velocity_mode()
            if goal_current is not None and "Goal_Current" in self.motor.CONTROL_TABLE:
                self.motor.write_control_table("Goal_Current", goal_current)
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


