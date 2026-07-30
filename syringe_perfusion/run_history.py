from __future__ import annotations

import csv
import io
import json
import tempfile
import os
from pathlib import Path
from typing import Any, Literal

from .config import ConfigResolution, resolve_config
from .perfusion_state import read_state, runtime_paths


def recent_runs(
    config: str | Path | ConfigResolution,
    *,
    limit: int = 20,
    dish_id: str = "",
    condition: str = "",
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    resolution = config if isinstance(config, ConfigResolution) else resolve_config(config)
    log_roots = [
        resolution.active_config_dir / "logs",
        resolution.active_config_dir.parent / "logs",
    ]
    rows: list[dict[str, str]] = []
    seen_roots: set[Path] = set()
    for log_root in log_roots:
        resolved = log_root.resolve()
        if resolved not in seen_roots:
            seen_roots.add(resolved)
            rows.extend(_read_csv_rows(resolved))
    transitions = _read_transitions(runtime_paths(resolution.active_config_dir).log)
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        run_id = str(row.get("run_id", "")).strip()
        if not run_id:
            continue
        item = grouped.setdefault(run_id, _empty_run(run_id))
        item["timestamp"] = max(item["timestamp"], str(row.get("timestamp", "")))
        for key in ("dish_id", "condition", "trigger_source", "plan_id"):
            if row.get(key):
                item[key] = row[key]
        role = str(row.get("pump", ""))
        if role == "IN" and row.get("requested_flow_ml_min"):
            item["in_flow_ml_min"] = row["requested_flow_ml_min"]
        if role == "OUT" and row.get("requested_flow_ml_min"):
            item["out_flow_ml_min"] = row["requested_flow_ml_min"]
        if row.get("duration_s"):
            item["duration_s"] = row["duration_s"]
        state = str(row.get("perfusion_state", ""))
        if state:
            item["start_state"] = item["start_state"] or state
            item["terminal_state"] = state
        action = str(row.get("action", "")).casefold()
        if "stop" in action:
            item["stop_or_fault"] = row.get("note") or action
    for transition in transitions:
        run_id = str(transition.get("run_id", "")).strip()
        if not run_id:
            continue
        item = grouped.setdefault(run_id, _empty_run(run_id))
        item["timestamp"] = max(item["timestamp"], str(transition.get("timestamp", "")))
        if transition.get("event") == "state_transition":
            item["start_state"] = item["start_state"] or str(transition.get("from", ""))
            item["terminal_state"] = str(transition.get("to", ""))
            if item["terminal_state"] in {"STOPPED", "STOP_FAILED", "FAULT"}:
                item["stop_or_fault"] = item["terminal_state"]
    state = read_state(resolution.active_config_dir)
    if state and state.get("run_id"):
        run_id = str(state["run_id"])
        item = grouped.setdefault(run_id, _empty_run(run_id))
        item["terminal_state"] = str(state.get("state", ""))
        item["plan_id"] = str(state.get("plan_id", item["plan_id"]))
        item["dish_id"] = str(state.get("dish_id", item["dish_id"]))
        item["condition"] = str(state.get("condition", item["condition"]))
        item["trigger_source"] = str(state.get("trigger_source", item["trigger_source"]))
        item["validation_status_at_start"] = str(state.get("validation_status_at_start", ""))
    values = [
        item for item in grouped.values()
        if (not dish_id or dish_id.casefold() in item["dish_id"].casefold())
        and (not condition or condition.casefold() in item["condition"].casefold())
    ]
    values.sort(key=lambda item: item["timestamp"], reverse=True)
    return values[:limit]


def export_runs(
    runs: list[dict[str, Any]],
    output: str | Path,
    *,
    format: Literal["json", "csv", "markdown"],
) -> Path:
    path = Path(output).resolve()
    if format == "json":
        text = json.dumps(runs, ensure_ascii=False, indent=2) + "\n"
    elif format == "csv":
        output_io = io.StringIO(newline="")
        fields = list(_empty_run("").keys())
        writer = csv.DictWriter(output_io, fieldnames=fields)
        writer.writeheader()
        writer.writerows(runs)
        text = output_io.getvalue()
    else:
        lines = [
            "# Recent Pump Runs",
            "",
            "| Timestamp | Dish | Condition | Run ID | IN | OUT | Terminal | STOP/Fault |",
            "|---|---|---|---|---:|---:|---|---|",
        ]
        for item in runs:
            lines.append(
                f"| {item['timestamp']} | {item['dish_id']} | {item['condition']} | "
                f"`{item['run_id']}` | {item['in_flow_ml_min']} | {item['out_flow_ml_min']} | "
                f"{item['terminal_state']} | {item['stop_or_fault']} |"
            )
        text = "\n".join(lines) + "\n"
    _atomic_text(path, text)
    return path


def _read_csv_rows(root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not root.exists():
        return rows
    for path in root.glob("a4pump_*.csv"):
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows.extend(dict(row) for row in csv.DictReader(handle))
        except (OSError, csv.Error, UnicodeError):
            continue
    return rows


def _read_transitions(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        result.append(value)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return result


def _empty_run(run_id: str) -> dict[str, Any]:
    return {
        "timestamp": "",
        "dish_id": "",
        "condition": "",
        "trigger_source": "",
        "plan_id": "",
        "run_id": run_id,
        "in_flow_ml_min": "",
        "out_flow_ml_min": "",
        "duration_s": "",
        "start_state": "",
        "terminal_state": "",
        "stop_or_fault": "",
        "validation_status_at_start": "",
    }


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
