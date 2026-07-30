from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .app_info import CONTROL_COMPATIBILITY_VERSION, get_build_info
from .config import ConfigResolution, load_config, resolve_config
from .perfusion_state import config_fingerprint, process_exists, read_json, read_state, runtime_paths
from .validation_store import ValidationStore


LEVEL_ORDER = {"BLOCK": 0, "WARN": 1, "INFO": 2, "PASS": 3}


def evaluate_preflight(
    config_data: dict[str, Any],
    *,
    runtime_state: dict[str, Any] | None,
    validation_status: dict[str, Any] | None,
    current_fingerprint: str,
    detected_ports: Iterable[dict[str, Any]] | None = None,
    require_commissioned: bool = False,
    dry_run: bool = False,
    custom_active_config: bool = False,
    slider_range: tuple[float, float] | None = None,
    selected_flow: float | None = None,
    live_lock: dict[str, Any] | None = None,
    live_lock_owner_alive: bool = False,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    pumps = config_data.get("pumps")
    if not isinstance(pumps, dict) or not isinstance(pumps.get("IN"), dict):
        _add(findings, "BLOCK", "MALFORMED_CONFIG", "pumps.IN is missing or malformed")
        return _result(findings, require_commissioned)
    in_cfg = pumps["IN"]
    out_cfg = pumps.get("OUT") if isinstance(pumps.get("OUT"), dict) else {}
    out_enabled = bool(out_cfg.get("enabled", False))
    in_port = str(in_cfg.get("port", "")).strip()
    out_port = str(out_cfg.get("port", "")).strip()
    if not in_port:
        _add(findings, "BLOCK", "IN_PORT_MISSING", "IN port is missing")
    if out_enabled and not out_port:
        _add(findings, "BLOCK", "OUT_PORT_MISSING", "Required OUT port is missing")
    if out_enabled and in_port and in_port.casefold() == out_port.casefold():
        _add(findings, "BLOCK", "DUPLICATE_PORT", "IN and enabled OUT use the same port")
    port_map = {
        str(item.get("device", "")).casefold(): item for item in (detected_ports or [])
    }
    for role, cfg in (("IN", in_cfg), ("OUT", out_cfg)):
        if role == "OUT" and not out_enabled:
            continue
        stored = cfg.get("hardware_identity") or {}
        current = port_map.get(str(cfg.get("port", "")).casefold(), {})
        stored_hwid = str(stored.get("hwid", "")).strip()
        current_hwid = str(current.get("hwid", "")).strip()
        if stored_hwid and current_hwid and stored_hwid != current_hwid:
            _add(findings, "BLOCK", f"{role}_HWID_MISMATCH", f"{role} hardware identity conflicts")
        elif not stored_hwid:
            _add(findings, "WARN", f"{role}_NO_STABLE_ID", f"{role} has no stored stable HWID metadata")
    state = runtime_state or {}
    state_name = str(state.get("state", "MISSING"))
    if state_name in {"FAULT", "STOP_FAILED"}:
        _add(findings, "BLOCK", "UNRESOLVED_FAULT", f"Runtime state is {state_name}")
    if state_name in {"PENDING", "STARTING", "STARTED", "PROGRAMMING", "RECIPE_RUNNING", "STOPPING"}:
        _add(findings, "BLOCK", "UNSAFE_RUNTIME_STATE", f"Runtime state is {state_name}")
    plan = state.get("plan") if isinstance(state.get("plan"), dict) else {}
    if state_name == "ARMED":
        if not plan or plan.get("config_fingerprint") != current_fingerprint:
            _add(findings, "BLOCK", "INVALID_ARMED_PLAN", "ARMED plan is missing or has a config fingerprint mismatch")
        duration = plan.get("programmed_duration_s")
        if duration is None or float(duration) <= 0:
            _add(findings, "BLOCK", "IMPOSSIBLE_DURATION", "ARMED duration is invalid")
    if live_lock:
        pid = int(live_lock.get("pid", 0) or 0)
        if pid and live_lock_owner_alive:
            _add(findings, "BLOCK", "LIVE_RUN_LOCK", f"Run transition lock is owned by live process {pid}")
    validation = validation_status or {}
    commissioned = bool(validation.get("commissioned"))
    record = validation.get("record") if isinstance(validation.get("record"), dict) else {}
    tests = {
        str(item.get("test_id")): item
        for item in record.get("test_results", [])
        if isinstance(item, dict)
    }
    recorded_pumps = record.get("pumps") if isinstance(record.get("pumps"), dict) else {}
    for role, cfg in (("IN", in_cfg), ("OUT", out_cfg)):
        if role == "OUT" and not out_enabled:
            continue
        recorded_identity = (
            recorded_pumps.get(role, {}).get("hardware_identity") or {}
            if isinstance(recorded_pumps.get(role), dict)
            else {}
        )
        detected_identity = port_map.get(str(cfg.get("port", "")).casefold(), {})
        for key in ("serial_number", "hwid"):
            old_value = str(recorded_identity.get(key, "")).strip()
            new_value = str(detected_identity.get(key, "")).strip()
            if old_value and new_value and old_value.casefold() != new_value.casefold():
                _add(
                    findings,
                    "BLOCK",
                    f"{role}_COMMISSIONED_IDENTITY_MISMATCH",
                    f"{role} detected {key} conflicts with commissioned adapter identity",
                )
                break
    failed_safety = [
        test_id for test_id in (
            "direction_in", "direction_out", "stop_in", "stop_out", "stop_both"
        )
        if tests.get(test_id, {}).get("outcome") == "FAILED"
    ]
    if failed_safety:
        _add(
            findings,
            "BLOCK",
            "PHYSICAL_SAFETY_VALIDATION_FAILED",
            "Failed physical safety validation: " + ", ".join(failed_safety),
        )
    if require_commissioned and not commissioned:
        _add(findings, "BLOCK", "COMMISSIONING_REQUIRED", "Current commissioning is required by production policy")
    elif not commissioned:
        _add(findings, "WARN", "COMMISSIONING_INCOMPLETE", validation.get("status", "Physical commissioning is incomplete"))
    if tests.get("direction_in", {}).get("outcome") != "PASS":
        _add(findings, "WARN", "DIRECTION_NOT_VALIDATED", "IN physical direction is not manually validated")
    if tests.get("flow_in", {}).get("outcome") != "PASS":
        _add(findings, "WARN", "FLOW_CALIBRATION_MISSING", "Accepted IN flow calibration evidence is missing")
    if out_enabled and tests.get("flow_out", {}).get("outcome") != "PASS":
        _add(findings, "WARN", "OUT_REVERSE_NOT_MEASURED", "OUT reverse flow has not passed measured validation")
    if out_enabled and tests.get("balance", {}).get("outcome") != "PASS":
        _add(findings, "WARN", "BALANCE_NOT_VALIDATED", "IN/OUT paired balance evidence is missing")
    if tests.get("nis_workstation", {}).get("outcome") != "PASS":
        _add(findings, "WARN", "NIS_NOT_VALIDATED", "NIS/microscope workstation validation is missing")
    for reason in validation.get("stale_reasons", []):
        _add(findings, "WARN", "COMMISSIONING_STALE", str(reason))
    if dry_run:
        _add(findings, "INFO", "DRY_RUN", "DRY-RUN is selected")
    if not out_enabled:
        _add(findings, "INFO", "OUT_DISABLED", "OUT pump is disabled")
    if custom_active_config:
        _add(findings, "INFO", "CUSTOM_CONFIG", "A custom Active Config is selected")
    if slider_range and selected_flow is not None and not slider_range[0] <= selected_flow <= slider_range[1]:
        _add(findings, "INFO", "FLOW_OUTSIDE_SLIDER", "Selected exact flow is outside the visible slider range")
    _add(findings, "INFO", "NO_READBACK", "No pump hardware readback is available")
    if not any(item["level"] == "BLOCK" for item in findings):
        _add(findings, "PASS", "SOFTWARE_PREFLIGHT", "No software BLOCK findings")
    return _result(findings, require_commissioned)


def assess_preflight(
    config: str | Path | ConfigResolution,
    *,
    require_commissioned: bool = False,
    detected_ports: Iterable[dict[str, Any]] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    resolution = config if isinstance(config, ConfigResolution) else resolve_config(config)
    try:
        data = load_config(resolution)
        fingerprint = config_fingerprint(resolution.active_config_dir)
    except Exception as exc:
        return _with_build(
            _result(
                [{"level": "BLOCK", "code": "INVALID_ACTIVE_CONFIG", "message": str(exc)}],
                require_commissioned,
            )
        )
    lock = read_json(runtime_paths(resolution.active_config_dir).run_lock)
    lock_pid = int((lock or {}).get("pid", 0) or 0)
    ports = list(detected_ports or [])
    return _with_build(
        evaluate_preflight(
            data,
            runtime_state=read_state(resolution.active_config_dir),
            validation_status=ValidationStore(resolution).status(
                data=data,
                detected_ports=ports,
            ),
            current_fingerprint=fingerprint,
            detected_ports=ports,
            require_commissioned=require_commissioned,
            dry_run=dry_run,
            custom_active_config=resolution.source not in {"source_repository", "exe_adjacent"},
            live_lock=lock,
            live_lock_owner_alive=bool(lock_pid and process_exists(lock_pid)),
        )
    )


def format_preflight(result: dict[str, Any]) -> str:
    lines = [
        f"preflight: {result['summary']}",
        f"blocks: {result['counts']['BLOCK']}  warnings: {result['counts']['WARN']}",
    ]
    lines.extend(
        f"[{item['level']}] {item['code']}: {item['message']}"
        for item in result["findings"]
    )
    return "\n".join(lines)


def _with_build(result: dict[str, Any]) -> dict[str, Any]:
    build = get_build_info()
    return {
        **result,
        "application": {
            "human_version": build.get("human_version", ""),
            "package_version": build.get("package_version", ""),
            "git_commit_short": build.get("git_commit_short", ""),
            "build_identity_fingerprint": build.get("build_identity_fingerprint", ""),
            "control_compatibility_version": CONTROL_COMPATIBILITY_VERSION,
        },
    }


def _add(findings: list[dict[str, str]], level: str, code: str, message: str) -> None:
    findings.append({"level": level, "code": code, "message": message})


def _result(findings: list[dict[str, str]], strict: bool) -> dict[str, Any]:
    findings.sort(key=lambda item: (LEVEL_ORDER[item["level"]], item["code"]))
    counts = {level: sum(1 for item in findings if item["level"] == level) for level in LEVEL_ORDER}
    return {
        "summary": "BLOCK" if counts["BLOCK"] else "WARN" if counts["WARN"] else "PASS",
        "ready": counts["BLOCK"] == 0,
        "strict_commissioning": strict,
        "counts": counts,
        "findings": findings,
    }
