"""Post-calibration span validation at min, 25%, 50%, and max of recorded limits."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from harper_arm import units
from harper_arm.arm import FullArm
from harper_arm.calibration.config import CalibrationSettings
from harper_arm.calibration.errors import CommunicationError, EmergencyStopError
from harper_arm.calibration.motion import prepare_calibration_motion
from harper_arm.calibration.record import record_position
from harper_arm.calibration.session import JointCalibration
from harper_arm.config import ArmConfig, limit_position_at_fraction
from harper_arm.joint import Joint
from harper_arm.motor import move_to_ticks

# Min, 25%, 50%, and max of the configured [min, max] span.
VALIDATION_FRACTIONS = (0.0, 0.25, 0.5, 1.0)


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


def prepare_validation_support_joints(
    arm: FullArm,
    joint_name: str,
    arm_config: ArmConfig,
    settings: CalibrationSettings,
    *,
    abort_event: threading.Event | None = None,
) -> None:
    """Move supporting joints into position before validating ``joint_name``."""
    prep_moves = settings.validation_prep.get(joint_name, ())
    if not prep_moves:
        return

    for move in prep_moves:
        if abort_event is not None and abort_event.is_set():
            raise EmergencyStopError("emergency stop activated")
        if move.joint not in arm_config.joints:
            raise ValueError(f"unknown validation prep joint {move.joint!r}")
        limits = arm_config.joints[move.joint].position_limits
        target = limit_position_at_fraction(limits, move.fraction)
        move_to_ticks(arm, target, joint_name=move.joint)


def validate_joint(
    joint: Joint,
    calibration: JointCalibration,
    settings: CalibrationSettings,
    *,
    abort_event: threading.Event | None = None,
) -> JointValidationResult:
    """Move to min, 25%, 50%, and max of the recorded span and verify feedback."""
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

    hold_s = settings.validation_hold_s
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
            if hold_s > 0:
                time.sleep(hold_s)
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

    return JointValidationResult(
        joint_name=calibration.joint_name,
        passed=passed,
        fraction_results=tuple(fraction_results),
        repeatability_error_deg=None,
        message=None if passed else "position out of tolerance",
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
    passed = all(result.passed for result in results)
    return ValidationReport(
        passed=passed,
        joint_results=tuple(results),
        repeatability_error_deg=0.0,
    )
