"""Focused TUI flow for operator-confirmed e2e motions."""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import ClassVar, cast

from textual import on, work
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Static, Tree

from harper_arm.config import load_arm_config
from harper_arm.motion import ResolvedKeyframe, resolve_plan
from suites.e2e.config import load_e2e_config
from suites.e2e.operator import E2EOperator
from tui.catalog import TestSpec, e2e_test_specs
from tui.core.paths import RunPaths
from tui.screens.suites.base import SuiteRunnerScreen

_E2E_IDLE_INSTRUCTION = (
    "Press Run to connect. Confirm each keyframe when the arm area is clear."
)


class E2ESessionMixin:
    """Shared preview/confirm/stop workflow for operator-confirmed e2e motions."""

    _operator: E2EOperator | None
    _operator_lock: threading.Lock
    _e2e_session_active: bool
    _e2e_action_busy: bool

    def _init_e2e_session_state(self) -> None:
        self._operator = None
        self._operator_lock = threading.Lock()
        self._e2e_session_active = False
        self._e2e_action_busy = False

    def _e2e_section(self) -> Vertical | None:
        sections = self.query("#e2e-section")
        return cast(Vertical, sections.first()) if sections else None

    def _resolved_e2e_plan(self, spec: TestSpec) -> tuple[ResolvedKeyframe, ...]:
        e2e = load_e2e_config(self.paths.e2e_config_path)
        test = e2e.tests[spec.name]
        arm = load_arm_config(self.paths.config_path)
        return resolve_plan(arm, test.plan)

    def _e2e_keyframe_preview_lines(self, keyframe: ResolvedKeyframe) -> list[str]:
        lines = [f"{keyframe.index}. {keyframe.name}"]
        for target in keyframe.targets.values():
            lines.append(
                f"  {target.joint}: {target.fraction:+.2f} "
                f"-> {target.target_ticks} ticks"
            )
        return lines

    def _e2e_plan_preview_lines(self, spec: TestSpec) -> list[str]:
        try:
            resolved = self._resolved_e2e_plan(spec)
        except Exception as exc:
            return [f"Could not resolve motion plan: {exc}"]
        lines: list[str] = []
        for keyframe in resolved:
            lines.extend(self._e2e_keyframe_preview_lines(keyframe))
            lines.append("")
        if lines:
            lines.pop()
        return lines

    def _run_e2e_test(self) -> None:
        if self._selected is None:
            self._set_status("Select an e2e motion first.")
            return
        if self._e2e_session_active or self._e2e_action_busy:
            self._set_status("An e2e motion is already active.")
            return
        self._set_status(f"Opening {self._selected.label}...")
        self._open_e2e_session(self._selected)

    async def _reset_e2e_session(self) -> None:
        self._disconnect_e2e_session()
        self._set_e2e_run_button_visible(True)

    async def _mount_e2e_preview(self, spec: TestSpec | None) -> None:
        if spec is None or spec.suite != "e2e":
            await self._teardown_e2e_ui()
            return
        await self._ensure_e2e_ui()
        self._refresh_e2e_ui()

    async def _ensure_e2e_ui(self) -> None:
        if self._e2e_section() is not None:
            return
        scroll = self.query_one("#config-scroll", VerticalScroll)
        section = Vertical(id="e2e-section")
        await scroll.mount(section)
        await section.mount(
            Static(_E2E_IDLE_INSTRUCTION, id="e2e-instruction"),
            Static("", id="e2e-progress"),
            Static("", id="e2e-preview"),
        )
        row = Horizontal(classes="btn-row")
        await section.mount(row)
        await row.mount(
            Button("Move Step", classes="btn-black", id="e2e-confirm"),
            Button("Stop", classes="btn-stop", id="e2e-stop"),
        )

    async def _teardown_e2e_ui(self) -> None:
        self._set_e2e_run_button_visible(True)
        section = self._e2e_section()
        if section is not None:
            await section.remove()

    def _set_e2e_run_button_visible(self, visible: bool) -> None:
        self.query_one("#run-button", Button).display = visible

    @work(thread=True)
    def _open_e2e_session(self, spec: TestSpec) -> None:
        self._e2e_action_busy = True
        operator = E2EOperator(
            test=spec.name,
            config_path=self.paths.config_path,
            e2e_config_path=self.paths.e2e_config_path,
            results_root=self.paths.results_root,
        )
        try:
            operator.open()
        except Exception:
            self._call_from_thread(self._write_log, "[red]Failed to open e2e motion:[/]")
            self._call_from_thread(self._write_log, traceback.format_exc())
            self._call_from_thread(self._set_status, "Failed to open e2e motion")
            self._call_from_thread(self._refresh_e2e_ui)
            self._e2e_action_busy = False
            return

        self._operator = operator
        self._e2e_session_active = True
        self._call_from_thread(self._write_log, f"[cyan]▶ e2e/{spec.name}[/]")
        self._call_from_thread(self._on_e2e_session_opened)
        self._call_from_thread(self._set_status, "Preview the keyframe, then confirm.")
        self._e2e_action_busy = False

    def _on_e2e_session_opened(self) -> None:
        self._set_e2e_run_button_visible(False)
        self._refresh_e2e_ui()

    def _disconnect_e2e_session(self) -> None:
        self._e2e_session_active = False
        if self._operator is not None:
            self._operator.close()
            self._operator = None

    def _finish_e2e_session(self, run_dir: Path) -> None:
        self._disconnect_e2e_session()
        self._write_log(f"[green]✓ Results written to[/] [bold]{run_dir}[/]")
        self._set_status(f"Finished: {run_dir}")
        self._set_e2e_run_button_visible(True)
        self._refresh_e2e_ui()

    def _refresh_e2e_ui(self) -> None:
        section = self._e2e_section()
        if section is None:
            return

        if self._operator is not None and self._e2e_session_active:
            instruction = self._operator.instruction
            progress = self._operator.progress_text
            preview_lines = self._operator.preview_lines()
            controls_enabled = not self._e2e_action_busy
        elif self._selected is not None and self._selected.suite == "e2e":
            instruction = _E2E_IDLE_INSTRUCTION
            try:
                keyframe_count = len(self._resolved_e2e_plan(self._selected))
                progress = f"Not started — {keyframe_count} keyframes"
            except Exception as exc:
                progress = "Not started"
                preview_lines = [f"Could not resolve motion plan: {exc}"]
            else:
                preview_lines = self._e2e_plan_preview_lines(self._selected)
            controls_enabled = False
        else:
            return

        section.query_one("#e2e-instruction", Static).update(instruction)
        section.query_one("#e2e-progress", Static).update(progress)
        section.query_one("#e2e-preview", Static).update("\n".join(preview_lines))
        section.query_one("#e2e-confirm", Button).disabled = not controls_enabled
        section.query_one("#e2e-stop", Button).disabled = not controls_enabled

    @on(Button.Pressed, "#e2e-confirm")
    def on_confirm_step(self) -> None:
        self._confirm_e2e_step()

    @on(Button.Pressed, "#e2e-stop")
    def on_stop_e2e(self) -> None:
        self._stop_e2e_session()

    @work(thread=True)
    def _confirm_e2e_step(self) -> None:
        if self._operator is None or self._e2e_action_busy:
            return
        self._e2e_action_busy = True
        self._call_from_thread(self._set_status, "Moving confirmed keyframe...")
        try:
            with self._operator_lock:
                result = self._operator.confirm_step()
            self._call_from_thread(
                self._write_log,
                f"Moved keyframe {result.keyframe_index}: {result.keyframe_name}",
            )
            if result.stopped_early:
                self._call_from_thread(
                    self._write_log,
                    f"[yellow]Stopped early:[/] {result.stop_reason}",
                )
            if self._operator.is_complete:
                run_dir = self._operator.run_dir
                self._call_from_thread(self._finish_e2e_session, run_dir)
            else:
                self._call_from_thread(self._refresh_e2e_ui)
                self._call_from_thread(self._set_status, "Preview the next keyframe.")
        except Exception:
            self._call_from_thread(self._write_log, "[red]E2E step failed:[/]")
            self._call_from_thread(self._write_log, traceback.format_exc())
            self._call_from_thread(self._set_status, "E2E step failed")
        finally:
            self._e2e_action_busy = False
            self._call_from_thread(self._refresh_e2e_ui)

    @work(thread=True)
    def _stop_e2e_session(self) -> None:
        if self._operator is None:
            return
        if self._e2e_action_busy:
            with self._operator_lock:
                self._operator.stop()
            return
        self._e2e_action_busy = True
        try:
            with self._operator_lock:
                self._operator.stop()
                run_dir = self._operator.run_dir
            self._call_from_thread(self._finish_e2e_session, run_dir)
        except Exception:
            self._call_from_thread(self._write_log, "[red]Stop failed:[/]")
            self._call_from_thread(self._write_log, traceback.format_exc())
            self._call_from_thread(self._set_status, "Stop failed")
        finally:
            self._e2e_action_busy = False
            self._call_from_thread(self._refresh_e2e_ui)


class E2ERunnerScreen(E2ESessionMixin, SuiteRunnerScreen):
    """Run e2e motions as an explicit preview/confirm/step workflow."""

    BINDINGS: ClassVar[list[Binding]] = [
        *SuiteRunnerScreen.BINDINGS,
    ]

    def __init__(self, paths: RunPaths) -> None:
        super().__init__(paths, browser_title="E2E Motions")
        self._init_e2e_session_state()

    def populate_tree(self, tree: Tree) -> None:
        tree.root.remove_children()
        for spec in e2e_test_specs():
            tree.root.add_leaf(spec.tree_label, data=spec)

    def action_run_test(self) -> None:
        self._run_e2e_test()

    async def _select_test(self, spec: TestSpec | None) -> None:
        await self._reset_e2e_session()
        await super()._select_test(spec)
        await self._mount_e2e_preview(spec)

    def action_go_home(self) -> None:
        self._disconnect_e2e_session()
        super().action_go_home()
