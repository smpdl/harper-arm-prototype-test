"""Motor ping test"""

from __future__ import annotations

from pathlib import Path

from dynamixel_sdk import COMM_SUCCESS
from dynio import DynamixelIO

from harper_arm.joint import DEFAULT_CONFIG_PATH

from .helpers import DEFAULT_RESULTS_ROOT, StatusCallback, motor_test_run, utc_now


def ping_joint(io: DynamixelIO, motor_id: int, protocol: int) -> tuple[bool, str]:
    """Ping one motor on the bus and return whether it responded."""
    handler = io.packet_handler[protocol - 1]
    model_number, comm_result, dxl_error = handler.ping(io.port_handler, motor_id)
    if comm_result != COMM_SUCCESS:
        return False, handler.getTxRxResult(comm_result)
    if dxl_error != 0:
        return False, handler.getRxPacketError(dxl_error)
    return True, f"model {model_number}"

def run(
    *,
    joint: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    on_status: StatusCallback | None = None,
) -> Path:
    with motor_test_run(
        test="ping",
        schema="ping",
        joint_name=joint,
        config_path=config_path,
        results_root=results_root,
        on_status=on_status,
    ) as (connected_joint, recorder):
        success, message = ping_joint(
            connected_joint.io,
            connected_joint.joint.id,
            connected_joint.joint.protocol,
        )
        recorder.write_row(
            {
                "timestamp_utc": utc_now().isoformat(),
                "joint": joint,
                "success": success,
                "message": message,
            }
        )
        recorder.set_summary(success=success, message=message)
        return recorder.run_dir
