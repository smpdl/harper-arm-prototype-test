from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from dynio import DynamixelIO, DynamixelMotor

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
        try:
            self.motor.torque_disable()
        except Exception:
            pass
        disconnect_io(self.io)

    def configure_position_mode(self) -> None:
        configure_joint_position_mode(self.motor, self.joint)

    def configure_velocity_mode(self, *, goal_current: int | None = None) -> None:
        self.motor.set_velocity_mode(goal_current=goal_current)


