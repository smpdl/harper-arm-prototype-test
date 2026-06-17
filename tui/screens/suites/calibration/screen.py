"""Calibration session screen."""

from __future__ import annotations

import traceback
from typing import ClassVar, cast

from textual import on, work
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Select, Static, Tree

from harper_arm.calibration.config import (
    DEFAULT_CALIBRATION_PATH,
    jog_command_rows,
    load_calibration_settings,
)
from harper_arm.calibration.errors import CalibrationError, EmergencyStopError
from tui.catalog import TUI_CALIBRATION_SESSION_TESTS, TestSpec, tui_calibration_tree_specs
from tui.core.paths import RunPaths
from tui.screens.suites.base import SuiteRunnerScreen
from tui.screens.suites.calibration.controller import CalibrationSessionController


class CalibrationScreen(SuiteRunnerScreen):
    BINDINGS: ClassVar[list[Binding]] = [
        *SuiteRunnerScreen.BINDINGS,
    ]

    def __init__(self, paths: RunPaths) -> None:
        super().__init__(paths, browser_title="Calibration")
        self._controller: CalibrationSessionController | None = None
        self._session_ready = False
        self._action_busy = False
        self._refresh_scheduled = False
        self._active_session_test: str | None = None

    def populate_tree(self, tree: Tree) -> None:
        tree.root.remove_children()
        for spec in tui_calibration_tree_specs():
            tree.root.add_leaf(spec.tree_label, data=spec)

    def on_mount(self) -> None:
        super().on_mount()
        self.set_interval(0.5, self._poll_display)
        self.set_timer(0, self._select_default_test)

    async def _select_default_test(self) -> None:
        specs = tui_calibration_tree_specs()
        if not specs:
            return
        tree = self.query_one("#test-tree", Tree)
        if tree.root.children:
            tree.select_node(tree.root.children[0])
        await self._select_test(specs[0])

    async def _select_test(self, spec: TestSpec | None) -> None:
        await self._teardown_calibration_ui()
        await super()._select_test(spec)
        if spec is not None and spec.name in TUI_CALIBRATION_SESSION_TESTS:
            await self._setup_calibration_ui(spec)
            self._connect_calibration_session()

    async def _setup_calibration_ui(self, spec: TestSpec) -> None:
        self._active_session_test = spec.name
        self.query_one("#run-button", Button).display = False

        scroll = self.query_one("#config-scroll", VerticalScroll)
        section = Vertical(id="calibration-section")
        await scroll.mount(section)

        await section.mount(Static("Connecting…", id="calibration-position"))

        buttons = Vertical(id="calibration-buttons")
        await section.mount(buttons)

        if spec.name == "non_backdriveable":
            jog_container = Vertical(id="calibration-jog", classes="calibration-jog")
            await buttons.mount(jog_container)
            settings = load_calibration_settings(DEFAULT_CALIBRATION_PATH)
            negative_row, positive_row = jog_command_rows(settings)
            for row_labels in (negative_row, positive_row):
                row = Horizontal(classes="btn-row jog-row")
                await jog_container.mount(row)
                for label in row_labels:
                    await row.mount(
                        Button(
                            label,
                            classes="calibration-btn jog-btn btn-black",
                            disabled=True,
                        )
                    )

        record_row = Horizontal(id="calibration-record-row", classes="btn-row")
        await buttons.mount(record_row)
        for button_id, label in (
            ("record-min", "Rec Min"),
            ("record-max", "Rec Max"),
            ("record-home", "Rec Home"),
            ("run-calibration", "Save"),
        ):
            classes = "calibration-btn btn-run" if button_id == "run-calibration" else "calibration-btn btn-black"
            await record_row.mount(
                Button(
                    label,
                    id=button_id,
                    classes=classes,
                    disabled=True,
                )
            )

        await section.mount(Static(self._recorded_text(), id="calibration-recorded"))

    async def _teardown_calibration_ui(self) -> None:
        self._disconnect_calibration_session()
        self._active_session_test = None
        self.query_one("#run-button", Button).display = True
        section = self._calibration_section()
        if section is not None:
            await section.remove()

    def _recorded_text(
        self,
        *,
        min_pos: int | None = None,
        home_pos: int | None = None,
        max_pos: int | None = None,
    ) -> str:
        def fmt(value: int | None) -> str:
            return "—" if value is None else str(value)

        return (
            f"Min: {fmt(min_pos)}    "
            f"Max: {fmt(max_pos)}    "
            f"Home: {fmt(home_pos)}"
        )

    def _update_recorded(self) -> None:
        section = self._calibration_section()
        if section is None or self._controller is None:
            return
        min_pos, home_pos, max_pos = self._controller.recorded_positions()
        section.query_one("#calibration-recorded", Static).update(
            self._recorded_text(
                min_pos=min_pos,
                home_pos=home_pos,
                max_pos=max_pos,
            )
        )

    def _calibration_section(self) -> Vertical | None:
        sections = self.query("#calibration-section")
        return cast(Vertical, sections.first()) if sections else None

    def _set_calibration_controls_enabled(self, enabled: bool) -> None:
        section = self._calibration_section()
        if section is None:
            return
        for button in section.query(".calibration-btn"):
            button.disabled = not enabled

    def _set_calibration_position(self, message: str) -> None:
        section = self._calibration_section()
        if section is None:
            return
        section.query_one("#calibration-position", Static).update(message)

    def _selected_joint(self) -> str | None:
        widget = self._field_widgets.get("joint")
        if not isinstance(widget, Select):
            return None
        value = widget.value
        if value is Select.BLANK or not value:
            return None
        return str(value)

    @on(Select.Changed, "#field-joint")
    def on_joint_changed(self, _event: Select.Changed) -> None:
        if self._active_session_test is None:
            return
        self._connect_calibration_session()

    @work(thread=True)
    def _connect_calibration_session(self) -> None:
        if self._active_session_test is None:
            return
        joint = self._selected_joint()
        if joint is None:
            self._call_from_thread(self._set_status, "Select a joint first.")
            return

        self._disconnect_calibration_session()
        self._call_from_thread(self._set_calibration_controls_enabled, False)
        self._call_from_thread(self._set_calibration_position, "Connecting…")
        self._call_from_thread(self._set_status, f"Connecting to {joint}…")

        controller = CalibrationSessionController(
            self.paths,
            test=self._active_session_test,
            joint=joint,
        )
        try:
            controller.open()
        except Exception:
            self._call_from_thread(self._write_log, "[red]Failed to open calibration session:[/]")
            self._call_from_thread(self._write_log, traceback.format_exc())
            self._call_from_thread(self._set_status, "Connection failed")
            self._call_from_thread(self._set_calibration_position, "Connection failed")
            return

        if self._selected_joint() != joint or self._active_session_test != controller.test:
            controller.close()
            return

        self._controller = controller
        self._session_ready = True
        self._call_from_thread(
            self._write_log,
            f"[cyan]▶ calibration/{controller.test}[/] joint={joint}",
        )
        self._call_from_thread(self._set_status, "Ready — use the buttons to calibrate")
        self._call_from_thread(self._set_calibration_controls_enabled, True)
        self._call_from_thread(self._refresh_display)

    def _disconnect_calibration_session(self) -> None:
        self._session_ready = False
        if self._controller is not None:
            self._controller.close()
            self._controller = None

    def _poll_display(self) -> None:
        if (
            not self._session_ready
            or self._action_busy
            or self._refresh_scheduled
            or self._controller is None
        ):
            return
        self._refresh_scheduled = True
        self._refresh_display()

    @work(thread=True)
    def _refresh_display(self) -> None:
        try:
            if self._controller is None:
                return
            position, status = self._controller.refresh()
            self._call_from_thread(
                self._set_calibration_position,
                f"Position: {position} ticks",
            )
            self._call_from_thread(self._update_motor_status, status)
            self._call_from_thread(self._update_recorded)
        except Exception as exc:
            self._call_from_thread(self._write_log, f"[yellow]Refresh failed:[/] {exc}")
        finally:
            self._refresh_scheduled = False

    @work(thread=True)
    def _run_action(self, action: str, *, jog_command: str | None = None) -> None:
        if not self._session_ready or self._controller is None or self._action_busy:
            return
        self._action_busy = True
        try:
            if action == "record_min":
                ticks = self._controller.record_min()
                self._call_from_thread(self._write_log, f"Recorded MIN = {ticks}")
            elif action == "record_home":
                ticks = self._controller.record_home()
                self._call_from_thread(self._write_log, f"Recorded HOME = {ticks}")
            elif action == "record_max":
                ticks = self._controller.record_max()
                self._call_from_thread(self._write_log, f"Recorded MAX = {ticks}")
            elif action == "jog" and jog_command is not None:
                reached, measured = self._controller.jog(jog_command)
                note = "" if reached else " (did not settle)"
                self._call_from_thread(
                    self._write_log,
                    f"Jog {jog_command} → {measured} ticks{note}",
                )
            elif action == "save":
                run_dir = self._controller.save()
                self._call_from_thread(
                    self._write_log,
                    "[green]✓ Saved calibration to config[/]",
                )
                self._call_from_thread(
                    self._write_log,
                    f"[green]✓ Results written to[/] [bold]{run_dir}[/]",
                )
                self._call_from_thread(self._set_status, f"Saved: {run_dir}")
                self._disconnect_calibration_session()
                self._call_from_thread(self._set_calibration_controls_enabled, False)
                return
            self._call_from_thread(self._refresh_display)
            self._call_from_thread(self._set_status, "Ready")
        except CalibrationError as exc:
            self._call_from_thread(self._write_log, f"[yellow]{exc}[/]")
            self._call_from_thread(self._set_status, str(exc))
        except EmergencyStopError as exc:
            self._call_from_thread(self._write_log, f"[red]{exc}[/]")
            self._call_from_thread(self._set_status, str(exc))
        except Exception:
            self._call_from_thread(self._write_log, "[red]Action failed:[/]")
            self._call_from_thread(self._write_log, traceback.format_exc())
            self._call_from_thread(self._set_status, "Action failed")
        finally:
            self._action_busy = False

    def action_go_home(self) -> None:
        self._disconnect_calibration_session()
        super().action_go_home()

    @on(Button.Pressed, "#record-min")
    def on_record_min(self) -> None:
        self._run_action("record_min")

    @on(Button.Pressed, "#record-home")
    def on_record_home(self) -> None:
        self._run_action("record_home")

    @on(Button.Pressed, "#record-max")
    def on_record_max(self) -> None:
        self._run_action("record_max")

    @on(Button.Pressed, "#run-calibration")
    def on_run_calibration(self) -> None:
        self._set_status("Saving…")
        self._run_action("save")

    @on(Button.Pressed, ".jog-btn")
    def on_jog_pressed(self, event: Button.Pressed) -> None:
        label = str(event.button.label)
        self._set_status(f"Jogging {label}…")
        self._run_action("jog", jog_command=label)
