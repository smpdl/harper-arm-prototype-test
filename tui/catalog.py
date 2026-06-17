"""Test suite metadata for the TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FieldType = Literal["text", "int", "float", "bool", "joint", "pose"]


CalibrationJointFilter = Literal["backdriveable", "non_backdriveable"]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    field_type: FieldType
    required: bool = False
    default: str | int | float | bool | None = None
    placeholder: str = ""
    joint_filter: CalibrationJointFilter | None = None


@dataclass(frozen=True)
class TestSpec:
    suite: Literal["motor", "structural", "calibration", "e2e"]
    name: str
    label: str
    kind: str
    fields: tuple[FieldSpec, ...]
    browser_label: str = ""

    @property
    def tree_label(self) -> str:
        return self.browser_label or self.label


MOTOR_READ_ONLY_TESTS: tuple[str, ...] = (
    "ping",
    "present_voltage",
    "present_temperature",
    "current_no_load",
)

MOTOR_MOTION_TESTS: tuple[str, ...] = (
    "power_on_response",
    "position_accuracy",
)

MOTOR_WHOLE_ARM_TESTS: tuple[str, ...] = ("position_accuracy",)

MOTOR_POSITION_TESTS: tuple[str, ...] = (
    "power_on_response",
    "position_accuracy",
)

MOTOR_TEST_NAMES: tuple[str, ...] = MOTOR_READ_ONLY_TESTS + MOTOR_MOTION_TESTS

STRUCTURAL_TEST_NAMES: tuple[str, ...] = (
    "self_weight_hold",
    "point_load",
    "max_payload",
)

E2E_TEST_NAMES: tuple[str, ...] = (
    "reach_sideways",
    "reach_overhead",
    "arm_wave",
    "wrist_flexion_sweep",
    "forearm_rotation_sweep",
    "handshake_motion",
    "shoulder_rotation_sweep",
    "combined_wrist_forearm_rotation",
)

TUI_STRUCTURAL_SESSION_TESTS: frozenset[str] = frozenset({"point_load"})

CALIBRATION_TEST_NAMES: tuple[str, ...] = (
    "non_backdriveable",
    "backdriveable",
    "validate",
)

TUI_CALIBRATION_SESSION_TESTS: frozenset[str] = frozenset(
    {"backdriveable", "non_backdriveable"}
)

_JOINT_FIELD = FieldSpec("joint", "Joint", "joint", required=True)


def _motor_fields(test: str) -> tuple[FieldSpec, ...]:
    fields: list[FieldSpec] = [
        FieldSpec("joint", "Joint", "joint", required=True),
    ]

    if test in MOTOR_POSITION_TESTS:
        fields.append(
            FieldSpec(
                "profile_velocity_rpm",
                "Profile velocity (rpm)",
                "float",
                placeholder="Override arm.yaml per-joint default",
            )
        )

    if test == "position_accuracy":
        fields.append(
            FieldSpec(
                "trials",
                "Trials",
                "int",
                placeholder="Trials per target angle",
            )
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
        fields.extend(
            [
                FieldSpec(
                    "hold_time_s",
                    "Hold time (s)",
                    "float",
                    placeholder="Seconds to hold under load",
                ),
                FieldSpec(
                    "interval_s",
                    "Interval (s)",
                    "float",
                    placeholder="Sample interval",
                ),
                FieldSpec(
                    "payload_kg",
                    "Payload (kg)",
                    "float",
                    placeholder="Load applied at end effector",
                ),
            ]
        )

    return tuple(fields)


def _tui_motor_fields(_test: str) -> tuple[FieldSpec, ...]:
    return (_JOINT_FIELD,)


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


def tui_motor_test_specs() -> tuple[TestSpec, ...]:
    return tuple(
        TestSpec(
            suite="motor",
            name=name,
            label=name.replace("_", " "),
            browser_label=name.replace("_", " "),
            kind="read-only" if name in MOTOR_READ_ONLY_TESTS else "motion",
            fields=_tui_motor_fields(name),
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


def tui_structural_test_specs() -> tuple[TestSpec, ...]:
    _short = {
        "self_weight_hold": "Self weight",
        "point_load": "Point load",
        "max_payload": "Max payload",
    }
    return tuple(
        TestSpec(
            suite="structural",
            name=name,
            label=name.replace("_", " "),
            browser_label=_short.get(name, name.replace("_", " ")),
            kind="structural",
            fields=_structural_fields(name),
        )
        for name in STRUCTURAL_TEST_NAMES
    )


_E2E_BROWSER_LABELS: dict[str, str] = {
    "wrist_flexion_sweep": "Wrist flex",
    "forearm_rotation_sweep": "Forearm rot",
    "shoulder_rotation_sweep": "Shoulder rot",
    "combined_wrist_forearm_rotation": "Wrist+forearm",
}


def e2e_test_specs() -> tuple[TestSpec, ...]:
    return tuple(
        TestSpec(
            suite="e2e",
            name=name,
            label=name.replace("_", " "),
            browser_label=_E2E_BROWSER_LABELS.get(name, name.replace("_", " ")),
            kind="confirmed motion",
            fields=(),
        )
        for name in E2E_TEST_NAMES
    )


def _calibration_fields(test: str) -> tuple[FieldSpec, ...]:
    joint_filter: CalibrationJointFilter | None = None
    if test == "backdriveable":
        joint_filter = "backdriveable"
    elif test == "non_backdriveable":
        joint_filter = "non_backdriveable"

    return (
        FieldSpec(
            "joint",
            "Joint",
            "joint",
            required=True,
            joint_filter=joint_filter,
        ),
    )


def calibration_test_specs() -> tuple[TestSpec, ...]:
    return tuple(
        TestSpec(
            suite="calibration",
            name=name,
            label=name.replace("_", " "),
            kind="calibration",
            fields=_calibration_fields(name),
        )
        for name in CALIBRATION_TEST_NAMES
    )


def tui_calibration_tree_specs() -> tuple[TestSpec, ...]:
    """Calibration entries shown in the TUI."""
    return (
        TestSpec(
            suite="calibration",
            name="backdriveable",
            label="Calibrate Backdriveable Joints",
            browser_label="Backdriveable",
            kind="interactive",
            fields=(
                FieldSpec(
                    "joint",
                    "Joint",
                    "joint",
                    required=True,
                    joint_filter="backdriveable",
                ),
            ),
        ),
        TestSpec(
            suite="calibration",
            name="non_backdriveable",
            label="Calibrate Non-Backdriveable Joints",
            browser_label="Non-Backdriveable",
            kind="interactive",
            fields=(
                FieldSpec(
                    "joint",
                    "Joint",
                    "joint",
                    required=True,
                    joint_filter="non_backdriveable",
                ),
            ),
        ),
        TestSpec(
            suite="calibration",
            name="validate",
            label="Validate the Arm Calibration",
            browser_label="Validate",
            kind="calibration",
            fields=(_JOINT_FIELD,),
        ),
    )


def tui_test_tree_specs() -> tuple[tuple[str, tuple[TestSpec, ...]], ...]:
    """Grouped test catalogue for the unified Tests screen."""
    return (
        ("Motor", tui_motor_test_specs()),
        ("Structural", tui_structural_test_specs()),
        ("E2E", e2e_test_specs()),
    )


def all_test_specs() -> tuple[TestSpec, ...]:
    return motor_test_specs() + structural_test_specs() + e2e_test_specs()
