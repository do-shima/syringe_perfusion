from __future__ import annotations

import csv
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import logs_dir


LOG_COLUMNS = [
    "timestamp",
    "event_id",
    "started_at",
    "ended_at",
    "dish_id",
    "condition",
    "trigger_source",
    "plan_id",
    "run_id",
    "perfusion_state",
    "pump",
    "port",
    "action",
    "command",
    "mode",
    "jog_duration_ms",
    "profile",
    "syringe",
    "speed_mm_min",
    "duration_s",
    "target_volume_ul",
    "estimated_volume_ul",
    "requested_flow_ml_min",
    "estimated_actual_flow_ml_min",
    "in_to_out_delay_s",
    "response",
    "response_hex",
    "note",
    "recipe_id",
    "block_id",
    "block_type",
    "relative_time_s",
    "block_index",
]


def today_log_path(log_root: str | Path | None = None) -> Path:
    root = logs_dir(log_root)
    stamp = datetime.now().strftime("%Y%m%d")
    return root / f"a4pump_{stamp}.csv"


def write_log(row: dict[str, Any], log_root: str | Path | None = None) -> Path:
    path = today_log_path(log_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    complete = normalize_log_row(row)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
        if needs_header:
            writer.writeheader()
        writer.writerow(complete)
    return path


def normalize_log_row(row: dict[str, Any]) -> dict[str, Any]:
    timestamp = row.get("timestamp") or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    event_id = row.get("event_id") or str(uuid.uuid4())
    complete = {column: "" for column in LOG_COLUMNS}
    complete.update(row)
    complete["timestamp"] = timestamp
    complete["event_id"] = event_id
    return complete


def log_command(
    *,
    result: dict[str, Any],
    action: str,
    dish_id: str = "",
    condition: str = "",
    trigger_source: str = "",
    plan_id: str = "",
    run_id: str = "",
    perfusion_state: str = "",
    profile: str = "",
    syringe: str = "",
    speed_mm_min: float | str | None = None,
    duration_s: float | str | None = None,
    target_volume_ul: float | str | None = None,
    estimated_volume_ul: float | str | None = None,
    requested_flow_ml_min: float | str | None = None,
    estimated_actual_flow_ml_min: float | str | None = None,
    in_to_out_delay_s: float | str | None = None,
    note: str = "",
    mode: str = "",
    jog_duration_ms: int | str | None = None,
    recipe_id: str = "",
    block_id: str = "",
    block_type: str = "",
    relative_time_s: float | str | None = None,
    block_index: int | str | None = None,
    started_at: str = "",
    ended_at: str = "",
    log_root: str | Path | None = None,
) -> Path:
    row = {
        "timestamp": result.get("timestamp"),
        "started_at": started_at,
        "ended_at": ended_at,
        "dish_id": dish_id,
        "condition": condition,
        "trigger_source": trigger_source,
        "plan_id": plan_id,
        "run_id": run_id,
        "perfusion_state": perfusion_state,
        "pump": result.get("pump", ""),
        "port": result.get("port", ""),
        "action": action,
        "command": result.get("command", ""),
        "mode": mode,
        "jog_duration_ms": _clean(jog_duration_ms),
        "profile": profile,
        "syringe": syringe,
        "speed_mm_min": _clean(speed_mm_min),
        "duration_s": _clean(duration_s),
        "target_volume_ul": _clean(target_volume_ul),
        "estimated_volume_ul": _clean(estimated_volume_ul),
        "requested_flow_ml_min": _clean(requested_flow_ml_min),
        "estimated_actual_flow_ml_min": _clean(estimated_actual_flow_ml_min),
        "in_to_out_delay_s": _clean(in_to_out_delay_s),
        "response": result.get("response", ""),
        "response_hex": result.get("response_hex", ""),
        "note": note,
        "recipe_id": recipe_id,
        "block_id": block_id,
        "block_type": block_type,
        "relative_time_s": _clean(relative_time_s),
        "block_index": _clean(block_index),
    }
    return write_log(row, log_root)


def _clean(value: Any) -> Any:
    return "" if value is None else value
