from __future__ import annotations

from typing import Any


SCHEMA_VERSION = 2

BLOCK_TYPES = {
    "pump_start",
    "pump_stop",
    "stop_all",
    "wait",
    "log_marker",
    "prompt_check",
}

PUMP_ACTIONS = {
    "pump_start": {"start_forward", "start_reverse"},
    "pump_stop": {"stop"},
}

ACTION_TO_COMMAND_KEY = {
    "start_forward": "start_forward",
    "start_reverse": "start_reverse",
    "stop": "stop",
}

DEFAULT_BLOCKS: dict[str, dict[str, Any]] = {
    "pump_start": {
        "type": "pump_start",
        "pump": "IN",
        "action": "start_forward",
        "profile": "fast30_1ml",
        "note": "",
    },
    "pump_stop": {
        "type": "pump_stop",
        "pump": "IN",
        "action": "stop",
        "note": "",
    },
    "stop_all": {
        "type": "stop_all",
        "note": "Safety stop",
    },
    "wait": {
        "type": "wait",
        "duration_s": 1.0,
    },
    "log_marker": {
        "type": "log_marker",
        "message": "Marker",
        "note": "",
    },
    "prompt_check": {
        "type": "prompt_check",
        "message": "Confirm before continuing",
        "note": "",
    },
}


def default_block(block_type: str) -> dict[str, Any]:
    if block_type not in DEFAULT_BLOCKS:
        raise ValueError(f"Unknown block type: {block_type}")
    return DEFAULT_BLOCKS[block_type].copy()


def block_summary(block: dict[str, Any]) -> str:
    block_type = block.get("type", "")
    block_id = block.get("id", "")
    if block_type == "pump_start":
        return (
            f"{block_id}  Pump start  {block.get('pump', '')} "
            f"{block.get('action', '')}  {block.get('profile', '')}"
        )
    if block_type == "pump_stop":
        return f"{block_id}  Pump stop  {block.get('pump', '')}"
    if block_type == "stop_all":
        return f"{block_id}  STOP ALL"
    if block_type == "wait":
        return f"{block_id}  Wait  {float(block.get('duration_s', 0)):.3f} s"
    if block_type == "log_marker":
        return f"{block_id}  Log marker  {block.get('message', '')}"
    if block_type == "prompt_check":
        return f"{block_id}  Prompt check  {block.get('message', '')}"
    return f"{block_id}  {block_type}"
