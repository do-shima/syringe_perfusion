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
from .coordinator import OperationCoordinator, system_boot_marker, token_from_state
from .operations import start_armed_pair, validate_armed_plan
from .port_scan import scan_serial_ports
from .perfusion_state import (
    append_protocol_log,
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
    from .validation_store import ValidationStore

    validation_at_schedule = ValidationStore(resolution).status(data=_data)["status"]
    root = resolution.active_config_dir
    coordinator = OperationCoordinator(resolution)
    token, pending = coordinator.reserve_pending(
        delay_s=delay_s,
        metadata={
            "dish_id": dish_id,
            "condition": condition,
            "trigger_source": trigger_source,
            "validation_status_at_start": validation_at_schedule,
        },
    )
    command = build_worker_command(root, token.run_id)
    append_protocol_log(root, {"event": "scheduled", **pending, "worker_command": command})
    if spawn:
        paths = runtime_paths(root)
        paths.root.mkdir(parents=True, exist_ok=True)
        output = paths.log.open("a", encoding="utf-8", newline="\n")
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
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
            except Exception as exc:
                coordinator.rollback_pending(token, str(exc))
                raise
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
    if int(pending.get("boot_marker", -1)) != system_boot_marker():
        coordinator = OperationCoordinator(resolution, pump_factory=pump_factory)
        state = read_state(root) or {}
        if state.get("run_id") == run_id and state.get("state") == "PENDING":
            coordinator.rollback_pending(token_from_state(state), "stale pending run from a previous boot")
        raise ValueError("scheduled run is stale from a previous boot")
    state = read_state(root)
    if (
        not state
        or state.get("state") != "PENDING"
        or state.get("run_id") != run_id
        or state.get("operation_id") != pending.get("operation_id")
    ):
        raise ValueError("scheduled run state is stale")
    token = token_from_state(state)
    coordinator = OperationCoordinator(resolution, pump_factory=pump_factory)
    delay_s = float(pending.get("delay_s", 0))
    event = wait_event or Event()
    result = coordinator.wait(
        token,
        delay_s,
        allowed_states={"PENDING"},
        event=event,
    )
    if result != "completed":
        append_protocol_log(
            root,
            {"event": "scheduled_exit", "run_id": run_id, "reason": result},
        )
        return {"run_id": run_id, "state": "CANCELLED" if result == "cancelled" else "STALE"}
    coordinator.claim_pending(token)
    return start_armed_pair(
        resolution,
        run_id=run_id,
        reserved_token=token,
        dish_id=str(pending.get("dish_id", "")),
        condition=str(pending.get("condition", "")),
        trigger_source=str(pending.get("trigger_source", "CLI")),
        scanner=scanner,
        pump_factory=pump_factory,
        wait_event=event,
    )
