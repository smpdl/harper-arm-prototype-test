"""Unit conversion helpers for Dynamixel X-series register values."""

from __future__ import annotations

TICKS_PER_REV = 4096
DEGREES_PER_TICK = 360.0 / TICKS_PER_REV

# Present_Velocity / Profile_Velocity: 0.229 rev/min per unit (X-series, protocol 2.0).
RPM_PER_VELOCITY_UNIT = 0.229

# Profile_Acceleration in velocity-based profile mode: 214.577 rev/min² per unit.
RPM2_PER_ACCELERATION_UNIT = 214.577

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


def rpm2_to_acceleration(rpm2: float) -> int:
    """Convert rev/min² to the nearest Profile_Acceleration register unit."""
    return int(round(rpm2 / RPM2_PER_ACCELERATION_UNIT))


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

def thermal_sample_current_ma(
    current: int,
    *,
    model: str,
    current_limit: int,
) -> float:
    """Convert thermal-rise telemetry to milliamps (XL430 uses Present_Load in 0.1%)."""
    name = _normalize_model(model)
    if "xl430" in name:
        return abs(current) * 0.1 / 100.0 * current_limit
    return current_to_ma(current, model=model)


def joint_uses_extended_position(position_limits: tuple[int, int]) -> bool:
    """Return True when a joint spans outside single-turn encoder range."""
    low, high = position_limits
    return min(low, high) < 0 or max(low, high) > TICKS_PER_REV - 1


def decode_position_ticks(raw: int) -> int:
    """Convert a Dynamixel Present/Goal_Position read to signed encoder ticks.

    The Dynamixel SDK returns 4-byte registers as unsigned integers, but
    Present_Position is a signed 32-bit value. Extended-position joints can
    report negative ticks; without this step they appear as values near 2^32.
    """
    value = int(raw) & 0xFFFFFFFF
    if value >= 0x80000000:
        return value - 0x100000000
    return value


def position_error_ticks(
    measured_ticks: int,
    reference_ticks: int,
    *,
    extended_position: bool = False,
) -> int:
    """Signed tick error (measured minus reference).

    Uses linear signed error for extended-position joints. For single-turn joints,
    uses the shortest path on the 4096-tick ring when both values lie in the
    single-turn range; otherwise uses linear signed error.
    """
    measured = decode_position_ticks(measured_ticks)
    reference = decode_position_ticks(reference_ticks)
    delta = measured - reference
    if extended_position:
        return delta
    if 0 <= measured <= TICKS_PER_REV - 1 and 0 <= reference <= TICKS_PER_REV - 1:
        half = TICKS_PER_REV // 2
        if delta > half:
            delta -= TICKS_PER_REV
        elif delta < -half:
            delta += TICKS_PER_REV
    return delta


def position_error_deg(
    measured_ticks: int,
    reference_ticks: int,
    *,
    extended_position: bool = False,
) -> float:
    """Signed position error in degrees (measured minus reference)."""
    return ticks_to_degrees(
        position_error_ticks(
            measured_ticks,
            reference_ticks,
            extended_position=extended_position,
        )
    )
