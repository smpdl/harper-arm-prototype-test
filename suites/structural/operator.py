"""Step-by-step structural test operators for TUI and terminal stdin loops."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from harper_arm.arm import FullArm
from harper_arm.config import load_arm_config, require_arm_calibrated
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.logging import TestRun
from harper_arm.safety import SafetyMonitor
from harper_arm.sampling import operator_abort_guard
from suites.e2e.config import DEFAULT_E2E_CONFIG_PATH

from .helpers import (
    DEFAULT_HOME_NAME,
    DEFAULT_RESULTS_ROOT,
    LINK_JOINTS,
    load_motion_config,
    make_safety_monitor,
    max_flex_deg,
    move_home_scurve,
    prepare_hold_pose,
    structural_test_run,
    utc_now,
)

PointLoadPhase = Literal[
    "await_pose_confirm",
    "await_ready",
    "await_inputs",
    "await_bring_home",
    "complete",
]


@dataclass(frozen=True)
class PointLoadRecordResult:
    link: str
    max_flex_deg: float
    stopped_early: bool
    stop_reason: str
    limiting_joint: str | None


class PointLoadOperator:
    """Operator-assisted point-load flex assessment, one link at a time."""

    def __init__(
        self,
        *,
        pose: str,
        config_path: Path | str = DEFAULT_CONFIG_PATH,
        e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH,
        results_root: Path = DEFAULT_RESULTS_ROOT,
    ) -> None:
        self.pose = pose
        self.config_path = Path(config_path)
        self.e2e_config_path = Path(e2e_config_path)
        self.results_root = results_root
        self._stack = ExitStack()
        self._arm: FullArm | None = None
        self._recorder: TestRun | None = None
        self._monitor: SafetyMonitor | None = None
        self._reference: dict[str, int] = {}
        self._link_queue: list[tuple[str, tuple[str, ...]]] = []
        self._current_link: tuple[str, tuple[str, ...]] | None = None
        self._phase: PointLoadPhase = "complete"
        self._links_tested = 0
        self._stopped_early = False
        self._stop_reason = ""
        self._limiting_joint: str | None = None
        self._reached_all = False
        self._finished = False
        self._returned_home = False
        self._abort_event = None

    def open(self) -> PointLoadOperator:
        return self.__enter__()

    def close(self) -> None:
        self.__exit__(None, None, None)

    def __enter__(self) -> PointLoadOperator:
        require_arm_calibrated(load_arm_config(self.config_path))

        arm, recorder = self._stack.enter_context(
            structural_test_run(
                test="point_load",
                schema="point_load",
                config_path=self.config_path,
                results_root=self.results_root,
                metadata={
                    "pose": self.pose,
                    "e2e_config_path": str(self.e2e_config_path),
                },
            )
        )
        abort_guard = self._stack.enter_context(operator_abort_guard())
        self._arm = arm
        self._recorder = recorder
        self._abort_event = abort_guard

        if self.pose == DEFAULT_HOME_NAME:
            self._move_to_test_pose()
        else:
            self._phase = "await_pose_confirm"
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._arm is not None and not self._returned_home:
            try:
                motion = load_motion_config(self.pose, e2e_config_path=self.e2e_config_path)
                reached_home, stop_reason, limiting_joint = move_home_scurve(
                    self._arm,
                    config_path=self.config_path,
                    e2e_config_path=self.e2e_config_path,
                    motion=motion,
                    monitor=self._monitor,
                )
                self._returned_home = reached_home and not stop_reason
                if stop_reason:
                    self._stopped_early = True
                    self._stop_reason = self._stop_reason or stop_reason
                    self._limiting_joint = self._limiting_joint or limiting_joint
            except Exception as exc:
                self._stop_reason = self._stop_reason or f"return_home_failed: {exc}"
        if self._recorder is not None and not self._finished:
            self._write_summary()
        self._stack.close()

    @property
    def phase(self) -> PointLoadPhase:
        return self._phase

    @property
    def is_complete(self) -> bool:
        return self._phase == "complete"

    @property
    def run_dir(self) -> Path:
        assert self._recorder is not None
        return self._recorder.run_dir

    @property
    def instruction(self) -> str:
        if self._phase == "complete":
            return "Point load test complete."
        if self._phase == "await_pose_confirm":
            return (
                f"Preview the approach to pose {self.pose!r}, then confirm when "
                "the arm area is clear."
            )
        if self._phase == "await_bring_home":
            return "All links recorded. Press Bring Home to return and finish."
        if self._current_link is None:
            return ""
        link, joint_names = self._current_link
        joints = ", ".join(joint_names)
        if self._phase == "await_ready":
            return (
                f"Point load: {link} ({joints}). "
                "Apply the test load, then press Ready."
            )
        return f"Record load details for {link}."

    @property
    def progress_text(self) -> str:
        total = len(LINK_JOINTS)
        return f"Links tested: {self._links_tested} / {total}"

    def confirm_approach(self) -> None:
        """Move to the hold pose after operator confirmation."""
        if self._phase != "await_pose_confirm":
            raise RuntimeError("Not waiting for pose approach confirmation.")
        self._move_to_test_pose()

    def _move_to_test_pose(self) -> None:
        assert self._arm is not None
        reached_home, _, home_stop, home_limit = prepare_hold_pose(
            self._arm,
            DEFAULT_HOME_NAME,
            config_path=self.config_path,
            e2e_config_path=self.e2e_config_path,
        )
        if home_stop:
            self._stopped_early = True
            self._stop_reason = home_stop
            self._limiting_joint = home_limit
            self._finish()
            return

        self._reached_all = reached_home
        if self.pose != DEFAULT_HOME_NAME:
            reached_pose, _, move_stop_reason, move_limiting_joint = prepare_hold_pose(
                self._arm,
                self.pose,
                config_path=self.config_path,
                e2e_config_path=self.e2e_config_path,
            )
            self._reached_all = reached_pose
            if move_stop_reason:
                self._stopped_early = True
                self._stop_reason = move_stop_reason
                self._limiting_joint = move_limiting_joint
                self._finish()
                return

        baseline = self._arm.sample()
        self._monitor = make_safety_monitor(
            self._arm,
            reference_positions={name: s.position for name, s in baseline.items()},
            baseline_temperatures={name: s.temperature for name, s in baseline.items()},
            abort_event=self._abort_event,
        )
        self._reference = {name: sample.position for name, sample in baseline.items()}
        self._link_queue = list(LINK_JOINTS.items())
        self._start_next_link()

    def mark_ready(self) -> None:
        if self._phase != "await_ready":
            raise RuntimeError("Not waiting for ready.")
        self._phase = "await_inputs"

    def record(self, load_description: str, operator_notes: str) -> PointLoadRecordResult:
        if self._phase != "await_inputs" or self._current_link is None:
            raise RuntimeError("Not waiting for load details.")
        assert self._arm is not None
        assert self._recorder is not None
        assert self._monitor is not None

        link, joint_names = self._current_link
        snapshot = self._arm.sample()
        result = self._monitor.evaluate(snapshot)
        flex_deg = max_flex_deg(snapshot, self._reference, joint_names)
        primary_joint = joint_names[0]

        self._recorder.write_row(
            {
                "timestamp_utc": utc_now().isoformat(),
                "joint": primary_joint,
                "link": link,
                "load_description": load_description,
                "operator_notes": operator_notes,
                "max_flex_deg": flex_deg,
            }
        )
        self._links_tested += 1

        stopped_early = result.should_stop
        if stopped_early:
            self._stopped_early = True
            self._stop_reason = result.reason
            self._limiting_joint = result.triggering_joint
            self._finish()
        else:
            self._start_next_link()

        return PointLoadRecordResult(
            link=link,
            max_flex_deg=flex_deg,
            stopped_early=stopped_early,
            stop_reason=result.reason,
            limiting_joint=result.triggering_joint,
        )

    def bring_home(self) -> None:
        """Return to home and finish the run."""
        if self._finished:
            return
        assert self._arm is not None
        motion = load_motion_config(self.pose, e2e_config_path=self.e2e_config_path)
        reached_home, stop_reason, limiting_joint = move_home_scurve(
            self._arm,
            config_path=self.config_path,
            e2e_config_path=self.e2e_config_path,
            motion=motion,
            monitor=self._monitor,
        )
        self._returned_home = reached_home and not stop_reason
        if stop_reason:
            self._stopped_early = True
            self._stop_reason = stop_reason
            self._limiting_joint = limiting_joint
        self._finish()

    def stop(self) -> None:
        self.bring_home()

    def _start_next_link(self) -> None:
        if self._link_queue:
            self._current_link = self._link_queue.pop(0)
            self._phase = "await_ready"
            return
        self._current_link = None
        self._phase = "await_bring_home"

    def _finish(self) -> None:
        self._phase = "complete"
        self._write_summary()
        self._finished = True

    def _write_summary(self) -> None:
        assert self._recorder is not None
        self._recorder.set_summary(
            pose_reached=self._reached_all,
            links_tested=self._links_tested,
            stopped_early=self._stopped_early,
            stop_reason=self._stop_reason or None,
            limiting_joint=self._limiting_joint,
            returned_home=self._returned_home,
        )
