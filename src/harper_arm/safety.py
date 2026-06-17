"""Stop conditions for structural and E2E tests."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from harper_arm import units

if TYPE_CHECKING:
    from dynio import DynamixelMotor

    from harper_arm.sampling import JointSample

@dataclass(frozen=True)
class SafetyThresholds:
    current_fraction: float = 0.9
    temperature_delta_c: float = 15.0
    position_drift_ticks: int = 50
    min_voltage_v: float = 11.0
    max_voltage_v: float = 15.0

@dataclass(frozen=True)
class SafetyResult:
    should_stop: bool
    reason: str
    triggering_joint: str | None


class SafetyMonitor:
    """Evaluate sampled telemetry against shared stop conditions."""

    def __init__(
        self,
        *,
        current_limits: Mapping[str, int],
        thresholds: SafetyThresholds | None = None,
        baseline_temperatures: Mapping[str, int] | None = None,
        reference_positions: Mapping[str, int] | None = None,
        abort_event: threading.Event | None = None,
    ) -> None:
        self._current_limits = dict(current_limits)
        self._thresholds = thresholds or SafetyThresholds()
        self._baseline_temperatures = (
            dict(baseline_temperatures) if baseline_temperatures is not None else {}
        )
        self._reference_positions = (
            dict(reference_positions) if reference_positions is not None else {}
        )
        self._abort_event = abort_event

    def evaluate(self, samples: Mapping[str, JointSample]) -> SafetyResult:
        if self._abort_requested():
            return SafetyResult(True, "operator_abort", None)

        current_result = self._check_current(samples)
        if current_result is not None:
            return current_result

        temperature_result = self._check_temperature(samples)
        if temperature_result is not None:
            return temperature_result

        drift_result = self._check_position_drift(samples)
        if drift_result is not None:
            return drift_result

        voltage_result = self._check_voltage(samples)
        if voltage_result is not None:
            return voltage_result

        hardware_result = self._check_hardware_error(samples)
        if hardware_result is not None:
            return hardware_result

        return SafetyResult(False, "", None)

    def as_stop_check(self) -> Callable[[Mapping[str, JointSample]], tuple[bool, str, str | None]]:
        def check(samples: Mapping[str, JointSample]) -> tuple[bool, str, str | None]:
            result = self.evaluate(samples)
            return result.should_stop, result.reason, result.triggering_joint

        return check

    def _abort_requested(self) -> bool:
        return self._abort_event is not None and self._abort_event.is_set()

    def _check_current(self, samples: Mapping[str, JointSample]) -> SafetyResult | None:
        """Check the current of the joints against the current limits.
        If the current of the joint is greater than the current limit, the joint is stopped.

        Args:
            samples: The samples to check.

        Returns:
            A SafetyResult object.
        
        """

        threshold = self._thresholds.current_fraction
        worst_joint: str | None = None
        worst_ratio = 0.0 # The worst ratio of the current of the joint to the current limit.

        for name, sample in samples.items():
            limit = self._current_limits.get(name) # The current limit of the joint.
            if limit is None or limit <= 0:
                continue
            ratio = abs(sample.current) / limit
            if ratio >= threshold and ratio >= worst_ratio:
                worst_ratio = ratio
                worst_joint = name

        if worst_joint is not None:
            return SafetyResult(True, "current_limit", worst_joint)
        return None

    def _check_temperature(self, samples: Mapping[str, JointSample]) -> SafetyResult | None:
        """Check joint temperatures against baselines.

        Stops the joint when its temperature exceeds the baseline.

        Args:
            samples: The samples to check.

        Returns:
            A SafetyResult object.
        """
        if not self._baseline_temperatures:
            return None

        delta_limit = self._thresholds.temperature_delta_c
        worst_joint: str | None = None
        worst_delta = 0.0

        for name, sample in samples.items():
            baseline = self._baseline_temperatures.get(name)
            if baseline is None:
                continue
            delta = sample.temperature - baseline
            if delta >= delta_limit and delta >= worst_delta:
                worst_delta = delta
                worst_joint = name

        if worst_joint is not None:
            return SafetyResult(True, "temperature_rise", worst_joint)
        return None

    def _check_position_drift(self, samples: Mapping[str, JointSample]) -> SafetyResult | None:
        """Check the position of the joints against the reference positions.
        If the position of the joint is greater than the reference position, the joint is stopped.

        Args:
            samples: The samples to check.

        Returns:
            A SafetyResult object.
        """
        if not self._reference_positions:
            return None

        tolerance = self._thresholds.position_drift_ticks
        worst_joint: str | None = None
        worst_drift = 0

        for name, sample in samples.items():
            reference = self._reference_positions.get(name)
            if reference is None:
                continue
            drift = abs(sample.position - reference)
            if drift > tolerance and drift >= worst_drift:
                worst_drift = drift
                worst_joint = name

        if worst_joint is not None:
            return SafetyResult(True, "position_drift", worst_joint)
        return None

    def _check_voltage(self, samples: Mapping[str, JointSample]) -> SafetyResult | None:
        low = self._thresholds.min_voltage_v
        high = self._thresholds.max_voltage_v
        worst_joint: str | None = None
        worst_delta = 0.0

        for name, sample in samples.items():
            volts = units.voltage_to_volts(sample.voltage)
            if volts < low:
                delta = low - volts
            elif volts > high:
                delta = volts - high
            else:
                continue
            if delta >= worst_delta:
                worst_delta = delta
                worst_joint = name

        if worst_joint is not None:
            return SafetyResult(True, "input_voltage", worst_joint)
        return None

    def _check_hardware_error(self, samples: Mapping[str, JointSample]) -> SafetyResult | None:
        for name, sample in samples.items():
            if sample.hardware_error:
                return SafetyResult(True, "hardware_error", name)
        return None

def torque_off_all(motors: Mapping[str, DynamixelMotor]) -> None:
    """Torque off all the motors."""
    for motor in motors.values():
        motor.torque_disable()


def verify_torque_enabled_all(motors: Mapping[str, DynamixelMotor]) -> list[str]:
    """Return joint names where ``Torque_Enable`` is not set.

    Caller must hold the bus lock when motors share one serial port.
    """
    disabled: list[str] = []
    for name, motor in motors.items():
        try:
            enabled = bool(int(motor.read_control_table("Torque_Enable")))
        except Exception:
            disabled.append(name)
            continue
        if not enabled:
            disabled.append(name)
    return disabled


def ensure_torque_enabled_all(motors: Mapping[str, DynamixelMotor]) -> None:
    """Enable torque on every motor and verify the register readback.

    Caller must hold the bus lock when motors share one serial port.
    """
    for motor in motors.values():
        motor.torque_enable()
    disabled = verify_torque_enabled_all(motors)
    if disabled:
        joined = ", ".join(disabled)
        raise RuntimeError(f"torque enable failed for joints: {joined}")