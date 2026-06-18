"""Motor register snapshots for live status displays."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from dynio import DynamixelMotor

from harper_arm import units
from harper_arm.motor import read_registers_bulk

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

_STATUS_REGISTERS: tuple[str, ...] = (
    "Torque_Enable",
    "Moving",
    "Present_Velocity",
    "Present_Temperature",
    "Present_Input_Voltage",
    "Present_Position",
    "Goal_Position",
    "Goal_Velocity",
    "Hardware_Error_Status",
    "Operating_Mode",
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


def _present_current_register(motor: DynamixelMotor) -> str | None:
    table = motor.CONTROL_TABLE
    if "Present_Current" in table:
        return "Present_Current"
    if "Present_Load" in table:
        return "Present_Load"
    return None


def _goal_current_register(motor: DynamixelMotor) -> str | None:
    table = motor.CONTROL_TABLE
    if "Goal_Current" in table:
        return "Goal_Current"
    return None


def _status_registers_for_motor(motor: DynamixelMotor) -> tuple[str, ...]:
    registers = list(_STATUS_REGISTERS)
    present_current = _present_current_register(motor)
    if present_current is not None:
        registers.insert(3, present_current)
    goal_current = _goal_current_register(motor)
    if goal_current is not None:
        registers.insert(8, goal_current)
    return tuple(registers)


def _decode_position(raw: int | None) -> int | None:
    if raw is None:
        return None
    return units.decode_position_ticks(raw)


def _motor_status_unlocked(connected_joint: Joint) -> MotorStatus:
    """Build a status snapshot. Caller must hold ``connected_joint.bus_lock``."""
    motor = connected_joint.motor
    joint_cfg = connected_joint.joint
    present_current_reg = _present_current_register(motor)
    goal_current_reg = _goal_current_register(motor)

    values = read_registers_bulk(
        connected_joint.io,
        motor,
        _status_registers_for_motor(motor),
    )

    position_raw = values.get("Present_Position")
    if position_raw is None:
        raise RuntimeError("failed to read Present_Position")

    velocity = values.get("Present_Velocity")
    current_raw = values.get(present_current_reg) if present_current_reg else None
    temperature = values.get("Present_Temperature")
    voltage = values.get("Present_Input_Voltage")
    torque_raw = values.get("Torque_Enable")
    moving_raw = values.get("Moving")

    return MotorStatus(
        timestamp=datetime.now(),
        joint=connected_joint.joint_name,
        motor_id=joint_cfg.id,
        model=joint_cfg.model,
        position=units.decode_position_ticks(position_raw),
        velocity=0 if velocity is None else velocity,
        current=0 if current_raw is None else current_raw,
        temperature=0 if temperature is None else temperature,
        voltage=0 if voltage is None else voltage,
        goal_position=_decode_position(values.get("Goal_Position")),
        goal_velocity=values.get("Goal_Velocity"),
        goal_current=values.get(goal_current_reg) if goal_current_reg else None,
        torque_enabled=None if torque_raw is None else bool(torque_raw),
        moving=None if moving_raw is None else bool(moving_raw),
        hardware_error=values.get("Hardware_Error_Status"),
        operating_mode=values.get("Operating_Mode"),
    )


def read_motor_status(connected_joint: Joint) -> MotorStatus:
    """Read present and goal registers from a connected joint."""
    with connected_joint.bus_lock:
        return _motor_status_unlocked(connected_joint)


def read_joint_live(connected_joint: Joint) -> tuple[int, MotorStatus]:
    """Read position and status in one bulk bus transaction."""
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
