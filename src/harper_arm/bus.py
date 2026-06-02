"""Bus abstraction over vendored Dynamixel IO."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import JointConfig

from vendor.dynamixel_controller import DynamixelIO, DynamixelMotor


class BusError(Exception):
    """Base class for bus-level failures."""


class BusConnectionError(BusError):
    """Raised when a serial bus connection fails."""


class BusCommunicationError(BusError):
    """Raised when communication with a motor fails."""


class UnsupportedModelError(BusError):
    """Raised when a model family cannot be mapped to a control table."""


class DynamixelBus:
    def __init__(self, port: str, baud_rate: int, *, auto_connect: bool = False) -> None:
        self.port = port
        self.baud_rate = baud_rate
        self._io: DynamixelIO | None = None
        if auto_connect:
            self.connect()

    @property
    def io(self) -> DynamixelIO:
        if self._io is None:
            raise BusConnectionError("Bus is not connected. Call connect() first.")
        return self._io

    def connect(self) -> None:
        if self._io is not None:
            return
        try:
            self._io = DynamixelIO(device_name=self.port, baud_rate=self.baud_rate)
        except Exception as exc:  # pragma: no cover - depends on serial hardware
            raise BusConnectionError(
                f"Failed to connect on port '{self.port}' at baud {self.baud_rate}."
            ) from exc

    def disconnect(self) -> None:
        if self._io is None:
            return
        port_handler = getattr(self._io, "port_handler", None)
        if port_handler is not None:
            port_handler.closePort()
        self._io = None

    def __enter__(self) -> "DynamixelBus":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.disconnect()

    def new_motor(self, motor_id: int, json_path: str | Path, *, protocol: int = 2) -> DynamixelMotor:
        try:
            return self.io.new_motor(dxl_id=motor_id, json_file=str(json_path), protocol=protocol)
        except Exception as exc:  # pragma: no cover - depends on serial hardware
            raise BusCommunicationError(f"Failed to initialize motor id={motor_id}.") from exc

    def new_motor_for_joint(self, joint: JointConfig) -> DynamixelMotor:
        family = joint.model_family
        if family == "xc330":
            return self.new_xc330(joint.id, protocol=joint.protocol)
        if family == "xl430":
            return self.new_xl430(joint.id, protocol=joint.protocol)
        if family == "xm430":
            return self.new_xm430(joint.id, protocol=joint.protocol)
        if family == "xm540":
            return self.new_xm540(joint.id, protocol=joint.protocol)
        raise UnsupportedModelError(f"Unsupported model family: {family}")

    def new_xc330(self, motor_id: int, *, protocol: int = 2) -> DynamixelMotor:
        return self.new_motor(motor_id, _control_table_path("xc330"), protocol=protocol)

    def new_xl430(self, motor_id: int, *, protocol: int = 2) -> DynamixelMotor:
        return self.new_motor(motor_id, _control_table_path("xl430"), protocol=protocol)

    def new_xm430(self, motor_id: int, *, protocol: int = 2) -> DynamixelMotor:
        return self.new_motor(motor_id, _control_table_path("xm430"), protocol=protocol)

    def new_xm540(self, motor_id: int, *, protocol: int = 2) -> DynamixelMotor:
        return self.new_motor(motor_id, _control_table_path("xm540"), protocol=protocol)

    def bulk_read(self, *args: Any, **kwargs: Any) -> Any:
        return self.io.bulk_read(*args, **kwargs)

    def bulk_write(self, *args: Any, **kwargs: Any) -> Any:
        return self.io.bulk_write(*args, **kwargs)


def _control_table_path(model_family: str) -> Path:
    candidate = (
        Path(__file__).resolve().parent / "control_tables" / f"{model_family}.json"
    )
    if not candidate.exists():
        raise UnsupportedModelError(
            f"Control table JSON not found for '{model_family}': {candidate}"
        )
    return candidate
