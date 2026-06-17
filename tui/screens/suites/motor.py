"""Motor test suite browser screen."""

from __future__ import annotations

from textual.widgets import Tree

from tui.catalog import motor_test_specs, structural_test_specs
from tui.core.paths import RunPaths
from tui.screens.suites.structural import StructuralRunnerScreen


class MotorRunnerScreen(StructuralRunnerScreen):
    def __init__(self, paths: RunPaths) -> None:
        super().__init__(paths, browser_title="Motor Tests")

    def populate_tree(self, tree: Tree) -> None:
        tree.root.remove_children()
        for spec in motor_test_specs():
            tree.root.add_leaf(spec.tree_label, data=spec)


class StructuralTestsScreen(StructuralRunnerScreen):
    def __init__(self, paths: RunPaths) -> None:
        super().__init__(paths, browser_title="Structural Tests")

    def populate_tree(self, tree: Tree) -> None:
        tree.root.remove_children()
        for spec in structural_test_specs():
            tree.root.add_leaf(spec.tree_label, data=spec)
