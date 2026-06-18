"""This module contains the functions for the calibration motion."""

from __future__ import annotations

import threading

from harper_arm import units
from harper_arm.calibration.config import CalibrationSettings
from harper_arm.calibration.errors import EmergencyStopError
from harper_arm.calibration.record import record_position
from harper_arm.calibration.session import JointCalibration
from harper_arm.config import JointConfig
from harper_arm.joint import Joint, apply_motor_position_profile, configure_joint_position_mode
from harper_arm.motor import move_to_ticks


def prepare_calibration_motion(joint: Joint, settings: CalibrationSettings) -> None:
    """Configure slow position-mode motion without relying on uncalibrated EEPROM limits."""
    with joint.bus_lock:
        joint.motor.torque_disable()
        joint.motor.set_extended_position_mode()
        apply_motor_position_profile(
            joint.motor,
            velocity_rpm=settings.profile_velocity_rpm,
            acceleration_rpm2=settings.profile_acceleration_rpm2,
        )


def jog_degrees(
    joint: Joint,
    *,
    delta_deg: float,
    calibration: JointCalibration,
    abort_event: threading.Event | None = None,
) -> tuple[bool, int]:
    """Move incrementally by ``delta_deg``, clamped to the recorded calibration limits.

    Returns whether the move settled within tolerance and the final encoder reading.
    """
    if abort_event is not None and abort_event.is_set():
        raise EmergencyStopError("emergency stop activated")

    current = record_position(joint, abort_event=abort_event)
    delta_ticks = units.degrees_to_ticks(delta_deg)
    target = calibration.clamp_target(current + delta_ticks)

    if target == current:
        return True, current

    reached, measured = move_to_ticks(joint, target, joint_name=joint.joint_name)
    return reached, measured


def reconfigure_with_recorded_limits(joint: Joint, calibration: JointCalibration) -> None:
    """Switch from extended mode to limits matching the recorded calibration."""
    if calibration.min_position is None or calibration.max_position is None:
        raise ValueError("min and max positions must be recorded before applying limits")
    limits = (calibration.min_position, calibration.max_position)
    updated = JointConfig(
        name=joint.joint.name,
        id=joint.joint.id,
        model=joint.joint.model,
        protocol=joint.joint.protocol,
        position_limits=limits,
        current_limit=joint.joint.current_limit,
        home_position=joint.joint.home_position,
        calibrated=joint.joint.calibrated,
        position_profile_velocity_rpm=joint.joint.position_profile_velocity_rpm,
    )
    with joint.bus_lock:
        joint.motor.torque_disable()
        configure_joint_position_mode(joint.motor, updated)
