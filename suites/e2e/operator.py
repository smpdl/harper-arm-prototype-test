"""Step-by-step e2e motion execution for TUI and terminal callers."""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from harper_arm import units
from harper_arm.arm import FullArm
from harper_arm.config import load_arm_config, require_arm_calibrated, resolve_home_pose
from harper_arm.joint import DEFAULT_CONFIG_PATH
from harper_arm.logging import TestRun
from harper_arm.motion import ResolvedKeyframe, resolve_plan
from harper_arm.motor import POSITION_TOLERANCE_TICKS, move_to_ticks, set_positions
from harper_arm.safety import SafetyMonitor
from harper_arm.sampling import JointSample, operator_abort_guard
from harper_arm.trajectory import Trajectory, synchronized_scurve_trajectory

from .config import DEFAULT_E2E_CONFIG_PATH, E2ETestConfig, load_e2e_config

DEFAULT_RESULTS_ROOT = Path("results")
E2EPhase = Literal["await_confirm", "complete"]


@dataclass(frozen=True)
class E2EStepResult:
    """Outcome of one confirmed e2e keyframe."""

    keyframe_index: int
    keyframe_name: str
    stopped_early: bool
    stop_reason: str
    limiting_joint: str | None


class E2EOperator:
    """Own one open e2e run and expose explicit preview/step operations.

    The operator resolves the complete motion plan before enabling torque.  That
    ordering matters for hardware safety: a bad target should fail while the arm
    is idle, not halfway through a multi-joint movement.
    """

    def __init__(
        self,
        *,
        test: str,
        config_path: Path | str = DEFAULT_CONFIG_PATH,
        e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH,
        results_root: Path = DEFAULT_RESULTS_ROOT,
    ) -> None:
        self.test = test
        self.config_path = Path(config_path)
        self.e2e_config_path = Path(e2e_config_path)
        self.results_root = results_root
        self._stack = ExitStack()
        self._arm: FullArm | None = None
        self._recorder: TestRun | None = None
        self._config: E2ETestConfig | None = None
        self._resolved: tuple[ResolvedKeyframe, ...] = ()
        self._home_pose: dict[str, int] = {}
        self._monitor: SafetyMonitor | None = None
        self._models: dict[str, str] = {}
        self._step_index = 0
        self._phase: E2EPhase = "complete"
        self._finished = False
        self._returned_home = False
        self._stopped_early = False
        self._stop_reason = ""
        self._limiting_joint: str | None = None
        self._abort_event: threading.Event | None = None

    def open(self) -> E2EOperator:
        return self.__enter__()

    def close(self) -> None:
        self.__exit__(None, None, None)

    def __enter__(self) -> E2EOperator:
        all_tests = load_e2e_config(self.e2e_config_path).tests
        try:
            self._config = all_tests[self.test]
        except KeyError as exc:
            known = ", ".join(sorted(all_tests))
            raise ValueError(f"unknown e2e test {self.test!r}; known: {known}") from exc

        arm_config = load_arm_config(self.config_path)
        require_arm_calibrated(arm_config)
        # Resolve the entire plan up front.  This catches missing home_position,
        # bad joint names, or out-of-limit targets before the bus is opened.
        self._resolved = resolve_plan(arm_config, self._config.plan)
        self._home_pose = resolve_home_pose(arm_config)

        arm = FullArm.open(config_path=self.config_path)
        abort_event = self._stack.enter_context(operator_abort_guard())
        self._abort_event = abort_event
        recorder = self._stack.enter_context(
            TestRun(
                suite="e2e",
                test=self.test,
                schema="e2e_motion",
                results_root=self.results_root,
                metadata={
                    "e2e_config_path": str(self.e2e_config_path),
                    "profile_velocity_rpm": self._config.profile_velocity_rpm,
                    "scurve_max_velocity_deg_s": (
                        self._config.scurve_max_velocity_deg_s
                    ),
                    "scurve_max_acceleration_deg_s2": (
                        self._config.scurve_max_acceleration_deg_s2
                    ),
                    "scurve_sample_period_s": self._config.scurve_sample_period_s,
                    "keyframes": [keyframe.name for keyframe in self._resolved],
                },
            )
        )

        self._arm = arm
        self._recorder = recorder
        self._models = arm.joint_models()

        # Position mode and torque are configured only after the plan is known
        # to be valid.  The low profile velocity makes operator-confirmed tests
        # easier to observe and abort.
        arm.prepare_motion_bus(
            joint_name=None,
            profile_velocity_rpm=self._config.profile_velocity_rpm,
            profile_acceleration_rpm2=self._config.profile_acceleration_rpm2,
        )
        self._move_home()
        baseline = arm.sample()
        self._monitor = SafetyMonitor(
            current_limits=arm.current_limits(),
            baseline_temperatures={name: sample.temperature for name, sample in baseline.items()},
            abort_event=abort_event,
        )
        self._phase = "await_confirm"
        return self

    def __exit__(self, *exc_info: object) -> None:
        skip_homing = (
            self._abort_event is not None and self._abort_event.is_set()
        )
        if self._arm is not None and not self._returned_home and not skip_homing:
            try:
                self._move_home()
            except Exception as exc:
                self._stop_reason = self._stop_reason or f"return_home_failed: {exc}"
        if self._recorder is not None and not self._finished:
            self._write_summary()
        if self._arm is not None:
            self._arm.close(skip_homing=True)
            self._arm = None
        self._stack.close()

    @property
    def phase(self) -> E2EPhase:
        return self._phase

    @property
    def is_complete(self) -> bool:
        return self._phase == "complete"

    @property
    def run_dir(self) -> Path:
        assert self._recorder is not None
        return self._recorder.run_dir

    @property
    def current_keyframe(self) -> ResolvedKeyframe | None:
        if self._step_index >= len(self._resolved):
            return None
        return self._resolved[self._step_index]

    @property
    def progress_text(self) -> str:
        total = len(self._resolved)
        current = min(self._step_index + 1, total)
        return f"Keyframe {current} / {total}"

    @property
    def instruction(self) -> str:
        keyframe = self.current_keyframe
        if keyframe is None:
            return "E2E motion complete."
        return f"Preview '{keyframe.name}', then confirm when the arm area is clear."

    def preview_lines(self) -> list[str]:
        """Return human-readable target lines for the current keyframe."""
        keyframe = self.current_keyframe
        if keyframe is None:
            return ["No remaining keyframes."]
        lines = [f"{keyframe.index}. {keyframe.name}"]
        for target in keyframe.targets.values():
            lines.append(
                f"  {target.joint}: {target.offset_deg:+.1f} deg "
                f"-> {target.target_ticks} ticks"
            )
        return lines

    def confirm_step(self) -> E2EStepResult:
        """Move one operator-confirmed keyframe and sample safety telemetry."""
        if self._phase != "await_confirm":
            raise RuntimeError("e2e operator is not waiting for confirmation")
        keyframe = self.current_keyframe
        if keyframe is None:
            self._finish()
            return E2EStepResult(0, "complete", False, "", None)

        assert self._arm is not None
        assert self._recorder is not None
        assert self._monitor is not None

        self._returned_home = False
        reached, stop_reason, limiting_joint = self._move_keyframe_scurve(keyframe)

        if keyframe.hold_s > 0:
            time.sleep(keyframe.hold_s)

        final_snapshot = self._arm.sample()
        if not stop_reason:
            safety = self._monitor.evaluate(final_snapshot)
            stop_reason = safety.reason
            limiting_joint = safety.triggering_joint
        self._record_keyframe_rows(keyframe, reached, final_snapshot, stop_reason)

        self._step_index += 1
        if stop_reason:
            self._stopped_early = True
            self._stop_reason = stop_reason
            self._limiting_joint = limiting_joint
            self._finish()
        elif self._step_index >= len(self._resolved):
            self._finish()

        return E2EStepResult(
            keyframe_index=keyframe.index,
            keyframe_name=keyframe.name,
            stopped_early=bool(stop_reason),
            stop_reason=stop_reason,
            limiting_joint=limiting_joint,
        )

    def stop(self) -> None:
        if self._abort_event is not None:
            self._abort_event.set()
        self._stopped_early = True
        self._stop_reason = self._stop_reason or "operator_stop"
        self._finish()

    def _move_home(self) -> None:
        """Return all joints to home in parallel (E2E only — not sequential homing)."""
        assert self._arm is not None
        reached_all = True
        for joint_name, target_ticks in self._home_pose.items():
            reached, _ = move_to_ticks(self._arm, target_ticks, joint_name=joint_name)
            reached_all = reached_all and reached
        if not reached_all:
            self._returned_home = False
            raise RuntimeError("failed to reach calibrated home position")
        self._returned_home = True

    def _move_keyframe_scurve(
        self,
        keyframe: ResolvedKeyframe,
    ) -> tuple[dict[str, tuple[bool, int]], str, str | None]:
        """Stream synchronized S-curve setpoints for one confirmed keyframe.

        We command intermediate setpoints instead of jumping straight to the
        final tick target.  The setpoints share one duration across all joints,
        matching the synchronization approach recommended by s-curve-beta.
        """
        assert self._arm is not None
        assert self._config is not None
        assert self._monitor is not None

        start_snapshot = self._arm.sample()
        starts = {
            joint_name: start_snapshot[joint_name].position
            for joint_name in keyframe.targets
        }
        targets = {
            joint_name: target.target_ticks
            for joint_name, target in keyframe.targets.items()
        }
        trajectory = synchronized_scurve_trajectory(
            starts,
            targets,
            max_velocity_deg_s=self._config.scurve_max_velocity_deg_s,
            max_acceleration_deg_s2=self._config.scurve_max_acceleration_deg_s2,
            sample_period_s=self._config.scurve_sample_period_s,
        )
        stop_reason, limiting_joint = self._execute_trajectory(trajectory)
        snapshot = self._arm.sample()
        reached = {
            joint_name: (
                abs(snapshot[joint_name].position - target_ticks)
                <= POSITION_TOLERANCE_TICKS,
                snapshot[joint_name].position,
            )
            for joint_name, target_ticks in targets.items()
        }
        return reached, stop_reason, limiting_joint

    def _execute_trajectory(self, trajectory: Trajectory) -> tuple[str, str | None]:
        """Send sampled S-curve setpoints and check safety between samples."""
        assert self._arm is not None
        assert self._monitor is not None

        started = time.monotonic()
        for point in trajectory.points:
            if self._abort_event is not None and self._abort_event.is_set():
                return "operator_stop", None

            # Sleep against the planned start time instead of a fixed delay so a
            # slow serial write does not compound timing drift over many points.
            remaining_s = started + point.elapsed_s - time.monotonic()
            if remaining_s > 0:
                time.sleep(remaining_s)

            set_positions(self._arm, point.targets)

            snapshot = self._arm.sample()
            safety = self._monitor.evaluate(snapshot)
            if safety.should_stop:
                return safety.reason, safety.triggering_joint

        return "", None

    def _finish(self) -> None:
        self._phase = "complete"
        self._write_summary()
        self._finished = True

    def _write_summary(self) -> None:
        assert self._recorder is not None
        self._recorder.set_summary(
            stopped_early=self._stopped_early,
            stop_reason=self._stop_reason or None,
            limiting_joint=self._limiting_joint,
            keyframes_completed=self._step_index,
            returned_home=self._returned_home,
            rows=self._recorder.row_count,
        )

    def _record_keyframe_rows(
        self,
        keyframe: ResolvedKeyframe,
        reached: Mapping[str, tuple[bool, int]],
        snapshot: Mapping[str, JointSample],
        stop_reason: str,
    ) -> None:
        assert self._recorder is not None
        for joint_name, target in keyframe.targets.items():
            sample = snapshot[joint_name]
            reached_target, measured_ticks = reached[joint_name]
            self._recorder.write_row(
                {
                    "timestamp_utc": sample.timestamp.isoformat(),
                    "keyframe_index": keyframe.index,
                    "keyframe": keyframe.name,
                    "joint": joint_name,
                    "offset_deg": target.offset_deg,
                    "target_ticks": target.target_ticks,
                    "measured_ticks": measured_ticks,
                    "error_deg": units.position_error_deg(
                        measured_ticks,
                        target.target_ticks,
                    ),
                    "current_ma": units.current_to_ma(
                        sample.current,
                        model=self._models[joint_name],
                    ),
                    "temperature_c": units.temperature_to_celsius(sample.temperature),
                    "reached": reached_target,
                    "stop_reason": stop_reason,
                }
            )


def run_terminal_confirmed(
    *,
    test: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
) -> Path:
    """Run an e2e motion test with stdin confirmation before every keyframe."""
    with E2EOperator(
        test=test,
        config_path=config_path,
        e2e_config_path=e2e_config_path,
        results_root=results_root,
    ) as operator:
        while not operator.is_complete:
            print()
            for line in operator.preview_lines():
                print(line)
            answer = input("Move this keyframe? [y/N/q] ").strip().lower()
            if answer == "q":
                operator.stop()
                break
            if answer != "y":
                continue
            result = operator.confirm_step()
            if result.stopped_early:
                print(f"Stopped early: {result.stop_reason}")
        return operator.run_dir
