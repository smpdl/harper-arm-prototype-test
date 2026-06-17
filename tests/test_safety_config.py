"""Tests for calibration gating and safety monitor extensions."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest

from harper_arm.config import ArmConfig, JointConfig, require_arm_calibrated, require_joint_calibrated
from harper_arm.safety import SafetyMonitor, SafetyThresholds
from harper_arm.sampling import JointSample


def _joint(*, calibrated: bool = False, home: int | None = None) -> JointConfig:
    return JointConfig(
        name="r_sh_flex",
        id=1,
        model="xm540-w270-t",
        protocol=2,
        position_limits=(0, 4095),
        current_limit=100,
        home_position=home,
        calibrated=calibrated,
    )


def _arm(joint: JointConfig) -> ArmConfig:
    return ArmConfig(serial_port="/dev/null", baud_rate=115200, joints={"r_sh_flex": joint})


def test_require_joint_calibrated_rejects_uncalibrated() -> None:
    with pytest.raises(ValueError, match="not calibrated"):
        require_joint_calibrated(_joint())


def test_require_joint_calibrated_accepts_saved_joint() -> None:
    require_joint_calibrated(_joint(calibrated=True, home=2048))


def test_require_arm_calibrated_lists_missing_joints() -> None:
    arm = ArmConfig(
        serial_port="/dev/null",
        baud_rate=115200,
        joints={
            "a": _joint(),
            "b": JointConfig(
                name="b",
                id=2,
                model="xl430-w250-t",
                protocol=2,
                position_limits=(0, 4095),
                current_limit=100,
                home_position=2048,
                calibrated=True,
            ),
        },
    )
    with pytest.raises(ValueError, match="uncalibrated joints: a"):
        require_arm_calibrated(arm)


def _sample(
    *,
    joint: str = "r_sh_flex",
    voltage: int = 120,
    hardware_error: int = 0,
) -> JointSample:
    return JointSample(
        timestamp=datetime.now(UTC),
        joint=joint,
        position=0,
        velocity=0,
        current=0,
        temperature=30,
        voltage=voltage,
        hardware_error=hardware_error,
    )


def test_safety_monitor_stops_on_low_voltage() -> None:
    monitor = SafetyMonitor(
        current_limits={"r_sh_flex": 100},
        thresholds=SafetyThresholds(min_voltage_v=11.0, max_voltage_v=15.0),
    )
    result = monitor.evaluate({"r_sh_flex": _sample(voltage=100)})
    assert result.should_stop
    assert result.reason == "input_voltage"


def test_safety_monitor_stops_on_hardware_error() -> None:
    monitor = SafetyMonitor(current_limits={"r_sh_flex": 100})
    result = monitor.evaluate({"r_sh_flex": _sample(hardware_error=0x10)})
    assert result.should_stop
    assert result.reason == "hardware_error"
    assert result.triggering_joint == "r_sh_flex"


def test_safety_monitor_honors_abort_event() -> None:
    abort_event = threading.Event()
    abort_event.set()
    monitor = SafetyMonitor(current_limits={"r_sh_flex": 100}, abort_event=abort_event)
    result = monitor.evaluate({"r_sh_flex": _sample()})
    assert result.should_stop
    assert result.reason == "operator_abort"
