"""Calibration failure types."""

from __future__ import annotations


class CalibrationError(Exception):
    """Base class for calibration abort conditions."""


class CommunicationError(CalibrationError):
    """Servo communication lost or position read failed."""


class EmergencyStopError(CalibrationError):
    """Operator emergency stop (SIGINT/SIGTERM) activated."""


class InvalidPositionError(CalibrationError):
    """Encoder value unavailable or out of recorded range."""
