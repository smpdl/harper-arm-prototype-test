"""Post-calibration span validation at 25%, 50%, and 75% of recorded span.
Repeatability approaches 50% from min twice: 0% -> 50% -> 0% -> 50% -> 0%.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from harper_arm import units
from harper_arm.calibration.config import CalibrationSettings
from harper_arm.calibration.errors import CommunicationError, EmergencyStopError
from harper_arm.calibration.motion import prepare_calibration_motion
from harper_arm.calibration.record import record_position
from harper_arm.calibration.session import JointCalibration
from harper_arm.joint import Joint, apply_motor_position_profile
from harper_arm.motor import move_to_ticks

VALIDATION_FRACTIONS = (0.25, 0.5, 0.75)
VALIDATION_HOLD_S = 3.0

@dataclass(frozen=True)
class FractionResult:
    fraction: float
    target_ticks: int
    reached: bool
    measured_ticks: int
    error_deg: float


@dataclass(frozen=True)
class JointValidationResult:
    joint_name: str
    passed: bool
    fraction_results: tuple[FractionResult, ...]
    repeatability_error_deg: float | None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "joint_name": self.joint_name,
            "passed": self.passed,
            "repeatability_error_deg": self.repeatability_error_deg,
            "message": self.message,
            "fractions": [
                {
                    "fraction": result.fraction,
                    "target_ticks": result.target_ticks,
                    "reached": result.reached,
                    "measured_ticks": result.measured_ticks,
                    "error_deg": result.error_deg,
                }
                for result in self.fraction_results
            ],
        }


@dataclass(frozen=True)
class ValidationReport:
    passed: bool
    joint_results: tuple[JointValidationResult, ...]
    repeatability_error_deg: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation": {
                "passed": self.passed,
                "repeatability_error_deg": self.repeatability_error_deg,
                "joints": [result.to_dict() for result in self.joint_results],
            }
        }


def validate_joint(
    joint: Joint,
    calibration: JointCalibration,
    settings: CalibrationSettings,
    *,
    abort_event: threading.Event | None = None,
) -> JointValidationResult:
    """Move to 25/50/75% of recorded span and verify encoder feedback."""
    if calibration.min_position is None or calibration.max_position is None:
        return JointValidationResult(
            joint_name=calibration.joint_name,
            passed=False,
            fraction_results=(),
            repeatability_error_deg=None,
            message="position_limits required (min and max)",
        )

    prepare_calibration_motion(joint, settings)
    with joint.bus_lock:
        joint.motor.torque_enable()

    fraction_results: list[FractionResult] = []
    try:
        for fraction in VALIDATION_FRACTIONS:
            if abort_event is not None and abort_event.is_set():
                raise EmergencyStopError("emergency stop activated")

            target = calibration.position_at_fraction(fraction)
            reached, measured = move_to_ticks(
                joint,
                target,
                joint_name=joint.joint_name,
            )
            try:
                record_position(joint, abort_event=abort_event)
            except CommunicationError as exc:
                return JointValidationResult(
                    joint_name=calibration.joint_name,
                    passed=False,
                    fraction_results=tuple(fraction_results),
                    repeatability_error_deg=None,
                    message=str(exc),
                )

            error_deg = abs(units.position_error_deg(measured, target))
            fraction_results.append(
                FractionResult(
                    fraction=fraction,
                    target_ticks=target,
                    reached=reached,
                    measured_ticks=measured,
                    error_deg=error_deg,
                )
            )
            time.sleep(VALIDATION_HOLD_S)

        repeatability_error_deg = _repeatability_at_midspan(
            joint,
            calibration,
            settings,
            abort_event=abort_event,
        )
    except (CommunicationError, EmergencyStopError) as exc:
        return JointValidationResult(
            joint_name=calibration.joint_name,
            passed=False,
            fraction_results=tuple(fraction_results),
            repeatability_error_deg=None,
            message=str(exc),
        )

    tolerance_deg = units.ticks_to_degrees(settings.validation_tolerance_ticks)
    passed = all(
        result.reached and result.error_deg <= tolerance_deg for result in fraction_results
    )
    if repeatability_error_deg > settings.validation_repeatability_deg:
        passed = False

    return JointValidationResult(
        joint_name=calibration.joint_name,
        passed=passed,
        fraction_results=tuple(fraction_results),
        repeatability_error_deg=repeatability_error_deg,
        message=None if passed else "position or repeatability out of tolerance",
    )


def validate_session(
    joints: dict[str, tuple[Joint, JointCalibration]],
    settings: CalibrationSettings,
    *,
    abort_event: threading.Event | None = None,
) -> ValidationReport:
    results = [
        validate_joint(
            hardware,
            calibration,
            settings,
            abort_event=abort_event,
        )
        for hardware, calibration in joints.values()
    ]
    repeatability_values = [
        result.repeatability_error_deg
        for result in results
        if result.repeatability_error_deg is not None
    ]
    worst_repeatability = max(repeatability_values) if repeatability_values else 0.0
    passed = all(result.passed for result in results)
    return ValidationReport(
        passed=passed,
        joint_results=tuple(results),
        repeatability_error_deg=worst_repeatability,
    )


def _repeatability_at_midspan(
    joint: Joint,
    calibration: JointCalibration,
    settings: CalibrationSettings,
    *,
    abort_event: threading.Event | None = None,
) -> float:
    """Approach 50% from min twice and compare the two readings at midspan."""
    min_target = calibration.position_at_fraction(0.0)
    mid_target = calibration.position_at_fraction(0.5)
    with joint.bus_lock:
        apply_motor_position_profile(
            joint.motor,
            velocity_rpm=settings.profile_velocity_rpm,
            acceleration_rpm2=settings.profile_acceleration_rpm2,
        )

    readings: list[int] = []
    for min_target_ticks, mid_target_ticks in (
        (min_target, mid_target),
        (min_target, mid_target),
    ):
        if abort_event is not None and abort_event.is_set():
            raise EmergencyStopError("emergency stop activated")
        move_to_ticks(joint, min_target_ticks, joint_name=joint.joint_name)
        time.sleep(VALIDATION_HOLD_S)
        move_to_ticks(joint, mid_target_ticks, joint_name=joint.joint_name)
        readings.append(record_position(joint, abort_event=abort_event))
        time.sleep(VALIDATION_HOLD_S)

    move_to_ticks(joint, min_target, joint_name=joint.joint_name)
    return abs(units.position_error_deg(readings[1], readings[0]))
