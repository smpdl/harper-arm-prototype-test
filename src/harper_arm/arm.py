"""Aggregate abstraction across all configured joints."""

from __future__ import annotations

from collections.abc import Mapping

from .bus import DynamixelBus
from .config import ArmConfig
from .joint import Joint, JointSample


class Arm:
    def __init__(self, joints: dict[str, Joint]) -> None:
        self._joints = joints

    @classmethod
    def from_config(cls, bus: DynamixelBus, config: ArmConfig) -> "Arm":
        bus.connect()
        joints: dict[str, Joint] = {}
        for name, joint_config in config.joints.items():
            motor = bus.new_motor_for_joint(joint_config)
            joints[name] = Joint(config=joint_config, motor=motor)
        return cls(joints=joints)

    def joint_names(self) -> tuple[str, ...]:
        return tuple(self._joints.keys())

    def get_joint(self, name: str) -> Joint:
        try:
            return self._joints[name]
        except KeyError as exc:
            known = ", ".join(self._joints.keys())
            raise KeyError(f"Unknown joint '{name}'. Known joints: {known}") from exc

    def ping_all(self) -> dict[str, bool]:
        return {name: joint.ping() for name, joint in self._joints.items()}

    def sample_all(self) -> dict[str, JointSample]:
        return {name: joint.sample_state() for name, joint in self._joints.items()}

    def read_all_present_position(self) -> dict[str, int]:
        return {name: joint.read_present_position() for name, joint in self._joints.items()}

    def read_all_present_velocity(self) -> dict[str, int]:
        return {name: joint.read_present_velocity() for name, joint in self._joints.items()}

    def read_all_present_current(self) -> dict[str, int]:
        return {name: joint.read_present_current() for name, joint in self._joints.items()}

    def read_all_present_temperature(self) -> dict[str, int]:
        return {name: joint.read_present_temperature() for name, joint in self._joints.items()}

    def read_all_present_voltage(self) -> dict[str, int]:
        return {name: joint.read_present_voltage() for name, joint in self._joints.items()}

    def move_joints(self, goal_positions: Mapping[str, int]) -> None:
        self._validate_joint_names(goal_positions)
        for name, position in goal_positions.items():
            self._joints[name].set_goal_position(position)

    def execute_named_pose(self, pose: Mapping[str, int]) -> None:
        self.move_joints(pose)

    def _validate_joint_names(self, values: Mapping[str, int]) -> None:
        unknown = [name for name in values if name not in self._joints]
        if unknown:
            raise KeyError(f"Unknown joints in command: {', '.join(unknown)}")
