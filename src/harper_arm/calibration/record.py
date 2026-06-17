"""Read encoder positions with communication checks."""

from __future__ import annotations

import threading

from dynamixel_sdk import COMM_SUCCESS

from harper_arm.calibration.errors import CommunicationError, EmergencyStopError
from harper_arm.joint import Joint


def check_communication(joint: Joint) -> None:
    """Ping the motor; raise if the bus is unreachable."""
    with joint.bus_lock:
        io = joint.io
        motor_id = joint.joint.id
        protocol = joint.joint.protocol
        handler = io.packet_handler[protocol - 1]
        try:
            _model, comm_result, dxl_error = handler.ping(io.port_handler, motor_id)
        except IndexError as exc:
            raise CommunicationError("ping returned an incomplete response") from exc
        if comm_result != COMM_SUCCESS:
            raise CommunicationError(handler.getTxRxResult(comm_result))
        if dxl_error != 0:
            raise CommunicationError(handler.getRxPacketError(dxl_error))

def read_position(
    joint: Joint,
    *,
    abort_event: threading.Event | None = None,
) -> int:
    """Read present encoder ticks without a bus ping."""
    if abort_event is not None and abort_event.is_set():
        raise EmergencyStopError("emergency stop activated")

    try:
        position = joint.get_position()
    except Exception as exc:
        raise CommunicationError(f"failed to read position: {exc}") from exc

    if abort_event is not None and abort_event.is_set():
        raise EmergencyStopError("emergency stop activated")

    return position


def record_position(
    joint: Joint,
    *,
    abort_event: threading.Event | None = None,
    verify_comm: bool = True,
) -> int:
    """
    Read present encoder ticks, optionally after a bus ping.

    Used for both guided incremental and manual (backdrive) placement modes.
    Live display polling should pass ``verify_comm=False`` to avoid hammering
    the bus with pings several times per second.
    """
    if verify_comm:
        check_communication(joint)
    return read_position(joint, abort_event=abort_event)
