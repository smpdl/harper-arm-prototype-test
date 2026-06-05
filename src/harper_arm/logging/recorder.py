'''
This file contains the TestRun class, and contains the functions to write the data to the CSV file, 
the metadata to the JSON file, and the summary to the JSON file.
'''

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..sampling import JointSample
from .schema import (
    CsvSchema,
    get_schema,
    telemetry_rows_from_snapshot,
    validate_row,
)


@dataclass
class TestRun:
    """
    Context manager that writes ``metadata.json``, ``data.csv``, and ``summary.json``.
    This is used to record the data from the tests.

    ``metadata.json`` records suite, test, schema, started_at, run_dir, and metadata.
    ```data.csv` is a CSV file that contains the data from the tests.
    ```summary.json` is a JSON file that contains the summary of the tests.

    Args:
        suite: The suite of the test.
        test: The name of the test.
        schema: The schema of the test.
        results_root: The root directory to write the results to.
        joint: The joint of the test.
        metadata: The metadata of the test.
    """

    suite: str
    test: str
    schema: str | CsvSchema
    results_root: Path = Path("results") # The root directory to write the results to.
    joint: str | None = None # The joint of the test.
    metadata: dict[str, Any] = field(default_factory=dict)

    run_dir: Path = field(init=False)
    _csv_schema: CsvSchema = field(init=False, repr=False)
    _csv_file: Any = field(init=False, repr=False, default=None)
    _csv_writer: csv.DictWriter | None = field(init=False, repr=False, default=None)
    _row_count: int = field(init=False, repr=False, default=0)
    _started_at: datetime = field(init=False, repr=False)
    _summary: dict[str, Any] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """
        Post-initialization setup that gets the CSV schema and initializes the run directory.
        """
        if isinstance(self.schema, str):
            self._csv_schema = get_schema(self.schema)
        else:
            self._csv_schema = self.schema

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        parts = [timestamp, self.suite, self.test] # The parts of the run directory name.
        if self.joint:
            parts.append(self.joint)
        self.run_dir = self.results_root / "_".join(parts)
        self._started_at = datetime.now(UTC)
        self._summary = {"status": "running"}

    def __enter__(self) -> TestRun:
        """
        Enter the context manager. This is called when the context manager is entered.
        The run directory is created and the metadata is written, and the CSV file is opened.
        """
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self._write_metadata()
        self._open_csv()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._csv_file is not None:
            self._csv_file.close()
            self._csv_file = None
            self._csv_writer = None

        if exc_type is not None and self._summary.get("status") == "running":
            self._summary["status"] = "failed"
            self._summary["error"] = str(exc)

        self._summary.setdefault("finished_at", datetime.now(UTC).isoformat())
        self._summary.setdefault("row_count", self._row_count)
        self._write_summary()

    @property
    def csv_schema(self) -> CsvSchema:
        """The CSV schema of the test."""
        return self._csv_schema

    @property
    def row_count(self) -> int:
        """The number of rows written to the CSV file."""
        return self._row_count

    def set_summary(self, **fields: Any) -> None:
        """Merge fields into ``summary.json`` (e.g. stop reason, peaks)."""
        self._summary.update(fields)

    def write_row(self, row: Mapping[str, Any]) -> None:
        """Write a row to the CSV file."""
        if self._csv_writer is None:
            raise RuntimeError("TestRun is not active; use as a context manager.")
        validated = validate_row(row, self._csv_schema)
        self._csv_writer.writerow(validated)
        self._row_count += 1

    def write_rows(self, rows: Iterable[Mapping[str, Any]]) -> None:
        """Write multiple rows to the CSV file."""
        for row in rows:
            self.write_row(row)

    def record_snapshot(
        self,
        samples: Mapping[str, JointSample],
        *,
        models: Mapping[str, str],
        elapsed_s: float | None = None,
    ) -> None:
        """Write telemetry rows when the active schema supports them.
        
        Args:
            samples: The joint samples to write.
            models: The models of the motors.
            elapsed_s: The elapsed time since the start of the test.
        """
        if self._csv_schema.name not in {"telemetry", "self_weight_hold"}:
            raise ValueError(
                f"record_snapshot requires a telemetry schema, got {self._csv_schema.name!r}"
            )
        self.write_rows(
            telemetry_rows_from_snapshot(samples, models=models, elapsed_s=elapsed_s)
        )

    def _write_metadata(self) -> None:
        payload = {
            "suite": self.suite,
            "test": self.test,
            "schema": self._csv_schema.name,
            "started_at": self._started_at.isoformat(),
            "run_dir": str(self.run_dir),
            **self.metadata,
        }
        if self.joint is not None:
            payload["joint"] = self.joint
        self._write_json(self.run_dir / "metadata.json", payload)

    def _write_summary(self) -> None:
        if self._summary.get("status") == "running":
            self._summary["status"] = "completed"
        self._write_json(self.run_dir / "summary.json", self._summary)

    def _open_csv(self) -> None:
        path = self.run_dir / "data.csv"
        self._csv_file = path.open("w", newline="", encoding="utf-8")
        self._csv_writer = csv.DictWriter(
            self._csv_file,
            fieldnames=list(self._csv_schema.columns),
            extrasaction="ignore",
        )
        self._csv_writer.writeheader()

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
