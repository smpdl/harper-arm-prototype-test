"""
Home-relative motion planning for multi-joint tests.

Each keyframe is one synchronized move command. All resolved targets are validated before any caller sends hardware commands.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from harper_arm import units
from harper_arm.config import (
    ArmConfig,
    JointConfig,
    clamp_to_position_limits,
    require_home_position,
    target_within_position_limits,
)

DEFAULT_HOLD_S = 3.0


@dataclass(frozen=True)
class MotionKeyframe:
    """One confirmed step in a motion pattern. 
    Only joints present in ``offsets_deg`` will participate in this step.
    Use additional keyframes for sequential motion."""

    name: str
    offsets_deg: Mapping[str, float]
    hold_s: float = DEFAULT_HOLD_S # seconds to hold after the move completes before the next step.


@dataclass(frozen=True)
class ResolvedJointTarget:
    """Resolved home-relative target for one commanded joint in one keyframe."""

    joint: str
    offset_deg: float
    target_ticks: int
    home_ticks: int


@dataclass(frozen=True)
class ResolvedKeyframe:
    """A keyframe after home-relative degree offsets have been converted to encoder targets.

    ``targets`` contains only joints listed in the source keyframe's
    ``offsets_deg``.  Other joints are not commanded for this step.
    """

    index: int
    name: str
    targets: Mapping[str, ResolvedJointTarget]
    hold_s: float

    @property
    def commanded_joints(self) -> tuple[str, ...]:
        """Joint names that move together during this keyframe."""
        return tuple(sorted(self.targets))


@dataclass(frozen=True)
class MotionPlan:
    """A named sequence of home-relative keyframes executed in order."""

    name: str
    keyframes: tuple[MotionKeyframe, ...]


def target_ticks_from_home(joint: JointConfig, offset_deg: float) -> int:
    """Convert a home-relative degree offset into an encoder target."""
    home = require_home_position(joint)
    return home + joint.direction * units.degrees_to_ticks(offset_deg)


def validate_target_in_limits(joint: JointConfig, target_ticks: int) -> None:
    """Reject targets outside configured hard software limits before motion."""
    min_tick, max_tick = joint.position_limits
    if not target_within_position_limits(joint.position_limits, target_ticks):
        raise ValueError(
            f"joint {joint.name!r} target {target_ticks} is outside position_limits "
            f"(min={min_tick}, max={max_tick})"
        )

def resolve_keyframe(
    arm: ArmConfig,
    keyframe: MotionKeyframe,
    *,
    index: int,
) -> ResolvedKeyframe:
    """Resolve one keyframe's commanded joints and validate their targets.

    Joints not listed in ``offsets_deg`` will be omitted from the result and will be
    expected to hold position when the plan is executed.
    """
    unknown = sorted(set(keyframe.offsets_deg) - set(arm.joints))
    if unknown:
        raise ValueError(f"keyframe {keyframe.name!r} references unknown joints: {unknown}")

    targets: dict[str, ResolvedJointTarget] = {}
    for joint_name, offset_deg in keyframe.offsets_deg.items():
        joint = arm.joints[joint_name]
        home = require_home_position(joint)
        target = target_ticks_from_home(joint, offset_deg)
        validate_target_in_limits(joint, target)
        targets[joint_name] = ResolvedJointTarget(
            joint=joint_name,
            offset_deg=float(offset_deg),
            target_ticks=target,
            home_ticks=home,
        )

    return ResolvedKeyframe(
        index=index,
        name=keyframe.name,
        targets=targets,
        hold_s=keyframe.hold_s,
    )


def resolve_plan(arm: ArmConfig, plan: MotionPlan) -> tuple[ResolvedKeyframe, ...]:
    """Resolve and validate every keyframe before the first motor command."""
    if not plan.keyframes:
        raise ValueError(f"motion plan {plan.name!r} must contain at least one keyframe")
    return tuple(
        resolve_keyframe(arm, keyframe, index=index)
        for index, keyframe in enumerate(plan.keyframes, start=1)
    )
