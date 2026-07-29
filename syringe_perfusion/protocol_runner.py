from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from typing import Any, Callable

from .config import ConfigResolution, resolve_config
from .operations import start_armed_pair, validate_armed_plan
from .port_scan import scan_serial_ports
from .perfusion_state import (
    append_protocol_log,
    exclusive_run_lock,
    new_run_id,
    now_iso,
    read_pending,
    read_state,
    runtime_paths,
    write_pending,
    write_state,
)


def build_worker_command(config_dir: str | Path, run_id: str) -> list[str]:
    root = str(Path(config_dir).resolve())
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), "--config-dir", root, "run-scheduled", "--run-id", run_id]
    return [sys.executable, "-m", "syringe_perfusion.cli", "--config-dir", root, "run-scheduled", "--run-id", run_id]


def schedule_armed(
    config: str | Path | ConfigResolution,
    *,
    delay_s: float,
    dish_id: str = "",
    condition: str = "",
    trigger_source: str = "CLI",
    scanner: Callable[[], list[dict[str, Any]]] = scan_serial_ports,
    spawn: bool = True,
    popen: Callable[..., Any] = subprocess.Popen,
) -> dict[str, Any]:
    if delay_s < 0:
        raise ValueError("delay_s must be zero or positive")
    resolution, state, _data, _ports = validate_armed_plan(config, scanner=scanner)
    root = resolution.active_config_dir
    run_id = new_run_id()
    with exclusive_run_lock(root, f"schedule:{run_id}"):
        existing = read_pending(root)
        if existing and existing.get("state") == "PENDING":
            raise RuntimeError("a pending perfusion run already exists")
        pending = {
            "run_id": run_id,
            "plan_id": state["plan_id"],
            "state": "PENDING",
            "created_at": now_iso(),
            "delay_s": float(delay_s),
            "scheduled_for": (datetime.now(timezone.utc) + timedelta(seconds=delay_s)).astimezone().isoformat(timespec="seconds"),
            "dish_id": dish_id,
            "condition": condition,
            "trigger_source": trigger_source,
        }
        write_pending(root, pending)
        write_state(root, {**state, "state": "PENDING", "run_id": run_id, "pending": pending})
    command = build_worker_command(root, run_id)
    append_protocol_log(root, {"event": "scheduled", **pending, "worker_command": command})
    if spawn:
        paths = runtime_paths(root)
        paths.root.mkdir(parents=True, exist_ok=True)
        output = paths.log.open("a", encoding="utf-8", newline="\n")
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                cwd=str(root.parent),
                close_fds=True,
                creationflags=flags,
            )
        finally:
            output.close()
    return {**pending, "worker_command": command}


def run_scheduled(
    config: str | Path | ConfigResolution,
    run_id: str,
    *,
    scanner: Callable[[], list[dict[str, Any]]] = scan_serial_ports,
    pump_factory: Callable[..., Any] | None = None,
    wait_event: Event | None = None,
) -> dict[str, Any]:
    resolution = config if isinstance(config, ConfigResolution) else resolve_config(config)
    root = resolution.active_config_dir
    pending = read_pending(root)
    if not pending or pending.get("run_id") != run_id or pending.get("state") != "PENDING":
        raise ValueError("scheduled run is stale or cancelled")
    delay_s = float(pending.get("delay_s", 0))
    event = wait_event or Event()
    deadline = time.monotonic() + delay_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if event.wait(min(0.25, remaining)):
            raise RuntimeError("scheduled run cancelled")
        current = read_pending(root)
        state = read_state(root)
        if (
            not current
            or current.get("run_id") != run_id
            or current.get("state") != "PENDING"
            or not state
            or state.get("state") != "PENDING"
            or state.get("plan_id") != current.get("plan_id")
        ):
            append_protocol_log(root, {"event": "scheduled_exit", "run_id": run_id, "reason": "cancelled or stale"})
            return {"run_id": run_id, "state": "CANCELLED"}
    return start_armed_pair(
        resolution,
        run_id=run_id,
        dish_id=str(pending.get("dish_id", "")),
        condition=str(pending.get("condition", "")),
        trigger_source=str(pending.get("trigger_source", "CLI")),
        scanner=scanner,
        pump_factory=pump_factory,
        wait_event=event,
    )
