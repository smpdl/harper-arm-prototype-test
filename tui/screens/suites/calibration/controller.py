"""Calibration session controller (hardware interaction layer)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from harper_arm.calibration.errors import CalibrationError, EmergencyStopError
from harper_arm.status import MotorStatus, read_joint_live
from suites.calibration.operator import CalibrationOperator
from tui.core.paths import RunPaths


@dataclass(frozen=True)
class CalibrationSessionResult:
    run_dir: Path | None
    saved: bool
    message: str


class CalibrationSessionController:
    def __init__(
        self,
        paths: RunPaths,
        *,
        test: str,
        joint: str,
    ) -> None:
        self.paths = paths
        self.test = test
        self.joint = joint
        self._operator: CalibrationOperator | None = None
        self._operator_lock = threading.Lock()
        self._saved = False
        self._run_dir: Path | None = None

    @property
    def backdriveable(self) -> bool:
        return self.test == "backdriveable"

    @property
    def operator(self) -> CalibrationOperator | None:
        return self._operator

    @property
    def saved(self) -> bool:
        return self._saved

    @property
    def run_dir(self) -> Path | None:
        return self._run_dir

    def open(self) -> None:
        self.close()
        self._operator = CalibrationOperator(
            test=self.test,
            joint_name=self.joint,
            backdriveable=self.backdriveable,
            config_path=self.paths.config_path,
            results_root=self.paths.results_root,
        ).open()
        self._saved = False
        self._run_dir = None

    def close(self) -> None:
        if self._operator is not None:
            self._operator.close()
            self._operator = None

    def _require_operator(self) -> CalibrationOperator:
        if self._operator is None:
            raise RuntimeError("No active calibration session")
        return self._operator

    def refresh(self) -> tuple[int, MotorStatus]:
        operator = self._require_operator()
        operator._check_abort()
        with self._operator_lock:
            return read_joint_live(operator.connected_joint)

    def recorded_positions(self) -> tuple[int | None, int | None, int | None]:
        if self._operator is None:
            return None, None, None
        calibration = self._operator.calibration
        return (
            calibration.min_position,
            calibration.home_position,
            calibration.max_position,
        )

    def record_min(self) -> int:
        operator = self._require_operator()
        with self._operator_lock:
            return operator.record_min()

    def record_home(self) -> int:
        operator = self._require_operator()
        with self._operator_lock:
            return operator.record_home()

    def record_max(self) -> int:
        operator = self._require_operator()
        with self._operator_lock:
            return operator.record_max()

    def jog(self, jog_command: str) -> tuple[bool, int]:
        operator = self._require_operator()
        with self._operator_lock:
            return operator.jog(jog_command)

    def save(self) -> Path:
        operator = self._require_operator()
        with self._operator_lock:
            operator.save()
            self._saved = True
            self._run_dir = operator.run_dir
            return self._run_dir


__all__ = [
    "CalibrationError",
    "CalibrationSessionController",
    "CalibrationSessionResult",
    "EmergencyStopError",
]
