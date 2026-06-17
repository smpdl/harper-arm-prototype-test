"""Load editable e2e motion-pattern configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from harper_arm.motion import MotionKeyframe, MotionPlan

DEFAULT_E2E_CONFIG_PATH = Path("config/e2e.yaml")
DEFAULT_PROFILE_VELOCITY_RPM = 8.0
DEFAULT_SCURVE_MAX_VELOCITY_DEG_S = 20.0
DEFAULT_SCURVE_MAX_ACCELERATION_DEG_S2 = 40.0
DEFAULT_SCURVE_SAMPLE_PERIOD_S = 0.10
DEFAULT_HOLD_S = 0.75


@dataclass(frozen=True)
class E2ETestConfig:
    """One configured e2e motion test."""

    name: str
    label: str
    plan: MotionPlan
    profile_velocity_rpm: float
    profile_acceleration_rpm2: float | None
    scurve_max_velocity_deg_s: float
    scurve_max_acceleration_deg_s2: float
    scurve_sample_period_s: float


@dataclass(frozen=True)
class E2EConfig:
    """All configured e2e tests from ``config/e2e.yaml``."""

    tests: Mapping[str, E2ETestConfig]


def _require_mapping(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping.")
    return value


def load_e2e_config(path: Path | str = DEFAULT_E2E_CONFIG_PATH) -> E2EConfig:
    """Load e2e motion plans and conservative execution defaults."""
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    document = _require_mapping(raw, label="e2e config root")

    default_profile_velocity_rpm = float(
        document.get("default_profile_velocity_rpm", DEFAULT_PROFILE_VELOCITY_RPM)
    )
    if default_profile_velocity_rpm <= 0:
        raise ValueError("default_profile_velocity_rpm must be positive.")

    default_hold_s = float(document.get("default_hold_s", DEFAULT_HOLD_S))
    if default_hold_s < 0:
        raise ValueError("default_hold_s must be non-negative.")

    default_scurve_max_velocity_deg_s = _positive_float(
        document,
        "default_scurve_max_velocity_deg_s",
        DEFAULT_SCURVE_MAX_VELOCITY_DEG_S,
    )
    default_scurve_max_acceleration_deg_s2 = _positive_float(
        document,
        "default_scurve_max_acceleration_deg_s2",
        DEFAULT_SCURVE_MAX_ACCELERATION_DEG_S2,
    )
    default_scurve_sample_period_s = _positive_float(
        document,
        "default_scurve_sample_period_s",
        DEFAULT_SCURVE_SAMPLE_PERIOD_S,
    )

    default_accel_raw = document.get("default_profile_acceleration_rpm2")
    default_profile_acceleration_rpm2: float | None
    if default_accel_raw is None:
        default_profile_acceleration_rpm2 = None
    else:
        default_profile_acceleration_rpm2 = float(default_accel_raw)
        if default_profile_acceleration_rpm2 <= 0:
            raise ValueError("default_profile_acceleration_rpm2 must be positive.")

    tests_raw = _require_mapping(document.get("tests"), label="tests")
    tests: dict[str, E2ETestConfig] = {}
    for name, value in tests_raw.items():
        test = _require_mapping(value, label=f"tests.{name}")
        label = str(test.get("label", name.replace("_", " ")))
        profile_velocity_rpm = float(
            test.get("profile_velocity_rpm", default_profile_velocity_rpm)
        )
        if profile_velocity_rpm <= 0:
            raise ValueError(f"tests.{name}.profile_velocity_rpm must be positive.")

        accel_raw = test.get("profile_acceleration_rpm2", default_profile_acceleration_rpm2)
        profile_acceleration_rpm2: float | None
        if accel_raw is None:
            profile_acceleration_rpm2 = None
        else:
            profile_acceleration_rpm2 = float(accel_raw)
            if profile_acceleration_rpm2 <= 0:
                raise ValueError(f"tests.{name}.profile_acceleration_rpm2 must be positive.")

        scurve_max_velocity_deg_s = _positive_float(
            test,
            "scurve_max_velocity_deg_s",
            default_scurve_max_velocity_deg_s,
            label=f"tests.{name}.scurve_max_velocity_deg_s",
        )
        scurve_max_acceleration_deg_s2 = _positive_float(
            test,
            "scurve_max_acceleration_deg_s2",
            default_scurve_max_acceleration_deg_s2,
            label=f"tests.{name}.scurve_max_acceleration_deg_s2",
        )
        scurve_sample_period_s = _positive_float(
            test,
            "scurve_sample_period_s",
            default_scurve_sample_period_s,
            label=f"tests.{name}.scurve_sample_period_s",
        )

        keyframes_raw = test.get("keyframes")
        if not isinstance(keyframes_raw, list) or not keyframes_raw:
            raise ValueError(f"tests.{name}.keyframes must be a non-empty list.")

        keyframes: list[MotionKeyframe] = []
        for index, item in enumerate(keyframes_raw, start=1):
            keyframe = _require_mapping(item, label=f"tests.{name}.keyframes[{index}]")
            offsets_raw = _require_mapping(
                keyframe.get("offsets_deg"),
                label=f"tests.{name}.keyframes[{index}].offsets_deg",
            )
            offsets = {joint: float(offset) for joint, offset in offsets_raw.items()}
            if not offsets:
                raise ValueError(
                    f"tests.{name}.keyframes[{index}].offsets_deg cannot be empty."
                )
            hold_s = float(keyframe.get("hold_s", default_hold_s))
            if hold_s < 0:
                raise ValueError(f"tests.{name}.keyframes[{index}].hold_s must be >= 0.")
            keyframes.append(
                MotionKeyframe(
                    name=str(keyframe.get("name", f"step {index}")),
                    offsets_deg=offsets,
                    hold_s=hold_s,
                )
            )

        tests[str(name)] = E2ETestConfig(
            name=str(name),
            label=label,
            plan=MotionPlan(name=str(name), keyframes=tuple(keyframes)),
            profile_velocity_rpm=profile_velocity_rpm,
            profile_acceleration_rpm2=profile_acceleration_rpm2,
            scurve_max_velocity_deg_s=scurve_max_velocity_deg_s,
            scurve_max_acceleration_deg_s2=scurve_max_acceleration_deg_s2,
            scurve_sample_period_s=scurve_sample_period_s,
        )

    return E2EConfig(tests=tests)


def _positive_float(
    document: Mapping[str, Any],
    key: str,
    default: float,
    *,
    label: str | None = None,
) -> float:
    value = float(document.get(key, default))
    if value <= 0:
        raise ValueError(f"{label or key} must be positive.")
    return value
