"""Dynamixel motor helpers."""

from __future__ import annotations

import time

from dynio import DynamixelIO, DynamixelMotor

MOVE_TIMEOUT_S = 10.0
POSITION_TOLERANCE_TICKS = 10

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


def move_to_ticks(
    motor: DynamixelMotor,
    target_ticks: int,
    *,
    timeout_s: float = MOVE_TIMEOUT_S,
    tolerance_ticks: int = POSITION_TOLERANCE_TICKS,
) -> tuple[bool, int]:
    motor.set_position(target_ticks)
    deadline = time.monotonic() + timeout_s
    measured_ticks = int(motor.get_position())
    while time.monotonic() < deadline:
        measured_ticks = int(motor.get_position())
        if abs(measured_ticks - target_ticks) <= tolerance_ticks:
            return True, measured_ticks
        time.sleep(0.05)
    return False, measured_ticks
