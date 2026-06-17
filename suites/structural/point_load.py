"""Operator-assisted point-load flex assessment per arm link."""

from __future__ import annotations

from pathlib import Path

from harper_arm.joint import DEFAULT_CONFIG_PATH
from suites.e2e.config import DEFAULT_E2E_CONFIG_PATH

from .helpers import DEFAULT_RESULTS_ROOT
from .operator import PointLoadOperator


def _prompt(label: str) -> str:
    return input(f"{label}: ").strip()


def run(
    *,
    pose: str = "home",
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    **_: object,
) -> Path:
    with PointLoadOperator(
        pose=pose,
        config_path=config_path,
        e2e_config_path=e2e_config_path,
        results_root=results_root,
    ) as operator:
        while not operator.is_complete:
            print(f"\n{operator.instruction}")
            if operator.phase == "await_pose_confirm":
                answer = input("Move to hold pose? [y/N/q] ").strip().lower()
                if answer == "y":
                    operator.confirm_approach()
                elif answer == "q":
                    operator.stop()
                continue
            if operator.phase == "await_bring_home":
                answer = input("Bring home? [y/N/q] ").strip().lower()
                if answer == "y":
                    operator.bring_home()
                elif answer == "q":
                    operator.stop()
                continue
            if operator.phase == "await_ready":
                _prompt("Press Enter when ready")
                operator.mark_ready()
            elif operator.phase == "await_inputs":
                load_description = _prompt("Load description")
                operator_notes = _prompt("Operator notes")
                result = operator.record(load_description, operator_notes)
                print(
                    f"Recorded {result.link}: max flex {result.max_flex_deg:.2f}°"
                )
                if result.stopped_early:
                    print(f"Stopped early: {result.stop_reason}")
        return operator.run_dir
