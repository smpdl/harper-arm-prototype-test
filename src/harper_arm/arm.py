from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dynio import DynamixelIO, DynamixelMotor

from harper_arm import units
from harper_arm.config import ArmConfig, load_arm_config, resolve_position_profile_velocity_rpm
from harper_arm.joint import DEFAULT_CONFIG_PATH, Joint, configure_joint_position_mode
from harper_arm.motor import connect_io, disconnect_io, new_motor
from harper_arm.safety import ensure_torque_enabled_all, torque_off_all
from harper_arm.sampling import JointSample, sample_joints


@dataclass
class FullArm:
    """All configured joints on one Dynamixel bus."""
    config: ArmConfig
    io: DynamixelIO
    motors: Mapping[str, DynamixelMotor]
    # this is a lock to syncronize access to the bus (e.g. reading/writing registers).
    # Read-Modify-Write operations should be atomic.
    bus_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

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
        with self.bus_lock:
            torque_off_all(self.motors)
        disconnect_io(self.io)

    def configure_position_mode(self) -> None:
        """Configure the position mode for all the joints."""
        with self.bus_lock:
            for name, motor in self.motors.items():
                motor.torque_disable()
                configure_joint_position_mode(motor, self.config.joints[name])

    def apply_position_profile_velocities(self) -> None:
        """Set Profile_Velocity on every joint from arm.yaml (or default)."""
        with self.bus_lock:
            for name, motor in self.motors.items():
                rpm = resolve_position_profile_velocity_rpm(self.config.joints[name])
                motor.set_velocity(units.rpm_to_velocity(rpm))

    def torque_enable_all(self) -> None:
        """Torque enable all the motors."""
        with self.bus_lock:
            ensure_torque_enabled_all(self.motors)

    def joint_view(self, joint_name: str) -> Joint:
        """
        Return a single-joint view that shares this bus connection.
        This was designed to be used for motion tests that need to operate on a single joint
        without needing to open a new serial connection.
        
        Args:
            joint_name: The name of the joint to return a view of.

        Returns:
            A Joint object that shares this bus connection.         
        """
        try:
            joint_cfg = self.config.joints[joint_name]
        except KeyError as exc:
            known = ", ".join(sorted(self.config.joints))
            raise ValueError(f"unknown joint {joint_name!r}; known: {known}") from exc
        return Joint(
            config=self.config,
            joint_name=joint_name,
            io=self.io,
            motor=self.motors[joint_name],
            joint=joint_cfg,
            bus_lock=self.bus_lock,
            _owns_bus=False, # this joint does not own the bus connection, it is shared with the full arm.
        )

    def prepare_motion_bus(
        self,
        *,
        joint_name: str,
        profile_velocity_rpm: float | None = None,
    ) -> None:
        """Configure position mode, profile speeds, and ensure torque on every motor."""
        self.configure_position_mode()
        self.apply_position_profile_velocities()
        if profile_velocity_rpm is not None:
            with self.bus_lock:
                self.motors[joint_name].set_velocity(
                    units.rpm_to_velocity(profile_velocity_rpm)
                )
        self.torque_enable_all()

    def joint_models(self) -> dict[str, str]:
        """Get the models of all the joints."""
        return {name: joint.model for name, joint in self.config.joints.items()}

    def current_limits(self) -> dict[str, int]:
        """Get the current limits of all the joints."""
        return {name: joint.current_limit for name, joint in self.config.joints.items()}

    def sample(self) -> dict[str, JointSample]:
        """Sample the joints."""
        with self.bus_lock:
            return sample_joints(self.motors)