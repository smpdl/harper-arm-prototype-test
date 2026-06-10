"""Timed polling of joint telemetry."""

from __future__ import annotations

import signal
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dynio import DynamixelMotor

    from harper_arm.joint import Joint

RegisterReader = Callable[[], dict[str, "JointSample"]]
StopCheck = Callable[[dict[str, "JointSample"]], tuple[bool, str, str | None]]


@dataclass(frozen=True)
class JointSample:
    timestamp: datetime
    joint: str
    position: int
    velocity: int
    current: int
    temperature: int
    voltage: int

def _read_joint_sample_from_motor(motor: DynamixelMotor, *, joint: str) -> JointSample:
    return JointSample(
        timestamp=datetime.now(UTC),
        joint=joint,
        position=int(motor.read_control_table("Present_Position")),
        velocity=int(motor.read_control_table("Present_Velocity")),
        current=int(motor.read_control_table("Present_Current")),
        temperature=int(motor.read_control_table("Present_Temperature")),
        voltage=int(motor.read_control_table("Present_Input_Voltage")),
    )


def read_joint_sample(joint: Joint) -> JointSample:
    """Read present registers from a connected joint."""
    with joint.bus_lock:
        return _read_joint_sample_from_motor(joint.motor, joint=joint.joint_name)

def sample_joints(joints: Mapping[str, DynamixelMotor]) -> dict[str, JointSample]:
    """Sample the joints. Caller must hold the bus lock when sharing a serial port."""
    return {
        name: _read_joint_sample_from_motor(motor, joint=name)
        for name, motor in joints.items()
    }

def _sleep_until(next_tick: float) -> None:
    """Sleep until the next tick."""
    delay = next_tick - time.monotonic()
    if delay > 0:
        time.sleep(delay)

def sample_until(
    sample_fn: RegisterReader,
    *,
    should_stop: StopCheck,
    interval_s: float,
    max_duration_s: float | None = None,
    on_sample: Callable[[dict[str, JointSample]], Any] | None = None,
) -> tuple[list[dict[str, JointSample]], tuple[bool, str, str | None]]:
    """Poll until the should_stop function returns true or the max_duration_s elapses.
    Args:
        sample_fn: The function to sample the joints.
        should_stop: Callable that returns whether sampling should stop (e.g. safety).
        interval_s: Sampling interval in seconds.
        max_duration_s: Optional cap on total sampling duration in seconds.
        on_sample: The function to call on each sample. This is used to record the samples.

    Returns:
        A tuple of the samples and the stop result.
    """
    if interval_s <= 0:
        raise ValueError("interval_s must be positive.")

    deadline = None if max_duration_s is None else time.monotonic() + max_duration_s
    next_tick = time.monotonic()
    snapshots: list[dict[str, JointSample]] = []
    stop_result: tuple[bool, str, str | None] = (False, "", None)

    while deadline is None or time.monotonic() < deadline:
        snapshot = sample_fn()
        snapshots.append(snapshot)
        if on_sample is not None:
            on_sample(snapshot)

        stop_result = should_stop(snapshot)
        if stop_result[0]:
            break

        next_tick += interval_s
        _sleep_until(next_tick)

    return snapshots, stop_result


class _OperatorAbort:
    """Class to handle the abort event."""
    def __init__(self) -> None:
        """Initialize the operator abort guard."""
        self._event = threading.Event() # The event to signal the abort.
        self._previous_handlers: dict[int, Any] = {} # The previous handlers for the signals.

    @property
    def requested(self) -> bool:
        """Check if the abort event is set."""
        return self._event.is_set()

    def _handle(self, signum: int, _frame: object) -> None:
        """Handle the signal."""
        self._event.set() # Set the event to signal the abort.

        # Restore the previous handler for the signal if it exists.
        # SIG_DFL is the default handler for the signal.
        previous = self._previous_handlers.get(signum, signal.SIG_DFL)
        if callable(previous):
            previous(signum, _frame)

    def install(self) -> None:
        """Install the operator abort guard."""
        # SIGINT and SIGTERM abort the test.
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, self._handle)

    def restore(self) -> None:
        """Restore the operator abort guard."""
        for signum, handler in self._previous_handlers.items():
            signal.signal(signum, handler)
        self._previous_handlers.clear()


@contextmanager
def operator_abort_guard() -> Iterator[threading.Event]:
    """Context manager that sets an event when the operator sends SIGINT/SIGTERM."""
    guard = _OperatorAbort()
    guard.install()
    try:
        yield guard._event # Yield the event to signal the abort.   
    finally:
        guard.restore()
