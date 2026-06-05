"""Unit conversion helpers for Dynamixel X-series register values."""

from __future__ import annotations

TICKS_PER_REV = 4096
DEGREES_PER_TICK = 360.0 / TICKS_PER_REV

# Present_Velocity: 0.229 rev/min per unit (X-series, protocol 2.0).
RPM_PER_VELOCITY_UNIT = 0.229

# Present_Input_Voltage: 0.1 V per unit.
VOLTS_PER_VOLTAGE_UNIT = 0.1

# Goal/Present current scaling (mA per register unit).
_MA_PER_UNIT_XM = 2.69
_MA_PER_UNIT_XL_XC = 1.0


def ticks_to_degrees(ticks: int | float) -> float:
    """Convert encoder ticks to degrees (4096 ticks/rev)."""
    return float(ticks) * DEGREES_PER_TICK


def degrees_to_ticks(degrees: int | float) -> int:
    """Convert degrees to the nearest encoder tick."""
    return int(round(float(degrees) / DEGREES_PER_TICK))


def velocity_to_rpm(velocity: int) -> float:
    """Convert Present_Velocity register units to rev/min."""
    return velocity * RPM_PER_VELOCITY_UNIT


def rpm_to_velocity(rpm: float) -> int:
    """Convert rev/min to the nearest Present_Velocity register unit."""
    return int(round(rpm / RPM_PER_VELOCITY_UNIT))


def voltage_to_volts(voltage: int) -> float:
    """Convert Present_Input_Voltage register units to volts."""
    return voltage * VOLTS_PER_VOLTAGE_UNIT


def temperature_to_celsius(temperature: int) -> float:
    """Present_Temperature is already degrees Celsius on X-series motors."""
    return float(temperature)


def _normalize_model(model: str) -> str:
    return model.strip().lower().replace("_", "-")


def current_ma_per_unit(model: str) -> float:
    """Return mA per Goal/Present Current register unit for a motor model name."""
    name = _normalize_model(model)
    if "xm540" in name or "xm430" in name:
        return _MA_PER_UNIT_XM
    if "xl430" in name or "xc330" in name or "xc430" in name:
        return _MA_PER_UNIT_XL_XC
    raise ValueError(f"unknown model for current scaling: {model!r}")
    
def current_to_ma(current: int, *, model: str) -> float:
    """Convert signed Present/Goal Current register units to milliamps."""
    return current * current_ma_per_unit(model)


def position_error_deg(measured_ticks: int, reference_ticks: int) -> float:
    """Signed position error in degrees (measured minus reference)."""
    return ticks_to_degrees(measured_ticks - reference_ticks)
