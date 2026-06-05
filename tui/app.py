"""Main Textual application for hardware test suites."""

from __future__ import annotations

import traceback
from collections.abc import Sequence
from typing import Any, ClassVar

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    Switch,
    Tree,
)
from textual.widgets.tree import TreeNode

from harper_arm.config import load_arm_config, load_motions_config
from harper_arm.status import MotorStatus
from tui.monitor import MotorStatusPanel
from tui.runner import RunPaths, run_test
from tui.settings import SettingsScreen
from tui.suite_catalog import FieldSpec, TestSpec, all_test_specs


class TestRunnerApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #body {
        height: 1fr;
        layout: horizontal;
    }

    #browser {
        width: 30;
        min-width: 24;
        border: solid $primary-darken-2;
        padding: 0 1;
    }

    #browser-title {
        margin: 1 0;
        text-style: bold;
    }

    #config-panel {
        width: 1fr;
        border: solid $primary-darken-2;
        padding: 1 2;
    }

    MotorStatusPanel {
        width: 32;
        min-width: 28;
        border: solid $primary-darken-2;
        padding: 1;
    }

    #monitor-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #monitor-body {
        height: 1fr;
    }

    .monitor-idle {
        color: $text-muted;
    }

    #config-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #config-meta {
        color: $text-muted;
        margin-bottom: 1;
    }

    #config-fields {
        height: 1fr;
        min-height: 8;
    }

    .field-row {
        height: auto;
        margin-bottom: 1;
    }

    .field-label {
        width: 18;
        content-align: right middle;
        margin-right: 1;
    }

    .field-control {
        width: 1fr;
    }

    #config-actions {
        height: auto;
        margin-top: 1;
        align: left middle;
    }

    #output-panel {
        height: 14;
        min-height: 10;
        border: solid $primary-darken-2;
        padding: 0 1;
    }

    #output-title {
        margin: 1 0 0 0;
        text-style: bold;
    }

    #output-log {
        height: 1fr;
        border: none;
        padding: 0;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $boost;
        color: $text;
        padding: 0 1;
    }
    """

    BINDINGS: ClassVar[Sequence[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "run_test", "Run"),
        Binding("s", "open_settings", "Settings"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.paths = RunPaths()
        self._selected: TestSpec | None = None
        self._joints: list[str] = []
        self._poses: list[str] = []
        self._field_widgets: dict[str, Input | Select[str] | Switch] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="browser"):
                yield Static("Test Suites", id="browser-title")
                yield Tree("Suites", id="test-tree")
            with Vertical(id="config-panel"):
                yield Static("Select a test", id="config-title")
                yield Static("", id="config-meta")
                with VerticalScroll(id="config-fields"):
                    yield Static("Choose a test from the tree.", id="empty-hint")
                with Horizontal(id="config-actions"):
                    yield Button("Run Test", variant="primary", id="run-button", disabled=True)
                    yield Button("Settings", id="settings-button")
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
        specs = all_test_specs()
        motor_node = tree.root.add("Motor", expand=True)
        for spec in specs:
            if spec.suite == "motor":
                motor_node.add_leaf(spec.name, data=spec)
        structural_node = tree.root.add("Structural", expand=True)
        for spec in specs:
            if spec.suite == "structural":
                structural_node.add_leaf(spec.name, data=spec)

    def _reload_catalog(self) -> None:
        try:
            config = load_arm_config(self.paths.config_path)
            self._joints = sorted(config.joints)
        except Exception as exc:
            self._joints = []
            self._write_log(
                f"[yellow]Could not load joints from {self.paths.config_path}: {exc}[/]"
            )
        try:
            motions = load_motions_config(self.paths.motions_path)
            self._poses = sorted(motions.poses)
        except Exception as exc:
            self._poses = []
            self._write_log(
                f"[yellow]Could not load poses from {self.paths.motions_path}: {exc}[/]"
            )

    def _set_status(self, message: str) -> None:
        self.query_one("#status-bar", Static).update(message)

    def _write_log(self, message: str) -> None:
        self.query_one("#output-log", RichLog).write(message)

    def _status_monitor(self) -> MotorStatusPanel:
        return self.query_one("#status-monitor", MotorStatusPanel)

    def _update_motor_status(self, status: MotorStatus) -> None:
        self._status_monitor().update_status(status)

    def _refresh_status_monitor(self, _spec: TestSpec | None) -> None:
        self._status_monitor().show_idle()

    async def _select_test(self, spec: TestSpec | None) -> None:
        self._selected = spec
        self.query_one("#config-title", Static).update(
            spec.label.title() if spec else "Select a test"
        )
        meta = ""
        if spec:
            meta = f"{spec.suite} · {spec.kind}"
        self.query_one("#config-meta", Static).update(meta)

        fields = self.query_one("#config-fields", VerticalScroll)
        await fields.remove_children()
        self._field_widgets.clear()

        run_button = self.query_one("#run-button", Button)
        if spec is None:
            await fields.mount(Static("Choose a test from the tree.", id="empty-hint"))
            run_button.disabled = True
            self._refresh_status_monitor(None)
            return

        run_button.disabled = False
        for field in spec.fields:
            await self._mount_field_row(fields, field)
        self._refresh_status_monitor(spec)

    async def _mount_field_row(self, fields: VerticalScroll, field: FieldSpec) -> None:
        widget = self._build_field_widget(field)
        widget.add_class("field-control")
        self._field_widgets[field.name] = widget
        row = Horizontal(classes="field-row")
        await fields.mount(row)
        await row.mount(Label(field.label, classes="field-label"), widget)

    def _build_field_widget(self, field: FieldSpec) -> Input | Select[str] | Switch:
        if field.field_type == "bool":
            widget: Input | Select[str] | Switch = Switch(value=bool(field.default))
        elif field.field_type == "joint":
            options = [(name, name) for name in self._joints] or [("(none)", "")]
            widget = Select(options, prompt="Select joint", id=f"field-{field.name}")
            if self._joints:
                widget.value = self._joints[0]
        elif field.field_type == "pose":
            options = [(name, name) for name in self._poses] or [("(none)", "")]
            widget = Select(options, prompt="Select pose", id=f"field-{field.name}")
            if field.default and str(field.default) in self._poses:
                widget.value = str(field.default)
            elif self._poses:
                widget.value = self._poses[0]
        elif field.field_type in {"int", "float", "text"}:
            widget = Input(
                placeholder=field.placeholder,
                id=f"field-{field.name}",
                type="text",
            )
            if field.default is not None:
                widget.value = str(field.default)
        else:
            widget = Input(placeholder=field.placeholder, id=f"field-{field.name}")

        return widget

    def _collect_kwargs(self, spec: TestSpec) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        for field in spec.fields:
            widget = self._field_widgets[field.name]
            if field.field_type == "bool":
                assert isinstance(widget, Switch)
                kwargs[field.name] = widget.value
                continue

            if isinstance(widget, Select):
                value = widget.value
                if field.required and (value is Select.BLANK or not value):
                    raise ValueError(f"{field.label} is required.")
                if value is not Select.BLANK and value:
                    kwargs[field.name] = value
                continue

            assert isinstance(widget, Input)
            raw = widget.value.strip()
            if not raw:
                if field.required:
                    raise ValueError(f"{field.label} is required.")
                continue
            if field.field_type == "int":
                kwargs[field.name] = int(raw)
            elif field.field_type == "float":
                kwargs[field.name] = float(raw)
            else:
                kwargs[field.name] = raw
        return kwargs

    @on(Tree.NodeSelected, "#test-tree")
    async def on_tree_selected(self, event: Tree.NodeSelected) -> None:
        node: TreeNode = event.node
        spec = node.data if isinstance(node.data, TestSpec) else None
        await self._select_test(spec)

    @on(Button.Pressed, "#run-button")
    def on_run_pressed(self) -> None:
        self.action_run_test()

    @on(Button.Pressed, "#settings-button")
    def on_settings_pressed(self) -> None:
        self.action_open_settings()

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
                f"motions={self.paths.motions_path}, "
                f"results={self.paths.results_root}"
            )

        self.push_screen(SettingsScreen(self.paths), handle_result)

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
        self._status_monitor().show_idle()
        self._execute_test(self._selected, kwargs)

    @property
    def _test_busy(self) -> bool:
        return bool(self.workers)

    @work(exclusive=True, thread=True)
    def _execute_test(self, spec: TestSpec, kwargs: dict[str, Any]) -> None:
        self.call_from_thread(self._set_status, f"Running {spec.suite}/{spec.name}...")
        self.call_from_thread(self._write_log, f"[bold cyan]▶ {spec.suite}/{spec.name}[/]")

        on_motor_status = None
        if spec.suite == "motor":
            on_motor_status = lambda status: self.call_from_thread(  # noqa: E731
                self._update_motor_status, status
            )

        try:
            run_dir = run_test(
                spec,
                self.paths,
                log_line=lambda line: self.call_from_thread(self._write_log, line),
                on_motor_status=on_motor_status,
                **kwargs,
            )
            self.call_from_thread(
                self._write_log,
                f"[green]✓ Results written to[/] [bold]{run_dir}[/]",
            )
            self.call_from_thread(self._set_status, f"Finished: {run_dir}")
            self.call_from_thread(self._refresh_status_monitor, spec)
        except Exception:
            self.call_from_thread(self._write_log, "[red]Test failed:[/]")
            self.call_from_thread(self._write_log, traceback.format_exc())
            self.call_from_thread(self._set_status, f"Failed: {spec.suite}/{spec.name}")
            self.call_from_thread(self._refresh_status_monitor, spec)
