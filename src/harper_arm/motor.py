"""Dynamixel motor helpers."""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping

from dynio import DynamixelIO, DynamixelMotor
from dynio.group_io import resolve_sync_register

from harper_arm import units

MOVE_TIMEOUT_S = 10.0
POSITION_TOLERANCE_TICKS = 10
SETTLE_POLL_INTERVAL_S = 0.02
SETTLE_STABLE_POLLS = 3


_MODELS = {
    "xc330-m288-t": "new_xc330m288t",
    "xl430-w250-t": "new_xl430w250t",
    "xm430-w350-t": "new_xm430w350t",
    "xm540-w270-t": "new_xm540w270t",
}


def normalize_model(model: str) -> str:
    return model.strip().lower().replace("_", "-")


def supported_models() -> tuple[str, ...]:
    return tuple(sorted(_MODELS))


def new_motor(
    io: DynamixelIO,
    id: int,
    model: str,
    protocol: int = 2,
) -> DynamixelMotor:
    key = normalize_model(model)
    try:
        factory_name = _MODELS[key]
    except KeyError as exc:
        known = ", ".join(supported_models())
        raise ValueError(f"unknown motor model {model!r}; known: {known}") from exc
    return getattr(io, factory_name)(id, protocol, None)


def connect_io(device_name: str, baud_rate: int) -> DynamixelIO:
    return DynamixelIO(device_name, baud_rate)


def disconnect_io(io: DynamixelIO | None) -> None:
    if io is None:
        return
    port_handler = getattr(io, "port_handler", None)
    if port_handler is not None:
        port_handler.closePort()


def _motor_bus(bus: object, joint_name: str | None) -> tuple[threading.Lock, DynamixelMotor]:
    bus_lock: threading.Lock = bus.bus_lock  # type: ignore[attr-defined]
    motors = getattr(bus, "motors", None)
    if motors is not None:
        if joint_name is None:
            raise ValueError("joint_name is required when bus exposes multiple motors")
        return bus_lock, motors[joint_name]
    return bus_lock, bus.motor  # type: ignore[attr-defined]


def _selected_motors(
    bus: object,
    joint_names: Mapping[str, object] | tuple[str, ...] | list[str],
) -> dict[str, DynamixelMotor]:
    """Return configured motors for ``joint_names`` only (not the full arm)."""
    motors: Mapping[str, DynamixelMotor] = bus.motors  # type: ignore[attr-defined]
    names = list(joint_names)
    unknown = sorted(set(names) - set(motors))
    if unknown:
        raise ValueError(f"unknown joints: {unknown}")
    return {name: motors[name] for name in names}


def _motor_ids_by_joint(selected: Mapping[str, DynamixelMotor]) -> dict[int, str]:
    return {motor.dxl_id: joint_name for joint_name, motor in selected.items()}


BUS_READ_RETRIES = 2
BUS_READ_RETRY_DELAY_S = 0.003


def read_control_table_safe(motor: DynamixelMotor, register: str) -> int | None:
    """Read one control-table register, retrying truncated SDK responses."""
    table = getattr(motor, "CONTROL_TABLE", None)
    if table is not None and register not in table:
        return None
    for attempt in range(BUS_READ_RETRIES):
        try:
            return int(motor.read_control_table(register))
        except IndexError:
            if attempt + 1 < BUS_READ_RETRIES:
                time.sleep(BUS_READ_RETRY_DELAY_S)
        except Exception:
            return None
    return None


def read_present_current_safe(motor: DynamixelMotor) -> int | None:
    for attempt in range(BUS_READ_RETRIES):
        try:
            value = motor.get_current()
            if value is None:
                return None
            return int(value)
        except IndexError:
            if attempt + 1 < BUS_READ_RETRIES:
                time.sleep(BUS_READ_RETRY_DELAY_S)
        except Exception:
            return None
    return None


def read_present_position(motor: DynamixelMotor) -> int:
    """Read Present_Position with signed 32-bit decoding."""
    raw = read_control_table_safe(motor, "Present_Position")
    if raw is None:
        raise RuntimeError("failed to read Present_Position")
    return units.decode_position_ticks(raw)


def _motor_moving(motor: DynamixelMotor) -> bool | None:
    table = getattr(motor, "CONTROL_TABLE", None)
    if table is not None and "Moving" not in table:
        return None
    raw = read_control_table_safe(motor, "Moving")
    if raw is None:
        return None
    return bool(raw)


def _within_position_tolerance(
    measured_ticks: int,
    target_ticks: int,
    tolerance_ticks: int,
) -> bool:
    return abs(units.position_error_ticks(measured_ticks, target_ticks)) <= tolerance_ticks


def _can_sync_register(motors: list[DynamixelMotor], register_name: str) -> bool:
    if not motors:
        return False
    try:
        resolve_sync_register(motors, register_name)
    except ValueError:
        return False
    return True


def write_positions_sequential(
    bus: object,
    positions: Mapping[str, int],
) -> None:
    """Write Goal_Position one joint at a time.

    Use this for all non-E2E motion paths. Each joint receives its goal in a
    separate bus transaction.
    """
    if not positions:
        return

    for joint_name, target_ticks in positions.items():
        bus_lock, motor = _motor_bus(bus, joint_name)
        with bus_lock:
            motor.set_position(target_ticks)


def set_positions(
    bus: object,
    positions: Mapping[str, int],
) -> None:
    """Write Goal_Position for multiple joints in one bus transaction (E2E only).

    Uses Dynamixel sync write when every selected motor shares the register
    address/size; otherwise falls back to bulk write. Non-E2E suites should
    call ``write_positions_sequential`` instead.
    """
    if not positions:
        return

    selected = _selected_motors(bus, positions)
    bus_lock: threading.Lock = bus.bus_lock  # type: ignore[attr-defined]
    io: DynamixelIO = bus.io  # type: ignore[attr-defined]
    motor_list = list(selected.values())

    with bus_lock:
        if _can_sync_register(motor_list, "Goal_Position"):
            writes = {
                selected[joint_name]: target_ticks
                for joint_name, target_ticks in positions.items()
            }
            io.sync_write(writes, register_name="Goal_Position")
            return

        specs = [
            (selected[joint_name], "Goal_Position", target_ticks)
            for joint_name, target_ticks in positions.items()
        ]
        io.bulk_write(specs)


def read_positions(
    bus: object,
    joint_names: Mapping[str, object] | tuple[str, ...] | list[str],
) -> dict[str, int]:
    """Read Present_Position for a subset of configured joints in one bus transaction."""
    names = list(joint_names)
    if not names:
        return {}

    selected = _selected_motors(bus, names)
    bus_lock: threading.Lock = bus.bus_lock  # type: ignore[attr-defined]
    io: DynamixelIO = bus.io  # type: ignore[attr-defined]
    motor_list = [selected[name] for name in names]
    id_to_joint = _motor_ids_by_joint(selected)

    with bus_lock:
        if _can_sync_register(motor_list, "Present_Position"):
            raw = io.sync_read(motor_list, "Present_Position")
        else:
            specs = [(selected[name], "Present_Position") for name in names]
            raw = io.bulk_read(specs)

    return {
        id_to_joint[dxl_id]: units.decode_position_ticks(int(value))
        for dxl_id, value in raw.items()
    }


def move_positions_to_ticks(
    bus: object,
    positions: Mapping[str, int],
    *,
    timeout_s: float = MOVE_TIMEOUT_S,
    tolerance_ticks: int = POSITION_TOLERANCE_TICKS,
) -> dict[str, tuple[bool, int]]:
    """Move a subset of joints together and wait until all settle or time out."""
    if not positions:
        return {}

    write_positions_sequential(bus, positions)

    joint_names = list(positions)
    deadline = time.monotonic() + timeout_s
    measured: dict[str, int] = {}
    while time.monotonic() < deadline:
        settled = True
        measured = {}
        for joint_name in joint_names:
            bus_lock, motor = _motor_bus(bus, joint_name)
            with bus_lock:
                measured[joint_name] = read_present_position(motor)
                moving = _motor_moving(motor)
            target_ticks = positions[joint_name]
            if not _within_position_tolerance(
                measured[joint_name], target_ticks, tolerance_ticks
            ):
                settled = False
            elif moving:
                settled = False
        if settled:
            return {
                joint_name: (True, measured[joint_name]) for joint_name in positions
            }
        time.sleep(SETTLE_POLL_INTERVAL_S)

    return {
        joint_name: (
            _position_settled(
                bus,
                joint_name,
                measured.get(joint_name, positions[joint_name]),
                positions[joint_name],
                tolerance_ticks,
            ),
            measured.get(joint_name, positions[joint_name]),
        )
        for joint_name in positions
    }


def _position_settled(
    bus: object,
    joint_name: str,
    measured_ticks: int,
    target_ticks: int,
    tolerance_ticks: int,
) -> bool:
    if not _within_position_tolerance(measured_ticks, target_ticks, tolerance_ticks):
        return False
    bus_lock, motor = _motor_bus(bus, joint_name)
    with bus_lock:
        moving = _motor_moving(motor)
    return moving is not True

def move_to_ticks(
    bus: object,
    target_ticks: int,
    *,
    joint_name: str | None = None,
    timeout_s: float = MOVE_TIMEOUT_S,
    tolerance_ticks: int = POSITION_TOLERANCE_TICKS,
) -> tuple[bool, int]:
    """Move one motor to ``target_ticks`` and wait until settled or timed out.

    ``bus`` must expose ``bus_lock`` and either ``motor`` (single joint) or
    ``motors`` (full arm, with ``joint_name`` set).
    """
    bus_lock, motor = _motor_bus(bus, joint_name)
    with bus_lock:
        motor.set_position(target_ticks)
        measured_ticks = read_present_position(motor)

    deadline = time.monotonic() + timeout_s
    stable_polls = 0
    while time.monotonic() < deadline:
        with bus_lock:
            measured_ticks = read_present_position(motor)
            moving = _motor_moving(motor)
        if _within_position_tolerance(measured_ticks, target_ticks, tolerance_ticks):
            if moving is not True:
                return True, measured_ticks
            stable_polls += 1
            if stable_polls >= SETTLE_STABLE_POLLS:
                return True, measured_ticks
        else:
            stable_polls = 0
        time.sleep(SETTLE_POLL_INTERVAL_S)
    return False, measured_ticks
