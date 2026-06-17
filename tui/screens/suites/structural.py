"""Inline UI for operator-assisted structural tests."""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Any, ClassVar, cast

from textual import on, work
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Static

from suites.structural.operator import PointLoadOperator
from tui.catalog import TUI_STRUCTURAL_SESSION_TESTS, TestSpec
from tui.core.paths import RunPaths
from tui.screens.suites.base import SuiteRunnerScreen


class StructuralRunnerScreen(SuiteRunnerScreen):
    BINDINGS: ClassVar[list[Binding]] = [
        *SuiteRunnerScreen.BINDINGS,
    ]

    def __init__(self, paths: RunPaths, *, browser_title: str) -> None:
        super().__init__(paths, browser_title=browser_title)
        self._structural_operator: PointLoadOperator | None = None
        self._structural_operator_lock = threading.Lock()
        self._structural_session_active = False
        self._structural_action_busy = False
        self._active_structural_test: str | None = None

    async def _select_test(self, spec: TestSpec | None) -> None:
        await self._teardown_structural_ui()
        await super()._select_test(spec)
        self._refresh_action_buttons()

    def _show_bring_home_button(self) -> bool:
        return (
            self._selected is not None
            and self._selected.name in TUI_STRUCTURAL_SESSION_TESTS
        ) or self._structural_session_active

    def _refresh_action_buttons(self) -> None:
        bring_home_button = self.query_one("#bring-home-button", Button)
        show = self._show_bring_home_button()
        bring_home_button.display = show
        if not show:
            bring_home_button.disabled = True
            return
        if self._structural_session_active and self._structural_operator is not None:
            bring_home_button.disabled = (
                self._structural_action_busy or self._structural_operator.is_complete
            )
        else:
            bring_home_button.disabled = self._structural_action_busy

    def action_run_test(self) -> None:
        if self._selected is None:
            self._set_status("Select a test first.")
            return
        if self._selected.name in TUI_STRUCTURAL_SESSION_TESTS:
            if self._structural_session_active or self._structural_action_busy:
                self._set_status("A structural test is already running.")
                return
            try:
                kwargs = self._collect_kwargs(self._selected)
            except ValueError as exc:
                self._set_status(str(exc))
                self._write_log(f"[red]Configuration error:[/] {exc}")
                return
            self._set_status(f"Starting {self._selected.label}…")
            self._open_structural_session(self._selected, kwargs)
            return
        super().action_run_test()

    async def _setup_structural_ui(self, spec: TestSpec) -> None:
        self._active_structural_test = spec.name

        scroll = self.query_one("#config-scroll", VerticalScroll)
        section = Vertical(id="structural-section")
        await scroll.mount(section)

        await section.mount(
            Static("Preparing…", id="structural-instruction"),
            Static("", id="structural-progress"),
            Input(placeholder="Load description", id="structural-load-description"),
            Input(placeholder="Operator notes", id="structural-operator-notes"),
        )

        row = Horizontal(classes="btn-row")
        await section.mount(row)
        await row.mount(
            Button(
                "Confirm Approach",
                id="structural-confirm-approach",
                classes="structural-btn btn-run",
            ),
            Button("Ready", id="structural-ready", classes="structural-btn btn-black"),
            Button("Record", id="structural-record", classes="structural-btn btn-black"),
        )
        self._refresh_structural_ui()

    async def _teardown_structural_ui(self) -> None:
        self._disconnect_structural_session()
        self._active_structural_test = None
        section = self._structural_section()
        if section is not None:
            await section.remove()
        self._refresh_action_buttons()

    def _structural_section(self) -> Vertical | None:
        sections = self.query("#structural-section")
        return cast(Vertical, sections.first()) if sections else None

    def _create_structural_operator(
        self,
        spec: TestSpec,
        kwargs: dict[str, Any],
    ) -> PointLoadOperator:
        if spec.name != "point_load":
            raise ValueError(f"unsupported structural session test: {spec.name}")
        return PointLoadOperator(
            pose=str(kwargs.get("pose", "home")),
            config_path=self.paths.config_path,
            e2e_config_path=self.paths.e2e_config_path,
            results_root=self.paths.results_root,
        )

    @work(thread=True)
    def _open_structural_session(self, spec: TestSpec, kwargs: dict[str, Any]) -> None:
        self._structural_action_busy = True
        operator = self._create_structural_operator(spec, kwargs)
        try:
            operator.open()
        except Exception:
            self._call_from_thread(self._write_log, "[red]Failed to start structural test:[/]")
            self._call_from_thread(self._write_log, traceback.format_exc())
            self._call_from_thread(self._set_status, "Failed to start test")
            self._call_from_thread(self._refresh_action_buttons)
            self._structural_action_busy = False
            return

        self._structural_operator = operator
        self._structural_session_active = True
        self._call_from_thread(self._refresh_action_buttons)
        if operator.is_complete:
            run_dir = operator.run_dir
            self._call_from_thread(self._write_log, "[yellow]Test ended during setup.[/]")
            self._call_from_thread(self._finish_structural_session, run_dir)
            self._structural_action_busy = False
            return
        self._call_from_thread(self._begin_structural_ui, spec, kwargs)
        self._structural_action_busy = False

    def _begin_structural_ui(self, spec: TestSpec, kwargs: dict[str, Any]) -> None:
        self.run_worker(self._mount_structural_ui(spec, kwargs), exclusive=True)

    async def _mount_structural_ui(self, spec: TestSpec, kwargs: dict[str, Any]) -> None:
        await self._setup_structural_ui(spec)
        self._refresh_structural_ui()
        self._refresh_action_buttons()
        pose = str(kwargs.get("pose", "home"))
        self._write_log(f"[cyan]▶ structural/{spec.name}[/] pose={pose}")
        if pose != "home":
            from suites.structural.helpers import pose_approach_preview_lines

            for line in pose_approach_preview_lines(
                pose,
                config_path=self.paths.config_path,
                e2e_config_path=self.paths.e2e_config_path,
            ):
                self._write_log(line)
        self._set_status("Follow the on-screen steps, then press Bring Home.")

    def _disconnect_structural_session(self) -> None:
        self._structural_session_active = False
        if self._structural_operator is not None:
            self._structural_operator.close()
            self._structural_operator = None

    def _finish_structural_session(self, run_dir: Path) -> None:
        self._disconnect_structural_session()
        self._write_log(f"[green]✓ Results written to[/] [bold]{run_dir}[/]")
        self._set_status(f"Finished: {run_dir}")
        self.run_worker(self._teardown_structural_ui(), exclusive=True)

    def _refresh_structural_ui(self) -> None:
        section = self._structural_section()
        operator = self._structural_operator
        if section is None or operator is None:
            return

        section.query_one("#structural-instruction", Static).update(operator.instruction)
        section.query_one("#structural-progress", Static).update(operator.progress_text)

        load_input = section.query_one("#structural-load-description", Input)
        notes_input = section.query_one("#structural-operator-notes", Input)
        confirm_btn = section.query_one("#structural-confirm-approach", Button)
        ready_btn = section.query_one("#structural-ready", Button)
        record_btn = section.query_one("#structural-record", Button)

        phase = operator.phase

        confirm_btn.display = phase == "await_pose_confirm"
        load_input.display = phase == "await_inputs"
        notes_input.display = phase == "await_inputs"
        ready_btn.display = phase == "await_ready"
        record_btn.display = phase == "await_inputs"

        for button in (confirm_btn, ready_btn, record_btn):
            button.disabled = self._structural_action_busy
        self._refresh_action_buttons()

    def action_go_home(self) -> None:
        if (
            self._structural_session_active
            and self._structural_operator is not None
            and not self._structural_action_busy
        ):
            self._structural_bring_home()
            return
        self._disconnect_structural_session()
        super().action_go_home()

    @on(Button.Pressed, "#structural-confirm-approach")
    def on_structural_confirm_approach(self) -> None:
        self._structural_confirm_approach()

    @on(Button.Pressed, "#structural-ready")
    def on_structural_ready(self) -> None:
        self._structural_point_load_ready()

    @on(Button.Pressed, "#structural-record")
    def on_structural_record(self) -> None:
        section = self._structural_section()
        if section is None:
            return
        load_description = section.query_one("#structural-load-description", Input).value.strip()
        operator_notes = section.query_one("#structural-operator-notes", Input).value.strip()
        self._structural_point_load_record(load_description, operator_notes)

    @on(Button.Pressed, "#bring-home-button")
    def on_bring_home_pressed(self) -> None:
        if self._structural_session_active and self._structural_operator is not None:
            self._structural_bring_home()
        else:
            self._standalone_bring_home()

    @work(thread=True)
    def _structural_confirm_approach(self) -> None:
        operator = self._structural_operator
        if operator is None:
            return
        self._structural_action_busy = True
        self._call_from_thread(self._set_status, "Moving to hold pose...")
        try:
            with self._structural_operator_lock:
                operator.confirm_approach()
            if operator.is_complete:
                run_dir = operator.run_dir
                self._call_from_thread(self._write_log, "[yellow]Test ended during approach.[/]")
                self._call_from_thread(self._finish_structural_session, run_dir)
            else:
                self._call_from_thread(self._refresh_structural_ui)
                self._call_from_thread(self._set_status, "Follow the on-screen steps.")
        except Exception:
            self._call_from_thread(self._write_log, "[red]Approach move failed:[/]")
            self._call_from_thread(self._write_log, traceback.format_exc())
            self._call_from_thread(self._set_status, "Approach move failed")
        finally:
            self._structural_action_busy = False
            self._call_from_thread(self._refresh_action_buttons)

    @work(thread=True)
    def _structural_point_load_ready(self) -> None:
        operator = self._structural_operator
        if operator is None:
            return
        self._structural_action_busy = True
        try:
            with self._structural_operator_lock:
                operator.mark_ready()
            self._call_from_thread(self._refresh_structural_ui)
            self._call_from_thread(self._set_status, "Enter load details, then press Record.")
        except Exception as exc:
            self._call_from_thread(self._write_log, f"[red]{exc}[/]")
            self._call_from_thread(self._set_status, "Action failed")
        finally:
            self._structural_action_busy = False
            self._call_from_thread(self._refresh_action_buttons)

    @work(thread=True)
    def _structural_point_load_record(self, load_description: str, operator_notes: str) -> None:
        operator = self._structural_operator
        if operator is None:
            return
        self._structural_action_busy = True
        try:
            with self._structural_operator_lock:
                result = operator.record(load_description, operator_notes)
            self._call_from_thread(
                self._write_log,
                f"Recorded {result.link}: max flex {result.max_flex_deg:.2f}°",
            )
            if result.stopped_early:
                self._call_from_thread(
                    self._write_log,
                    f"[yellow]Stopped early:[/] {result.stop_reason}",
                )
            if operator.is_complete:
                run_dir = operator.run_dir
                self._call_from_thread(self._finish_structural_session, run_dir)
            else:
                section = self._structural_section()
                if section is not None:
                    section.query_one("#structural-load-description", Input).value = ""
                    section.query_one("#structural-operator-notes", Input).value = ""
                self._call_from_thread(self._refresh_structural_ui)
                if operator.phase == "await_bring_home":
                    self._call_from_thread(
                        self._set_status,
                        "All links recorded. Press Bring Home beside Run to finish.",
                    )
                else:
                    self._call_from_thread(self._set_status, "Ready for next link.")
        except Exception:
            self._call_from_thread(self._write_log, "[red]Record failed:[/]")
            self._call_from_thread(self._write_log, traceback.format_exc())
            self._call_from_thread(self._set_status, "Record failed")
        finally:
            self._structural_action_busy = False
            self._call_from_thread(self._refresh_action_buttons)

    @work(thread=True)
    def _standalone_bring_home(self) -> None:
        if self._structural_action_busy:
            return
        self._structural_action_busy = True
        self._call_from_thread(self._refresh_action_buttons)
        self._call_from_thread(self._set_status, "Returning home…")
        try:
            from harper_arm.arm import FullArm
            from harper_arm.config import require_arm_calibrated, load_arm_config

            from suites.structural.helpers import (
                load_motion_config,
                move_home_scurve,
                prepare_motion_bus,
            )

            require_arm_calibrated(load_arm_config(self.paths.config_path))
            motion = load_motion_config("home", e2e_config_path=self.paths.e2e_config_path)
            arm = FullArm.open(config_path=self.paths.config_path)
            try:
                prepare_motion_bus(arm, motion)
                reached_home, stop_reason, _ = move_home_scurve(
                    arm,
                    config_path=self.paths.config_path,
                    e2e_config_path=self.paths.e2e_config_path,
                    motion=motion,
                )
            finally:
                arm.close(skip_homing=True)
            if stop_reason:
                self._call_from_thread(
                    self._write_log,
                    f"[yellow]Stopped early:[/] {stop_reason}",
                )
            elif reached_home:
                self._call_from_thread(self._write_log, "[cyan]Returned to home.[/]")
            else:
                self._call_from_thread(
                    self._write_log,
                    "[yellow]Arm did not fully reach home.[/]",
                )
            self._call_from_thread(self._set_status, "Ready.")
        except Exception:
            self._call_from_thread(self._write_log, "[red]Bring home failed:[/]")
            self._call_from_thread(self._write_log, traceback.format_exc())
            self._call_from_thread(self._set_status, "Bring home failed")
        finally:
            self._structural_action_busy = False
            self._call_from_thread(self._refresh_action_buttons)

    @work(thread=True)
    def _structural_bring_home(self) -> None:
        operator = self._structural_operator
        if operator is None or self._structural_action_busy:
            return
        self._structural_action_busy = True
        self._call_from_thread(self._set_status, "Returning home…")
        try:
            with self._structural_operator_lock:
                operator.bring_home()
                run_dir = operator.run_dir
            self._call_from_thread(self._write_log, "[cyan]Returned to home.[/]")
            self._call_from_thread(self._finish_structural_session, run_dir)
        except Exception:
            self._call_from_thread(self._write_log, "[red]Bring home failed:[/]")
            self._call_from_thread(self._write_log, traceback.format_exc())
            self._call_from_thread(self._set_status, "Bring home failed")
        finally:
            self._structural_action_busy = False
            self._call_from_thread(self._refresh_action_buttons)
