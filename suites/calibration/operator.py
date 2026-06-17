"""Shared calibration actions for TUI buttons and terminal stdin loops."""

from __future__ import annotations

import threading
from contextlib import ExitStack
from pathlib import Path
from typing import Literal

from harper_arm.calibration.config import (
    DEFAULT_CALIBRATION_PATH,
    CalibrationSettings,
    jog_command_rows,
    jog_commands,
    load_calibration_settings,
)
from harper_arm.calibration.errors import CalibrationError, EmergencyStopError
from harper_arm.calibration.joints import require_joint_mode
from harper_arm.calibration.motion import jog_degrees, prepare_calibration_motion
from harper_arm.calibration.persist import apply_joint_calibration, save_partial_session
from harper_arm.calibration.record import record_position
from harper_arm.calibration.session import CalibrationSession, JointCalibration
from harper_arm.joint import DEFAULT_CONFIG_PATH, Joint
from harper_arm.logging import TestRun

from .helpers import DEFAULT_RESULTS_ROOT, calibration_test_run, utc_now

CommandResult = Literal["continue", "quit", "saved"]


class CalibrationOperator:
    """One open joint connection for operator-supervised calibration."""

    def __init__(
        self,
        *,
        test: str,
        joint_name: str,
        backdriveable: bool,
        config_path: Path | str = DEFAULT_CONFIG_PATH,
        calibration_path: Path | str = DEFAULT_CALIBRATION_PATH,
        results_root: Path = DEFAULT_RESULTS_ROOT,
    ) -> None:
        self.test = test
        self.joint_name = joint_name
        self.backdriveable = backdriveable
        self.config_path = Path(config_path)
        self.calibration_path = Path(calibration_path)
        self.results_root = results_root
        self._stack = ExitStack()
        self._connected_joint: Joint | None = None
        self._recorder: TestRun | None = None
        self._session: CalibrationSession | None = None
        self._abort_event: threading.Event | None = None
        self._settings: CalibrationSettings | None = None
        self._saved = False

    def open(self) -> CalibrationOperator:
        """Connect to the joint and prepare for calibration."""
        return self.__enter__()

    def close(self) -> None:
        """Disconnect and finalize the test run."""
        self.__exit__(None, None, None)

    def __enter__(self) -> CalibrationOperator:
        require_joint_mode(self.joint_name, backdriveable=self.backdriveable)
        joint, recorder, session, abort_event = self._stack.enter_context(
            calibration_test_run(
                test=self.test,
                schema="calibration_record",
                joint_name=self.joint_name,
                config_path=self.config_path,
                calibration_path=self.calibration_path,
                results_root=self.results_root,
            )
        )
        self._connected_joint = joint
        self._recorder = recorder
        self._session = session
        self._abort_event = abort_event
        if self.backdriveable:
            joint.torque_disable()
        else:
            self._settings = load_calibration_settings(self.calibration_path)
            prepare_calibration_motion(joint, self._settings)
            joint.torque_enable()
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._recorder is not None and not self._saved:
            calibration = self.calibration
            self._recorder.set_summary(
                saved=False,
                joint=self.joint_name,
                min_position=calibration.min_position,
                home_position=calibration.home_position,
                max_position=calibration.max_position,
            )
        self._stack.close()

    @property
    def connected_joint(self) -> Joint:
        assert self._connected_joint is not None
        return self._connected_joint

    @property
    def calibration(self) -> JointCalibration:
        assert self._session is not None
        return self._session.joint(self.joint_name)

    @property
    def run_dir(self) -> Path:
        assert self._recorder is not None
        return self._recorder.run_dir

    def _check_abort(self) -> None:
        assert self._abort_event is not None
        if self._abort_event.is_set():
            raise EmergencyStopError("emergency stop activated")

    def refresh_position(self) -> int:
        self._check_abort()
        return record_position(
            self.connected_joint,
            abort_event=self._abort_event,
            verify_comm=False,
        )

    def record_min(self) -> int:
        ticks = self.refresh_position()
        self.calibration.record_min(ticks)
        self._log_action("record_min", ticks)
        return ticks

    def record_home(self) -> int:
        ticks = self.refresh_position()
        self.calibration.record_home(ticks)
        self._log_action("record_home", ticks)
        return ticks

    def record_max(self) -> int:
        ticks = self.refresh_position()
        self.calibration.record_max(ticks)
        self._log_action("record_max", ticks)
        return ticks

    def jog(self, command: str) -> tuple[bool, int]:
        if self.backdriveable:
            raise ValueError("jog is only available for non-backdriveable calibration")
        assert self._settings is not None
        signed_deg = jog_commands(self._settings).get(command)
        if signed_deg is None:
            raise ValueError(f"unknown jog command {command!r}")
        reached, measured = jog_degrees(
            self.connected_joint,
            delta_deg=signed_deg,
            calibration=self.calibration,
            abort_event=self._abort_event,
        )
        assert self._recorder is not None
        self._recorder.write_row(
            {
                "timestamp_utc": utc_now().isoformat(),
                "joint": self.joint_name,
                "action": "jog",
                "position_ticks": measured,
                "delta_deg": signed_deg,
                "reached": reached,
            }
        )
        return reached, measured

    def save(self) -> bool:
        if not self.calibration.is_complete():
            raise CalibrationError("record MIN, HOME, and MAX before saving")
        apply_joint_calibration(self.calibration, arm_path=self.config_path)
        assert self._session is not None
        save_partial_session(self._session)
        assert self._recorder is not None
        self._recorder.set_summary(saved=True, joint=self.joint_name)
        self._saved = True
        return True

    def handle_command(self, command: str) -> CommandResult:
        """Dispatch a stdin-style command. Used by terminal calibration loops."""
        command = command.strip().lower()
        if command in {"q", "quit"}:
            return "quit"
        if command in {"r", "refresh", ""}:
            return "continue"
        if command == "s":
            self.save()
            return "saved"
        if command in {"m", "min"}:
            self.record_min()
            return "continue"
        if command in {"h", "home"}:
            self.record_home()
            return "continue"
        if command in {"x", "max"}:
            self.record_max()
            return "continue"
        if not self.backdriveable:
            assert self._settings is not None
            if command in jog_commands(self._settings):
                reached, measured = self.jog(command)
                if not reached:
                    print(f"Jog did not settle within tolerance (at {measured} ticks).")
                return "continue"
        raise ValueError(f"unknown command: {command!r}")

    def _log_action(self, action: str, ticks: int) -> None:
        assert self._recorder is not None
        self._recorder.write_row(
            {
                "timestamp_utc": utc_now().isoformat(),
                "joint": self.joint_name,
                "action": action,
                "position_ticks": ticks,
                "delta_deg": "",
                "reached": "",
            }
        )


def format_status_prompt(operator: CalibrationOperator, position: int) -> str:
    """Build the terminal prompt shown before each stdin command."""
    if operator.backdriveable:
        return (
            f"\nJoint: {operator.joint_name} (torque OFF — move manually)\n"
            f"Position: {position} ticks\n"
            "\n"
            "[m] Record MIN   [h] Record HOME   [x] Record MAX   [r] Refresh position\n"
            "[s] Save & exit   [q] Quit without saving\n"
            "> "
        )
    assert operator._settings is not None
    negative, positive = jog_command_rows(operator._settings)
    jog_labels = " ".join([*negative, *positive])
    return (
        f"\nJoint: {operator.joint_name}\n"
        f"Position: {position} ticks\n"
        "\n"
        f"{jog_labels}  jog\n"
        "[m] Record MIN   [h] Record HOME   [x] Record MAX\n"
        "[s] Save & exit   [q] Quit without saving\n"
        "> "
    )


def run_stdin_loop(operator: CalibrationOperator) -> bool:
    """Blocking stdin loop for terminal use. Returns True if calibration was saved."""
    while True:
        position = operator.refresh_position()
        command = input(format_status_prompt(operator, position)).strip().lower()
        try:
            result = operator.handle_command(command)
        except CalibrationError as exc:
            print(str(exc))
            continue
        except ValueError as exc:
            print(str(exc))
            continue
        if result == "quit":
            return False
        if result == "saved":
            return True
        if command in {"m", "min"}:
            print(f"Recorded record_min = {operator.calibration.min_position}")
        elif command in {"h", "home"}:
            print(f"Recorded record_home = {operator.calibration.home_position}")
        elif command in {"x", "max"}:
            print(f"Recorded record_max = {operator.calibration.max_position}")
