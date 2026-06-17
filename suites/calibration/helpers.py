"""Shared helpers for calibration suite run() functions."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harper_arm.calibration.config import DEFAULT_CALIBRATION_PATH, load_calibration_settings
from harper_arm.calibration.errors import CalibrationError
from harper_arm.calibration.persist import DEFAULT_PARTIAL_PATH, save_partial_session
from harper_arm.calibration.session import CalibrationSession
from harper_arm.joint import DEFAULT_CONFIG_PATH, Joint
from harper_arm.logging import TestRun
from harper_arm.sampling import operator_abort_guard

DEFAULT_RESULTS_ROOT = Path("results")


def utc_now() -> datetime:
    return datetime.now(UTC)


def require_interactive(test: str, interactive: bool) -> None:
    if not interactive:
        raise ValueError(
            f"{test} requires interactive=True for operator-supervised calibration."
        )


@contextmanager
def calibration_test_run(
    *,
    test: str,
    schema: str,
    joint_name: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    calibration_path: Path | str = DEFAULT_CALIBRATION_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    metadata: dict[str, Any] | None = None,
) -> Iterator[tuple[Joint, TestRun, CalibrationSession, threading.Event]]:
    """Open one joint, track partial progress, and recover on failure."""
    settings = load_calibration_settings(calibration_path)
    session = CalibrationSession()
    partial_path = save_partial_session(session, DEFAULT_PARTIAL_PATH)
    connected_joint = Joint.open(joint_name=joint_name, config_path=config_path)
    try:
        with operator_abort_guard() as abort_event:
            with TestRun(
                suite="calibration",
                test=test,
                schema=schema,
                results_root=results_root,
                joint=joint_name,
                metadata={
                    **(metadata or {}),
                    "profile_velocity_rpm": settings.profile_velocity_rpm,
                    "step_small_deg": settings.step_small_deg,
                    "step_large_deg": settings.step_large_deg,
                },
            ) as recorder:
                session.joint(joint_name)
                try:
                    yield connected_joint, recorder, session, abort_event
                except CalibrationError as exc:
                    save_partial_session(session, partial_path, error=str(exc))
                    connected_joint.torque_disable()
                    raise
    finally:
        connected_joint.close()
