"""Unified test suite browser screen."""

from __future__ import annotations

from textual.widgets import Tree

from tui.catalog import TestSpec, tui_test_tree_specs
from tui.core.paths import RunPaths
from tui.screens.suites.e2e import E2ESessionMixin
from tui.screens.suites.structural import StructuralRunnerScreen


class TestsRunnerScreen(E2ESessionMixin, StructuralRunnerScreen):
    def __init__(self, paths: RunPaths) -> None:
        super().__init__(paths, browser_title="Tests")
        self._init_e2e_session_state()

    def populate_tree(self, tree: Tree) -> None:
        tree.root.remove_children()
        for group_label, specs in tui_test_tree_specs():
            group = tree.root.add(group_label, expand=True)
            for spec in specs:
                group.add_leaf(spec.tree_label, data=spec)

    async def _select_test(self, spec: TestSpec | None) -> None:
        await self._reset_e2e_session()
        await super()._select_test(spec)
        await self._mount_e2e_preview(spec)

    def action_run_test(self) -> None:
        if self._selected is not None and self._selected.suite == "e2e":
            if self._structural_session_active:
                self._set_status("Finish the current test first.")
                return
            self._run_e2e_test()
            return
        if self._e2e_session_active:
            self._set_status("An e2e motion is already active.")
            return
        super().action_run_test()

    def action_go_home(self) -> None:
        if self._e2e_session_active:
            self._disconnect_e2e_session()
        super().action_go_home()
