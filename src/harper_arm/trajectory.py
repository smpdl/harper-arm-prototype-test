"""
Defines the S-curve trajectory sampling for multi-joint motions.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import scurvebeta as scb

from harper_arm import units


@dataclass(frozen=True)
class TrajectoryPoint:
    """
    One sampled multi-joint command in a synchronized S-curve segment.

    For example:

    elapsed_s: 0.0
    targets: {
        "joint1": 1000,
        "joint2": 2000,
    }

    This would mean that joint1 should be at 1000 ticks and joint2 should be at 2000 ticks 
    after 0 seconds.
    """

    elapsed_s: float # time elapsed since the start of the trajectory
    targets: Mapping[str, int] # the target positions in ticks for each joint


@dataclass(frozen=True)
class Trajectory:
    """
    Sampled S-curve trajectory for one keyframe transition.

    For example:

    duration_s: 1.0
    points: (
        TrajectoryPoint(elapsed_s=0.0, targets={"joint1": 1000, "joint2": 2000}),
        TrajectoryPoint(elapsed_s=1.0, targets={"joint1": 2000, "joint2": 4000}),
    )

    This would mean that joint1 should be at 1000 ticks and joint2 should be at 2000 ticks 
    after 0 seconds, and joint1 should be at 2000 ticks and joint2 should be at 4000 ticks 
    after 1 second.
    """

    duration_s: float # the total duration of the trajectory
    points: tuple[TrajectoryPoint, ...] # the points in the trajectory


def synchronized_scurve_trajectory(
    starts: Mapping[str, int],
    targets: Mapping[str, int],
    *,
    max_velocity_deg_s: float,
    max_acceleration_deg_s2: float,
    sample_period_s: float,
) -> Trajectory:
    """
    This function will build a S-curve trajectory for multiple joints.

    The idea is that we will synchronize the joints by calculating each joint's
    motion time and then using the maximum time for all joints as the duration of the trajectory.
    That keeps the relative joint motion coordinated while shorter joints move with lower peak
    velocity/acceleration instead of finishing early. So, we will also do the same here .

    For example, if we have 3 joints with the following start and target positions:
    starts: {
        "joint1": 1000,
        "joint2": 2000,
        "joint3": 3000,
    }
    targets: {
        "joint1": 2000,
        "joint2": 4000,
        "joint3": 6000,
    }

    Now, we will use the library to calculate the motion time for each joint to reach the target position:
    joint1: t_motion_time_joint1 seconds
    joint2: t_motion_time_joint2 seconds
    joint3: t_motion_time_joint3 seconds

    Then, the duration of the trajectory will be duration_s = max(t_motion_time_joint1, t_motion_time_joint2, t_motion_time_joint3) seconds.

    Then, we will sample the trajectory at the given sample period, and the points will be returned as a tuple of TrajectoryPoint objects.
    

    duration_s: duration_s
    points: (
        TrajectoryPoint(elapsed_s=0.0, targets=starts),
        TrajectoryPoint(elapsed_s=0.1, targets={"joint1": intermediate_position_joint1, "joint2": intermediate_position_joint2, "joint3": intermediate_position_joint3}),
        ...
        TrajectoryPoint(elapsed_s=duration_s, targets=targets),
    )
    """
    if max_velocity_deg_s <= 0:
        raise ValueError("max_velocity_deg_s must be positive.")
    if max_acceleration_deg_s2 <= 0:
        raise ValueError("max_acceleration_deg_s2 must be positive.")
    if sample_period_s <= 0:
        raise ValueError("sample_period_s must be positive.")

    if set(starts) != set(targets):
        missing = sorted(set(starts) ^ set(targets))
        raise ValueError(f"starts and targets must contain the same joints: {missing}")

    durations = [
        _axis_motion_time(
            start_ticks=starts[joint],
            target_ticks=targets[joint],
            max_velocity_deg_s=max_velocity_deg_s,
            max_acceleration_deg_s2=max_acceleration_deg_s2,
        )
        for joint in starts
    ]
    duration_s = max(durations, default=0.0)
    if duration_s <= 0:
        return Trajectory(
            duration_s=0.0,
            points=(TrajectoryPoint(elapsed_s=0.0, targets=dict(targets)),),
        )

    step_count = max(1, math.ceil(duration_s / sample_period_s))
    points: list[TrajectoryPoint] = []
    for step in range(1, step_count + 1):
        elapsed_s = min(duration_s, step * sample_period_s)
        point_targets = {
            joint: _sample_axis(
                elapsed_s=elapsed_s,
                duration_s=duration_s,
                start_ticks=starts[joint],
                target_ticks=targets[joint],
            )
            for joint in starts
        }
        points.append(TrajectoryPoint(elapsed_s=elapsed_s, targets=point_targets))

    # Rounding intermediate floating-point samples can leave the last command a
    # tick short.  Force the final point to the exact validated target.
    points[-1] = TrajectoryPoint(elapsed_s=duration_s, targets=dict(targets))
    return Trajectory(duration_s=duration_s, points=tuple(points))


def _axis_motion_time(
    *,
    start_ticks: int,
    target_ticks: int,
    max_velocity_deg_s: float,
    max_acceleration_deg_s2: float,
) -> float:
    """
    This function will calculate the motion time for a joint to reach the target position.
    """
    range_deg = abs(units.ticks_to_degrees(target_ticks - start_ticks))
    if range_deg == 0:
        return 0.0
    return float(scb.motionTime(max_velocity_deg_s, max_acceleration_deg_s2, range_deg))


def _sample_axis(
    *,
    elapsed_s: float,
    duration_s: float,
    start_ticks: int,
    target_ticks: int,
) -> int:
    """
    This function will sample the trajectory at the given elapsed time.
    """
    if start_ticks == target_ticks:
        return target_ticks
    return int(round(float(scb.sCurve(elapsed_s, duration_s, start_ticks, target_ticks))))
