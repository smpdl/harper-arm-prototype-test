"""Path configuration for the test runner TUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harper_arm.joint import DEFAULT_CONFIG_PATH

DEFAULT_E2E_CONFIG_PATH = Path("config/e2e.yaml")
DEFAULT_RESULTS_ROOT = Path("results")
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class RunPaths:
    config_path: Path = DEFAULT_CONFIG_PATH
    e2e_config_path: Path = DEFAULT_E2E_CONFIG_PATH
    results_root: Path = DEFAULT_RESULTS_ROOT
