"""Single-joint abstraction for command + telemetry access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .config import JointConfig


@dataclass(frozen=True) # immutable data class
class JointSample:
    timestamp: datetime
    joint: str
    position: int
    velocity: int
    current: int
    temperature: int
    voltage: int


class Joint:
    def __init__(self, config: JointConfig, motor: object) -> None:
        self.config = config
        self.motor = motor

    @property
    def name(self) -> str:
        return self.config.name

    def ping(self) -> bool:
        return bool(self._read("Model_Number"))

    def read_present_voltage(self) -> int:
        return int(self._read("Present_Input_Voltage"))

    def read_present_temperature(self) -> int:
        return int(self._read("Present_Temperature"))

    def read_present_current(self) -> int:
        return int(self.motor.get_current())

    def read_present_position(self) -> int:
        return int(self._read("Present_Position"))

    def read_present_velocity(self) -> int:
        return int(self._read("Present_Velocity"))

    def set_goal_position(self, raw_ticks: int) -> None:
        low, high = self.config.position_limits
        if raw_ticks < low or raw_ticks > high:
            raise ValueError(
                f"Requested goal position {raw_ticks} outside limits [{low}, {high}] "
                f"for joint '{self.name}'."
            )
        self.motor.set_position(raw_ticks)

    def set_goal_velocity(self, raw_units: int) -> None:
        self.motor.set_velocity(raw_units)

    def set_position_mode(self) -> None:
        self.motor.set_position_mode(
            min_limit=self.config.position_limits[0],
            max_limit=self.config.position_limits[1],
        )

    def set_velocity_mode(self) -> None:
        self.motor.set_velocity_mode()

    def torque_enable(self, enable: bool) -> None:
        if enable:
            self.motor.torque_enable()
        else:
            self.motor.torque_disable()

    def sample_state(self) -> JointSample:
        return JointSample(
            timestamp=datetime.now(UTC),
            joint=self.name,
            position=self.read_present_position(),
            velocity=self.read_present_velocity(),
            current=self.read_present_current(),
            temperature=self.read_present_temperature(),
            voltage=self.read_present_voltage(),
        )

    def _read(self, register_name: str) -> int:
        return int(self.motor.read_control_table(register_name))
