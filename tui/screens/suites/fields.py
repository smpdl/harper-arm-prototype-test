"""Suite runner field widgets and kwargs collection."""

from __future__ import annotations

from typing import Any

from textual.containers import Horizontal, Vertical, Vertical
from textual.widgets import Input, Label, Select, Switch

from harper_arm.calibration.joints import is_backdriveable_joint
from tui.catalog import FieldSpec, TestSpec


class SuiteFieldMixin:
    """Build and read per-test configuration fields."""

    _joints: list[str]
    _poses: list[str]
    _pose_options: list[tuple[str, str]]
    _field_widgets: dict[str, Input | Select[str] | Switch]

    async def _mount_field_row(self, fields: Vertical, field: FieldSpec) -> None:
        widget = self._build_field_widget(field)
        widget.add_class("field-control")
        self._field_widgets[field.name] = widget
        row = Horizontal(classes="field-row")
        await fields.mount(row)
        await row.mount(Label(field.label, classes="field-label"), widget)

    def _joints_for_field(self, field: FieldSpec) -> list[str]:
        if field.joint_filter is None:
            return self._joints
        want_backdriveable = field.joint_filter == "backdriveable"
        return [
            name
            for name in self._joints
            if is_backdriveable_joint(name) == want_backdriveable
        ]

    def _build_field_widget(self, field: FieldSpec) -> Input | Select[str] | Switch:
        if field.field_type == "bool":
            widget: Input | Select[str] | Switch = Switch(value=bool(field.default))
        elif field.field_type == "joint":
            joints = self._joints_for_field(field)
            options = [(name, name) for name in joints] or [("(none)", "")]
            widget = Select(options, prompt="Select joint", id=f"field-{field.name}")
            if joints:
                widget.value = joints[0]
        elif field.field_type == "pose":
            options = self._pose_options or [(name, name) for name in self._poses] or [
                ("(none)", "")
            ]
            widget = Select(options, prompt="Select pose", id=f"field-{field.name}")
            default_pose = str(field.default) if field.default else None
            if default_pose and default_pose in self._poses:
                widget.value = default_pose
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
