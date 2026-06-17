"""Shared helpers for TUI screens."""

from __future__ import annotations

from typing import Protocol, cast

from tui.core.paths import RunPaths


class _AppWithPaths(Protocol):
    paths: RunPaths


def app_paths(screen: object) -> RunPaths:
    return cast(_AppWithPaths, screen.app).paths
