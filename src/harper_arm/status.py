"""Motor register snapshots for live status displays."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from dynio import DynamixelMotor

from harper_arm import units
from harper_arm.motor import (
    read_control_table_safe,
    read_present_current_safe,
    read_present_position,
)

if TYPE_CHECKING:
    from harper_arm.joint import Joint

_OPERATING_MODES: dict[int, str] = {
    0: "current",
    1: "velocity",
    3: "position",
    4: "extended position",
    5: "current-based position",
    16: "pwm",
}

_HARDWARE_ERROR_BITS: tuple[tuple[int, str], ...] = (
    (0x01, "input voltage"),
    (0x02, "overheating"),
    (0x04, "motor encoder"),
    (0x08, "electrical shock"),
    (0x10, "overload"),
)


@dataclass(frozen=True)
class MotorStatus:
    timestamp: datetime
    joint: str
    motor_id: int
    model: str
    position: int
    velocity: int
    current: int
    temperature: int
    voltage: int
    goal_position: int | None
    goal_velocity: int | None
    goal_current: int | None
    torque_enabled: bool | None
    moving: bool | None
    hardware_error: int | None
    operating_mode: int | None

    @property
    def position_deg(self) -> float:
        return units.ticks_to_degrees(self.position)

    @property
    def velocity_rpm(self) -> float:
        return units.velocity_to_rpm(self.velocity)

    @property
    def current_ma(self) -> float:
        return units.current_to_ma(self.current, model=self.model)

    @property
    def temperature_c(self) -> float:
        return units.temperature_to_celsius(self.temperature)

    @property
    def voltage_v(self) -> float:
        return units.voltage_to_volts(self.voltage)


def _safe_read_int(motor: DynamixelMotor, register: str) -> int | None:
    return read_control_table_safe(motor, register)


def _safe_read_int_signed(motor: DynamixelMotor, register: str) -> int | None:
    value = _safe_read_int(motor, register)
    if value is None:
        return None
    if register in {"Present_Position", "Goal_Position"}:
        return units.decode_position_ticks(value)
    return value


def _motor_status_unlocked(connected_joint: Joint) -> MotorStatus:
    """Build a status snapshot. Caller must hold ``connected_joint.bus_lock``."""
    motor = connected_joint.motor
    joint_cfg = connected_joint.joint

    torque_raw = _safe_read_int(motor, "Torque_Enable")
    moving_raw = _safe_read_int(motor, "Moving")
    velocity = _safe_read_int(motor, "Present_Velocity")
    current = read_present_current_safe(motor)
    temperature = _safe_read_int(motor, "Present_Temperature")
    voltage = _safe_read_int(motor, "Present_Input_Voltage")

    return MotorStatus(
        timestamp=datetime.now(),
        joint=connected_joint.joint_name,
        motor_id=joint_cfg.id,
        model=joint_cfg.model,
        position=read_present_position(motor),
        velocity=0 if velocity is None else velocity,
        current=0 if current is None else current,
        temperature=0 if temperature is None else temperature,
        voltage=0 if voltage is None else voltage,
        goal_position=_safe_read_int_signed(motor, "Goal_Position"),
        goal_velocity=_safe_read_int(motor, "Goal_Velocity"),
        goal_current=_safe_read_int(motor, "Goal_Current"),
        torque_enabled=None if torque_raw is None else bool(torque_raw),
        moving=None if moving_raw is None else bool(moving_raw),
        hardware_error=_safe_read_int(motor, "Hardware_Error_Status"),
        operating_mode=_safe_read_int(motor, "Operating_Mode"),
    )


def read_motor_status(connected_joint: Joint) -> MotorStatus:
    """Read present and goal registers from a connected joint."""
    with connected_joint.bus_lock:
        return _motor_status_unlocked(connected_joint)


def read_joint_live(connected_joint: Joint) -> tuple[int, MotorStatus]:
    """Read position and status in one bus transaction group."""
    with connected_joint.bus_lock:
        status = _motor_status_unlocked(connected_joint)
        return status.position, status


def format_hardware_error(code: int | None) -> str:
    if code is None:
        return "NA"
    if code == 0:
        return "OK"
    labels = [label for bit, label in _HARDWARE_ERROR_BITS if code & bit]
    return ", ".join(labels) if labels else f"0x{code:02x}"


def format_operating_mode(mode: int | None) -> str:
    if mode is None:
        return "NA"
    label = _OPERATING_MODES.get(mode)
    if label is None:
        return str(mode)
    return f"{mode} ({label})"


def format_on_off(value: bool | None) -> str:
    if value is None:
        return "NA"
    return "ON" if value else "OFF"


def format_yes_no(value: bool | None) -> str:
    if value is None:
        return "NA"
    return "yes" if value else "no"
