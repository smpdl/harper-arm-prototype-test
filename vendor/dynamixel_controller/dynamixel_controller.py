"""dynamixel-controller library extension hooks."""

from __future__ import annotations

from typing import Any

from dynio.dynamixel_controller import DynamixelIO as BaseDynamixelIO
from dynio.dynamixel_controller import DynamixelMotor


class DynamixelIO(BaseDynamixelIO):
    """Project extension point for shared controller enhancements."""

    def new_motor(  # type: ignore[override]
        self,
        dxl_id: int,
        json_file: str,
        protocol: int = 2,
        control_table_protocol: int | None = None,
    ) -> DynamixelMotor:
        """Create a motor from an arbitrary control-table JSON path."""
        return super().new_motor(
            dxl_id=dxl_id,
            json_file=json_file,
            protocol=protocol,
            control_table_protocol=control_table_protocol,
        )

    def bulk_read(self, *_: Any, **__: Any) -> Any:
        """Placeholder for upcoming bulk read extension."""
        raise NotImplementedError("bulk_read is not implemented in the project yet.")

    def bulk_write(self, *_: Any, **__: Any) -> Any:
        """Placeholder for upcoming bulk write extension."""
        raise NotImplementedError("bulk_write is not implemented in the project yet.")
