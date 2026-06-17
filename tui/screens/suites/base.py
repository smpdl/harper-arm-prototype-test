"""Shared test/calibration runner screen."""

from __future__ import annotations

import traceback
from abc import abstractmethod
from collections.abc import Sequence
from typing import Any, ClassVar

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    RichLog,
    Select,
    Static,
    Switch,
    Tree,
)
from textual.widgets.tree import TreeNode

from harper_arm.config import load_arm_config
from harper_arm.status import MotorStatus
from suites.e2e.config import load_e2e_config
from suites.structural.helpers import (
    STRUCTURAL_E2E_POSES,
    pose_approach_preview_lines,
    structural_pose_names,
)
from tui.catalog import TestSpec
from tui.core.paths import RunPaths
from tui.core.runner import run_test
from tui.screens.pose_confirm import PoseConfirmScreen
from tui.screens.settings import SettingsScreen
from tui.screens.suites.fields import SuiteFieldMixin
from tui.widgets.motor_status import MotorStatusPanel


class SuiteRunnerScreen(Screen[None], SuiteFieldMixin):
    BINDINGS: ClassVar[Sequence[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "run_test", "Run"),
        Binding("s", "open_settings", "Settings"),
        Binding("escape", "go_home", "Home"),
    ]

    def __init__(self, paths: RunPaths, *, browser_title: str) -> None:
        super().__init__()
        self.paths = paths
        self.browser_title = browser_title
        self._selected: TestSpec | None = None
        self._joints: list[str] = []
        self._poses: list[str] = []
        self._pose_options: list[tuple[str, str]] = []
        self._field_widgets: dict[str, Input | Select[str] | Switch] = {}
        self._pending_structural: tuple[TestSpec, dict[str, Any]] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="browser"):
                yield Static(self.browser_title, id="browser-title")
                yield Tree("Suites", id="test-tree", classes="browser-tree")
            with Vertical(id="config-panel"):
                yield Static("Select a test", id="config-title")
                with VerticalScroll(id="config-scroll"):
                    with Vertical(id="config-fields"):
                        pass
                with Horizontal(id="config-actions"):
                    yield Button(
                        "Run",
                        classes="btn-run",
                        id="run-button",
                        disabled=True,
                    )
                    yield Button(
                        "Bring Home",
                        classes="btn-black",
                        id="bring-home-button",
                        disabled=True,
                    )
            yield MotorStatusPanel(id="status-monitor")
        with Vertical(id="output-panel"):
            yield Static("Output", id="output-title")
            yield RichLog(id="output-log", highlight=True, markup=True)
        yield Static("Ready.", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self._reload_catalog()
        tree = self.query_one("#test-tree", Tree)
        tree.show_root = False
        tree.root.expand()
        self.populate_tree(tree)

    @abstractmethod
    def populate_tree(self, tree: Tree) -> None:
        """Add suite leaves to the browser tree."""

    def _reload_catalog(self) -> None:
        try:
            config = load_arm_config(self.paths.config_path)
            self._joints = sorted(config.joints)
        except Exception as exc:
            self._joints = []
            self._write_log(
                f"[yellow]Could not load joints from {self.paths.config_path}: {exc}[/]"
            )
        # Structural poses include calibrated home plus selected e2e keyframes.
        try:
            self._poses = list(
                structural_pose_names(e2e_config_path=self.paths.e2e_config_path)
            )
            e2e = load_e2e_config(self.paths.e2e_config_path)
            self._pose_options = [("Home", "home")]
            for pose_name in STRUCTURAL_E2E_POSES:
                if pose_name in e2e.tests:
                    self._pose_options.append((e2e.tests[pose_name].label, pose_name))
        except Exception as exc:
            self._poses = ["home"]
            self._pose_options = [("Home", "home")]
            self._write_log(
                f"[yellow]Could not load structural poses from "
                f"{self.paths.e2e_config_path}: {exc}[/]"
            )

    def _set_status(self, message: str) -> None:
        self.query_one("#status-bar", Static).update(message)

    def _write_log(self, message: str) -> None:
        self.query_one("#output-log", RichLog).write(message)

    def _call_from_thread(self, callback, /, *args, **kwargs) -> None:
        self.app.call_from_thread(callback, *args, **kwargs)

    def _status_monitor(self) -> MotorStatusPanel:
        return self.query_one("#status-monitor", MotorStatusPanel)

    def _update_motor_status(self, status: MotorStatus) -> None:
        self._status_monitor().update_status(status)

    def _refresh_status_monitor(self, _spec: TestSpec | None) -> None:
        self._status_monitor().show_idle()

    async def _select_test(self, spec: TestSpec | None) -> None:
        self._selected = spec
        self.query_one("#config-title", Static).update(
            spec.label if spec else "Select a test"
        )

        fields = self.query_one("#config-fields", Vertical)
        await fields.remove_children()
        self._field_widgets.clear()

        run_button = self.query_one("#run-button", Button)
        if spec is None:
            run_button.disabled = True
            self._refresh_status_monitor(None)
            return

        run_button.disabled = False
        for field in spec.fields:
            await self._mount_field_row(fields, field)
        self._refresh_status_monitor(spec)

    @on(Tree.NodeSelected, "#test-tree")
    async def on_tree_selected(self, event: Tree.NodeSelected) -> None:
        node: TreeNode = event.node
        spec = node.data if isinstance(node.data, TestSpec) else None
        await self._select_test(spec)

    @on(Button.Pressed, "#run-button")
    def on_run_pressed(self) -> None:
        self.action_run_test()

    def action_go_home(self) -> None:
        self.app.pop_screen()

    def action_open_settings(self) -> None:
        async def handle_result(saved: bool | None) -> None:
            if not saved:
                return
            self._reload_catalog()
            if self._selected is not None:
                await self._select_test(self._selected)
            self._set_status("Updated paths.")
            self._write_log(
                "[cyan]Paths updated:[/] "
                f"config={self.paths.config_path}, "
                f"e2e={self.paths.e2e_config_path}, "
                f"results={self.paths.results_root}"
            )

        self.app.push_screen(SettingsScreen(self.paths), handle_result)

    def action_run_test(self) -> None:
        if self._selected is None:
            self._set_status("Select a test first.")
            return
        if self._test_busy:
            self._set_status("A test is already running.")
            return
        try:
            kwargs = self._collect_kwargs(self._selected)
        except ValueError as exc:
            self._set_status(str(exc))
            self._write_log(f"[red]Configuration error:[/] {exc}")
            return

        if self._selected.suite == "structural":
            pose = str(kwargs.get("pose", "home"))
            if pose != "home":
                try:
                    preview = pose_approach_preview_lines(
                        pose,
                        config_path=self.paths.config_path,
                        e2e_config_path=self.paths.e2e_config_path,
                    )
                except Exception as exc:
                    self._set_status(str(exc))
                    self._write_log(f"[red]Configuration error:[/] {exc}")
                    return
                self._pending_structural = (self._selected, kwargs)
                self.app.push_screen(
                    PoseConfirmScreen(pose=pose, preview_lines=preview),
                    self._on_pose_confirm,
                )
                return

        self._status_monitor().show_idle()
        self._execute_test(self._selected, kwargs)

    def _on_pose_confirm(self, confirmed: bool | None) -> None:
        pending = self._pending_structural
        self._pending_structural = None
        if not confirmed or pending is None:
            self._set_status("Approach cancelled.")
            return
        spec, kwargs = pending
        kwargs = {**kwargs, "pose_confirmed": True}
        self._status_monitor().show_idle()
        self._execute_test(spec, kwargs)

    @property
    def _test_busy(self) -> bool:
        return bool(self.workers)

    @work(exclusive=True, thread=True)
    def _execute_test(self, spec: TestSpec, kwargs: dict[str, Any]) -> None:
        self._call_from_thread(self._set_status, f"Running {spec.suite}/{spec.name}...")
        self._call_from_thread(self._write_log, f"[bold cyan]▶ {spec.suite}/{spec.name}[/]")

        on_motor_status = None
        if spec.suite == "motor":
            on_motor_status = lambda status: self._call_from_thread(  # noqa: E731
                self._update_motor_status, status
            )

        try:
            run_dir = run_test(
                spec,
                self.paths,
                log_line=lambda line: self._call_from_thread(self._write_log, line),
                on_motor_status=on_motor_status,
                **kwargs,
            )
            self._call_from_thread(
                self._write_log,
                f"[green]✓ Results written to[/] [bold]{run_dir}[/]",
            )
            self._call_from_thread(self._set_status, f"Finished: {run_dir}")
            self._call_from_thread(self._refresh_status_monitor, spec)
        except Exception:
            self._call_from_thread(self._write_log, "[red]Test failed:[/]")
            self._call_from_thread(self._write_log, traceback.format_exc())
            self._call_from_thread(self._set_status, f"Failed: {spec.suite}/{spec.name}")
            self._call_from_thread(self._refresh_status_monitor, spec)
