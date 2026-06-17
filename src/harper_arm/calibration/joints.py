"""Which joints use backdriveable vs motor-assisted calibration."""

from __future__ import annotations


def is_backdriveable_joint(joint_name: str) -> bool:
    """Return True for shoulder and wrist joints (torque-off manual placement)."""
    return "_sh_" in joint_name or "_wrist_" in joint_name


def require_joint_mode(joint_name: str, *, backdriveable: bool) -> None:
    """Reject a joint that does not match the selected calibration mode."""
    if is_backdriveable_joint(joint_name) == backdriveable:
        return
    expected = "backdriveable" if backdriveable else "non_backdriveable"
    actual = "backdriveable" if is_backdriveable_joint(joint_name) else "non_backdriveable"
    raise ValueError(
        f"joint {joint_name!r} requires {actual} calibration, not {expected}"
    )
