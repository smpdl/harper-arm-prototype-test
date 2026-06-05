"""Test suite metadata for the TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FieldType = Literal["text", "int", "float", "bool", "joint", "pose"]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    field_type: FieldType
    required: bool = False
    default: str | int | float | bool | None = None
    placeholder: str = ""


@dataclass(frozen=True)
class TestSpec:
    suite: Literal["motor", "structural"]
    name: str
    label: str
    kind: str
    fields: tuple[FieldSpec, ...]


MOTOR_READ_ONLY_TESTS: tuple[str, ...] = (
    "ping",
    "present_voltage",
    "present_temperature",
    "current_no_load",
)

MOTOR_MOTION_TESTS: tuple[str, ...] = (
    "power_on_response",
    "range_of_motion",
    "position_accuracy",
    "velocity_tracking",
    "thermal_rise",
)

MOTOR_TEST_NAMES: tuple[str, ...] = MOTOR_READ_ONLY_TESTS + MOTOR_MOTION_TESTS

STRUCTURAL_TEST_NAMES: tuple[str, ...] = (
    "self_weight_hold",
    "point_load",
    "max_payload",
)

INTERACTIVE_STRUCTURAL_TESTS: frozenset[str] = frozenset({"point_load", "max_payload"})


def _motor_fields(test: str) -> tuple[FieldSpec, ...]:
    fields: list[FieldSpec] = [
        FieldSpec("joint", "Joint", "joint", required=True),
    ]

    if test == "range_of_motion":
        fields.append(
            FieldSpec(
                "steps",
                "Steps",
                "int",
                placeholder="Waypoints across position limits",
            )
        )
    elif test == "position_accuracy":
        fields.append(
            FieldSpec(
                "trials",
                "Trials",
                "int",
                placeholder="Trials per target angle",
            )
        )
    elif test == "velocity_tracking":
        fields.append(
            FieldSpec(
                "step_hold_s",
                "Step hold (s)",
                "float",
                placeholder="Seconds to hold each velocity step",
            )
        )
    elif test == "thermal_rise":
        fields.extend(
            [
                FieldSpec(
                    "duration_s",
                    "Duration (s)",
                    "float",
                    placeholder="Sampling duration",
                ),
                FieldSpec(
                    "interval_s",
                    "Interval (s)",
                    "float",
                    placeholder="Sample interval",
                ),
                FieldSpec(
                    "load_fraction",
                    "Load fraction",
                    "float",
                    placeholder="Fraction of joint current limit",
                ),
            ]
        )

    return tuple(fields)


def _structural_fields(test: str) -> tuple[FieldSpec, ...]:
    fields: list[FieldSpec] = []

    if test in {"self_weight_hold", "point_load", "max_payload"}:
        fields.append(
            FieldSpec(
                "pose",
                "Pose",
                "pose",
                default="home",
            )
        )

    if test == "self_weight_hold":
        fields.extend(
            [
                FieldSpec(
                    "duration_s",
                    "Duration (s)",
                    "float",
                    placeholder="Hold duration",
                ),
                FieldSpec(
                    "interval_s",
                    "Interval (s)",
                    "float",
                    placeholder="Sample interval",
                ),
            ]
        )
    elif test == "max_payload":
        fields.append(
            FieldSpec(
                "settle_time_s",
                "Settle time (s)",
                "float",
                placeholder="Seconds after each payload step",
            )
        )

    if test in INTERACTIVE_STRUCTURAL_TESTS:
        fields.append(
            FieldSpec(
                "interactive",
                "Interactive prompts",
                "bool",
                default=False,
                placeholder="Must be enabled; TUI cannot run this test without stdin",
            )
        )

    return tuple(fields)


def motor_test_specs() -> tuple[TestSpec, ...]:
    return tuple(
        TestSpec(
            suite="motor",
            name=name,
            label=name.replace("_", " "),
            kind="read-only" if name in MOTOR_READ_ONLY_TESTS else "motion",
            fields=_motor_fields(name),
        )
        for name in MOTOR_TEST_NAMES
    )


def structural_test_specs() -> tuple[TestSpec, ...]:
    return tuple(
        TestSpec(
            suite="structural",
            name=name,
            label=name.replace("_", " "),
            kind="structural",
            fields=_structural_fields(name),
        )
        for name in STRUCTURAL_TEST_NAMES
    )


def all_test_specs() -> tuple[TestSpec, ...]:
    return motor_test_specs() + structural_test_specs()
