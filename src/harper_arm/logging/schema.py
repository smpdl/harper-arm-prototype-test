'''
A CSV schema is a list of columns that are used to validate the data.csv file.
The columns are defined in the `SCHEMAS` dictionary. 
This file defines the whole schema for the test suites.
'''

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .. import units

if TYPE_CHECKING:
    from ..sampling import JointSample


@dataclass(frozen=True) # Immutable
class CsvSchema:
    """Defines the columns for the data.csv file.
    
    Args:
        name: The name of the schema.
        columns: The columns of the schema.

    Returns:
        A CsvSchema object that can be used to validate the data.
    """

    name: str # The name of the schema.
    columns: tuple[str, ...] # The columns of the schema.

    
def get_schema(name: str) -> CsvSchema:
    """Get the CSV schema by name.

    Args:
        name: The name of the schema.

    Returns:
        A CsvSchema object that can be used to validate the data.

    Raises:
        ValueError: If the schema is not found.
    """
    try:
        return SCHEMAS[name]
    except KeyError as exc:
        known = ", ".join(sorted(SCHEMAS)) 
        raise ValueError(f"unknown schema {name!r}; known: {known}") from exc


def validate_row(row: Mapping[str, Any], schema: CsvSchema) -> dict[str, Any]:
    """Ensure a row of data contains every column required by ``schema``.

    Args:
        row: The row to validate.
        schema: The schema to validate the row against.

    Returns:
        A dictionary of the validated row.

    Raises:
        ValueError: If the row is missing any columns required by the schema.
    """
    missing = [column for column in schema.columns if column not in row]
    if missing:
        raise ValueError(f"row missing columns for schema {schema.name!r}: {missing}")
    return {column: row[column] for column in schema.columns}

def telemetry_row(
    sample: JointSample,
    *,
    model: str,
    elapsed_s: float | None = None,
) -> dict[str, Any]:
    """Build one telemetry-schema row from a :class:`~harper_arm.sampling.JointSample`.

    Args:
        sample: Joint sample to convert. A sample is one telemetry reading from a motor.
        model: The model of the motor.
        elapsed_s: The elapsed time since the start of the test.

    Returns:
        A dictionary of the telemetry row.
    """
    return {
        "timestamp_utc": sample.timestamp.isoformat(),
        "elapsed_s": "" if elapsed_s is None else elapsed_s,
        "joint": sample.joint,
        "position_ticks": sample.position,
        "position_deg": units.ticks_to_degrees(sample.position),
        "velocity": sample.velocity,
        "velocity_rpm": units.velocity_to_rpm(sample.velocity),
        "current": sample.current,
        "current_ma": units.current_to_ma(sample.current, model=model),
        "temperature_c": units.temperature_to_celsius(sample.temperature),
        "voltage_raw": sample.voltage,
        "voltage_v": units.voltage_to_volts(sample.voltage),
    }

def telemetry_rows_from_snapshot(
    samples: Mapping[str, JointSample],
    *,
    models: Mapping[str, str],
    elapsed_s: float | None = None,
) -> list[dict[str, Any]]:
    """
    Expand a joint snapshot (a dict of joint samples) into telemetry rows (one row per joint).
    
    Example: 

    ```python
    samples = {
        "r_sh_flex": JointSample(
            timestamp=datetime.now(UTC), joint="r_sh_flex",
            position=1000, velocity=100, current=100, temperature=25, voltage=5,
        ),
        "r_sh_abd": JointSample(
            timestamp=datetime.now(UTC), joint="r_sh_abd",
            position=1000, velocity=100, current=100, temperature=25, voltage=5,
        ),
    }
    models = {
        "r_sh_flex": "xm540-w270-t",
        "r_sh_abd": "xm540-w270-t",
    }

    telemetry_rows_from_snapshot(samples, models=models, elapsed_s=10.0)
    [
        {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "elapsed_s": 10.0,
            "joint": "r_sh_flex",
            "position_ticks": 1000,
            "position_deg": 100.0,
        },
        {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "elapsed_s": 10.0,
            "joint": "r_sh_abd",
            "position_ticks": 1000,
            "position_deg": 100.0,
        },
    ]
    ```
    Args:
        samples: The joint samples to build the rows from.
        models: The models of the motors.
        elapsed_s: The elapsed time since the start of the test.

    Returns:
        A list of the telemetry rows.
    
    Raises:
        ValueError: If no model is configured for a joint.
    """
    rows: list[dict[str, Any]] = []
    for joint, sample in samples.items():
        try:
            model = models[joint]
        except KeyError as exc:
            raise ValueError(f"no model configured for joint {joint!r}") from exc
        rows.append(telemetry_row(sample, model=model, elapsed_s=elapsed_s))
    return rows

# The columns that are common to all telemetry schemas.
_TELEMETRY_COLUMNS = (
    "timestamp_utc", # The timestamp of the sample.
    "elapsed_s", # The elapsed time since the start of the test.
    "joint", # The joint of the sample.
    "position_ticks", # The position of the sample in ticks.
    "position_deg", # The position of the sample in degrees.
    "velocity", # The velocity of the sample in ticks/s.
    "velocity_rpm", # The velocity of the sample in RPM.
    "current", # The current of the sample in mA.
    "current_ma", # The current of the sample in mA.
    "temperature_c", # The temperature of the sample in Celsius.
    "voltage_raw", # The voltage of the sample in raw units.
    "voltage_v", # The voltage of the sample in volts.
)

SCHEMAS: dict[str, CsvSchema] = {
    "telemetry": CsvSchema("telemetry", _TELEMETRY_COLUMNS),
    "ping": CsvSchema(
        "ping",
        ("timestamp_utc", "joint", "success", "message"),
    ),
    "present_voltage": CsvSchema(
        "present_voltage",
        ("timestamp_utc", "joint", "voltage_raw", "voltage_v"),
    ),
    "present_temperature": CsvSchema(
        "present_temperature",
        ("timestamp_utc", "joint", "temperature_c"),
    ),
    "power_on_response": CsvSchema(
        "power_on_response",
        (
            "timestamp_utc",
            "joint",
            "start_position_deg",
            "end_position_deg",
            "delta_deg",
            "duration_s",
            "success",
        ),
    ),
    "position_accuracy": CsvSchema(
        "position_accuracy",
        (
            "timestamp_utc",
            "joint",
            "trial",
            "target_deg",
            "measured_deg",
            "error_deg",
        ),
    ),
    "velocity_tracking": CsvSchema(
        "velocity_tracking",
        (
            "timestamp_utc",
            "joint",
            "step_index",
            "target_rpm",
            "measured_rpm",
            "error_rpm",
        ),
    ),
    "current_no_load": CsvSchema(
        "current_no_load",
        ("timestamp_utc", "joint", "current", "current_ma"),
    ),
    "thermal_rise": CsvSchema(
        "thermal_rise",
        (
            "timestamp_utc",
            "elapsed_s",
            "joint",
            "temperature_c",
            "current",
            "current_ma",
        ),
    ),
    "self_weight_hold": CsvSchema("self_weight_hold", _TELEMETRY_COLUMNS),
    "point_load": CsvSchema(
        "point_load",
        (
            "timestamp_utc",
            "joint",
            "link",
            "load_description",
            "operator_notes",
            "max_flex_deg",
        ),
    ),
    "max_payload": CsvSchema(
        "max_payload",
        (
            "timestamp_utc",
            "payload_kg",
            "joint",
            "position_deg",
            "current_ma",
            "temperature_c",
            "limiting",
        ),
    ),
    "e2e_motion": CsvSchema(
        "e2e_motion",
        (
            "timestamp_utc",
            "keyframe_index",
            "keyframe",
            "joint",
            "offset_deg",
            "target_ticks",
            "measured_ticks",
            "error_deg",
            "current_ma",
            "temperature_c",
            "reached",
            "stop_reason",
        ),
    ),
    "calibration_record": CsvSchema(
        "calibration_record",
        (
            "timestamp_utc",
            "joint",
            "action",
            "position_ticks",
            "delta_deg",
            "reached",
        ),
    ),
    "calibration_validation": CsvSchema(
        "calibration_validation",
        (
            "timestamp_utc",
            "joint",
            "fraction",
            "target_ticks",
            "measured_ticks",
            "error_deg",
            "reached",
        ),
    ),
}
