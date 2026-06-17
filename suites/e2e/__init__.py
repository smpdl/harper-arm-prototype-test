"""Operator-confirmed end-to-end arm motion tests."""

from __future__ import annotations

from pathlib import Path

from harper_arm.joint import DEFAULT_CONFIG_PATH

from .config import DEFAULT_E2E_CONFIG_PATH, load_e2e_config
from .operator import DEFAULT_RESULTS_ROOT, run_terminal_confirmed


def test_names(e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH) -> tuple[str, ...]:
    """Return configured e2e test names in deterministic order."""
    return tuple(sorted(load_e2e_config(e2e_config_path).tests))


def run(
    test: str,
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    e2e_config_path: Path | str = DEFAULT_E2E_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    **_: object,
) -> Path:
    """Run an e2e motion test with terminal keyframe confirmation."""
    return run_terminal_confirmed(
        test=test,
        config_path=config_path,
        e2e_config_path=e2e_config_path,
        results_root=results_root,
    )
