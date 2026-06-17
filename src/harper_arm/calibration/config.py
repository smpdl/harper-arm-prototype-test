"""Calibration motion and validation settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CALIBRATION_PATH = Path("config/calibration.yaml")

@dataclass(frozen=True)
class CalibrationSettings:
    profile_velocity_rpm: float
    profile_acceleration_rpm2: float | None
    step_small_deg: float
    step_large_deg: float
    step_xlarge_deg: float
    validation_tolerance_ticks: int
    validation_repeatability_deg: float


def format_jog_magnitude(step_deg: float) -> str:
    if step_deg == int(step_deg):
        return str(int(step_deg))
    return format(step_deg, "g")


def jog_step_degrees(settings: CalibrationSettings) -> tuple[float, float, float]:
    return (settings.step_small_deg, settings.step_large_deg, settings.step_xlarge_deg)


def jog_commands(settings: CalibrationSettings) -> dict[str, float]:
    """Map jog command labels such as ``+5`` to signed step sizes from settings."""
    commands: dict[str, float] = {}
    for step_deg in jog_step_degrees(settings):
        magnitude = format_jog_magnitude(step_deg)
        commands[f"+{magnitude}"] = step_deg
        commands[f"-{magnitude}"] = -step_deg
    return commands


def jog_command_rows(
    settings: CalibrationSettings,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return negative and positive jog button labels derived from settings."""
    small, large, xlarge = jog_step_degrees(settings)
    negative = tuple(
        f"-{format_jog_magnitude(step_deg)}" for step_deg in (xlarge, large, small)
    )
    positive = tuple(
        f"+{format_jog_magnitude(step_deg)}" for step_deg in (small, large, xlarge)
    )
    return negative, positive


def load_calibration_settings(
    path: Path | str = DEFAULT_CALIBRATION_PATH,
) -> CalibrationSettings:
    config_path = Path(path)
    raw: Any = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("calibration config root must be a mapping.")

    def _positive_float(key: str, default: float) -> float:
        value = float(raw.get(key, default))
        if value <= 0:
            raise ValueError(f"{key} must be positive.")
        return value

    def _positive_int(key: str, default: int) -> int:
        value = int(raw.get(key, default))
        if value <= 0:
            raise ValueError(f"{key} must be positive.")
        return value

    accel_raw = raw.get("profile_acceleration_rpm2")
    profile_acceleration_rpm2: float | None
    if accel_raw is None:
        profile_acceleration_rpm2 = None
    else:
        profile_acceleration_rpm2 = float(accel_raw)
        if profile_acceleration_rpm2 <= 0:
            raise ValueError("profile_acceleration_rpm2 must be positive.")

    return CalibrationSettings(
        profile_velocity_rpm=_positive_float("profile_velocity_rpm", 23.0),
        profile_acceleration_rpm2=profile_acceleration_rpm2,
        step_small_deg=_positive_float("step_small_deg", 5.0),
        step_large_deg=_positive_float("step_large_deg", 10.0),
        step_xlarge_deg=_positive_float("step_xlarge_deg", 30.0),
        validation_tolerance_ticks=_positive_int("validation_tolerance_ticks", 15),
        validation_repeatability_deg=_positive_float("validation_repeatability_deg", 0.5),
    )
