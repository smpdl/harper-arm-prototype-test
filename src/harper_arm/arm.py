from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dynio import DynamixelIO, DynamixelMotor

from harper_arm.config import ArmConfig, load_arm_config
from harper_arm.joint import DEFAULT_CONFIG_PATH, configure_joint_position_mode
from harper_arm.motor import connect_io, disconnect_io, new_motor
from harper_arm.safety import torque_off_all
from harper_arm.sampling import JointSample, sample_joints


@dataclass
class FullArm:
    """All configured joints on one Dynamixel bus."""
    config: ArmConfig
    io: DynamixelIO
    motors: Mapping[str, DynamixelMotor]

    @classmethod
    def open(cls, *, config_path: Path | str = DEFAULT_CONFIG_PATH) -> FullArm:
        """Open the arm.

        Args:
            config_path: Path to the arm configuration file. Defaults to
                ``DEFAULT_CONFIG_PATH``.

        Returns:
            A FullArm object.
        """

        config = load_arm_config(config_path) 
        io = connect_io(config.serial_port, config.baud_rate)
        motors = {
            name: new_motor(io, joint.id, joint.model, protocol=joint.protocol)
            for name, joint in config.joints.items()
        }
        return cls(config=config, io=io, motors=motors)

    def close(self) -> None:
        """Close the arm.

        This function will torque off all the motors.
        """
        torque_off_all(self.motors)
        disconnect_io(self.io)

    def configure_position_mode(self) -> None:
        """Configure the position mode for all the joints."""
        for name, motor in self.motors.items():
            configure_joint_position_mode(motor, self.config.joints[name])

    def torque_enable_all(self) -> None:
        """Torque enable all the motors."""
        for motor in self.motors.values():
            motor.torque_enable()

    def joint_models(self) -> dict[str, str]:
        """Get the models of all the joints."""
        return {name: joint.model for name, joint in self.config.joints.items()}

    def current_limits(self) -> dict[str, int]:
        """Get the current limits of all the joints."""
        return {name: joint.current_limit for name, joint in self.config.joints.items()}

    def sample(self) -> dict[str, JointSample]:
        """Sample the joints."""
        return sample_joints(self.motors)



