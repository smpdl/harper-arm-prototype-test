"""Live motor register monitor for the TUI."""

from __future__ import annotations

from textual.widgets import Static

from harper_arm.status import (
    MotorStatus,
    format_hardware_error,
    format_on_off,
    format_operating_mode,
    format_yes_no,
)

_NA = "NA"


class MotorStatusPanel(Static):
    """Displays important Dynamixel registers for one joint."""

    def compose(self):
        yield Static("Motor Status", id="monitor-title")
        yield Static(_idle_body(), id="monitor-body", classes="monitor-idle")

    def show_idle(self) -> None:
        body = self.query_one("#monitor-body", Static)
        body.add_class("monitor-idle")
        body.update(_idle_body())

    def update_status(self, status: MotorStatus) -> None:
        lines = [
            _row("Joint", status.joint),
            _row("Model", status.model),
            "",
            _row("Position", f"{status.position} ticks"),
            _row("", f"{status.position_deg:.1f}°"),
            _row("Velocity", f"{status.velocity} ({status.velocity_rpm:.1f} rpm)"),
            _row("Current", f"{status.current:+d} ({status.current_ma:.1f} mA)"),
            _row("Temperature", f"{status.temperature_c:.0f} °C"),
            _row("Voltage", f"{status.voltage_v:.1f} V"),
            "",
            _row("Goal pos", _fmt_int(status.goal_position)),
            _row("Goal vel", _fmt_int(status.goal_velocity)),
            _row("Goal cur", _fmt_int(status.goal_current)),
            _row("Torque", format_on_off(status.torque_enabled)),
            _row("Moving", format_yes_no(status.moving)),
            _row("HW error", format_hardware_error(status.hardware_error)),
            _row("Op mode", format_operating_mode(status.operating_mode)),
            "",
            _row("Updated", status.timestamp.strftime("%H:%M:%S")),
        ]
        body = self.query_one("#monitor-body", Static)
        body.remove_class("monitor-idle")
        body.update("\n".join(lines))


def _idle_body() -> str:
    lines = [
        _row("Joint", _NA),
        _row("Model", _NA),
        "",
        _row("Position", _NA),
        _row("", _NA),
        _row("Velocity", _NA),
        _row("Current", _NA),
        _row("Temperature", _NA),
        _row("Voltage", _NA),
        "",
        _row("Goal pos", _NA),
        _row("Goal vel", _NA),
        _row("Goal cur", _NA),
        _row("Torque", _NA),
        _row("Moving", _NA),
        _row("HW error", _NA),
        _row("Op mode", _NA),
        "",
        _row("Updated", _NA),
    ]
    return "\n".join(lines)


def _row(label: str, value: str) -> str:
    if not label:
        return f"  {value}"
    return f"{label:<11} {value}"


def _fmt_int(value: int | None) -> str:
    return _NA if value is None else str(value)
