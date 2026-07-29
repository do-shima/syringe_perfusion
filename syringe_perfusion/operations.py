from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from typing import Any, Callable

from .a4 import A4Pump, pump_from_config
from .config import ConfigResolution, load_config, resolve_config
from .flow_control import PerfusionSetpoint
from .logger import log_command
from .perfusion_state import (
    append_protocol_log,
    cancel_pending as cancel_pending_state,
    config_fingerprint,
    exclusive_run_lock,
    now_iso,
    read_pending,
    read_state,
    write_pending,
    write_state,
)
from .port_scan import require_distinct_ports, scan_serial_ports, verify_port_identity
from .profiles import calculate_profile


ACTION_METHODS = {
    "start-forward": "start_forward",
    "start-reverse": "start_reverse",
    "manual-forward": "manual_forward",
    "manual-reverse": "manual_reverse",
    "stop": "stop",
    "save": "save",
}
PumpFactory = Callable[[str, dict[str, Any]], A4Pump]
Scanner = Callable[[], list[dict[str, Any]]]


def _factory(dry_run: bool) -> PumpFactory:
    return lambda key, config: pump_from_config(key, config, dry_run=dry_run)


def program_pair(
    config: str | Path | ConfigResolution,
    setpoint: PerfusionSetpoint,
    *,
    dry_run: bool = False,
    dish_id: str = "",
    condition: str = "",
    trigger_source: str = "GUI",
    scanner: Scanner = scan_serial_ports,
    pump_factory: PumpFactory | None = None,
) -> dict[str, Any]:
    resolution = config if isinstance(config, ConfigResolution) else resolve_config(config)
    root = resolution.active_config_dir
    data = load_config(resolution)
    in_cfg, out_cfg = _validate_pair_config(data)
    ports = scanner()
    if not dry_run:
        in_identity = verify_port_identity(str(in_cfg["port"]), None, ports)
        out_identity = verify_port_identity(str(out_cfg["port"]), None, ports)
    else:
        by_device = {str(port.get("device", "")).casefold(): port for port in ports}
        in_identity = by_device.get(str(in_cfg["port"]).casefold(), {})
        out_identity = by_device.get(str(out_cfg["port"]).casefold(), {})

    plan_id = str(uuid.uuid4())
    plan = _build_plan(
        resolution,
        data,
        setpoint,
        plan_id,
        in_identity,
        out_identity,
        dish_id=dish_id,
        condition=condition,
        trigger_source=trigger_source,
    )
    write_state(
        root,
        {
            "state": "PROGRAMMING",
            "plan_id": plan_id,
            "started_at": now_iso(),
            "plan": plan,
        },
    )
    append_protocol_log(root, {"event": "state_transition", "from": "DIRTY", "to": "PROGRAMMING", "plan_id": plan_id})
    factory = pump_factory or _factory(dry_run)
    results: dict[str, list[dict[str, Any]]] = {}
    try:
        pre_stop = _stop_configured(data, dry_run=dry_run, pump_factory=factory)
        if any(not item.get("ok") for item in pre_stop):
            raise RuntimeError("pre-program STOP failed; programming was not attempted")
        results["OUT"] = factory("OUT", out_cfg).write_settings(
            setpoint.out_setpoint.programmed_speed_mm_min,
            setpoint.programmed_duration_s,
            save=True,
        )
        _log_program_results(root, plan_id, "OUT", results["OUT"], plan, dish_id, condition, trigger_source)
        results["IN"] = factory("IN", in_cfg).write_settings(
            setpoint.in_setpoint.programmed_speed_mm_min,
            setpoint.programmed_duration_s,
            save=True,
        )
        _log_program_results(root, plan_id, "IN", results["IN"], plan, dish_id, condition, trigger_source)
    except Exception as exc:
        stop_results = _stop_configured(data, dry_run=dry_run, pump_factory=factory)
        fault = {
            "state": "FAULT",
            "plan_id": plan_id,
            "fault": {"operation": "program_pair", "error": str(exc), "at": now_iso()},
            "stop_results": stop_results,
        }
        write_state(root, fault)
        append_protocol_log(root, {"event": "fault", "plan_id": plan_id, **fault["fault"]})
        raise

    if dry_run:
        state_name = "DRY_RUN_PREVIEW"
        plan["dry_run"] = True
        plan["not_read_back"] = True
        armed_at = None
    else:
        state_name = "ARMED"
        plan["dry_run"] = False
        armed_at = now_iso()
        plan["armed_at"] = armed_at
    state = {
        "state": state_name,
        "plan_id": plan_id,
        "armed_at": armed_at,
        "message": "PROGRAMMED — NOT READ BACK" if not dry_run else "DRY-RUN PREVIEW — NOT PROGRAMMED",
        "plan": plan,
        "programming_results": results,
    }
    write_state(root, state)
    append_protocol_log(
        root,
        {"event": "state_transition", "from": "PROGRAMMING", "to": state_name, "plan_id": plan_id},
    )
    return state


def validate_armed_plan(
    config: str | Path | ConfigResolution,
    *,
    allowed_states: set[str] | None = None,
    scanner: Scanner = scan_serial_ports,
) -> tuple[ConfigResolution, dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    resolution = config if isinstance(config, ConfigResolution) else resolve_config(config)
    root = resolution.active_config_dir
    state = read_state(root)
    if state is None:
        raise ValueError("no armed perfusion state exists")
    allowed = allowed_states or {"ARMED"}
    if state.get("state") not in allowed:
        raise ValueError(f"perfusion plan is not startable: state={state.get('state')}")
    plan = state.get("plan")
    if not isinstance(plan, dict) or plan.get("dry_run"):
        raise ValueError("DRY_RUN_PREVIEW cannot be started")
    if plan.get("config_fingerprint") != config_fingerprint(root):
        raise ValueError("Active Config fingerprint does not match the armed plan")
    data = load_config(resolution)
    in_cfg, out_cfg = _validate_pair_config(data)
    for key, cfg in (("IN", in_cfg), ("OUT", out_cfg)):
        planned = plan["pumps"][key]
        if str(cfg.get("port", "")).casefold() != str(planned.get("port", "")).casefold():
            raise ValueError(f"{key} port differs from the armed plan")
    ports = scanner()
    verify_port_identity(str(in_cfg["port"]), plan["pumps"]["IN"].get("hardware_identity"), ports)
    verify_port_identity(str(out_cfg["port"]), plan["pumps"]["OUT"].get("hardware_identity"), ports)
    return resolution, state, data, ports


def start_armed_pair(
    config: str | Path | ConfigResolution,
    *,
    run_id: str | None = None,
    dish_id: str = "",
    condition: str = "",
    trigger_source: str = "CLI",
    scanner: Scanner = scan_serial_ports,
    pump_factory: PumpFactory | None = None,
    wait_event: Event | None = None,
) -> dict[str, Any]:
    allowed = {"PENDING"} if run_id else {"ARMED"}
    resolution, state, data, _ports = validate_armed_plan(config, allowed_states=allowed, scanner=scanner)
    root = resolution.active_config_dir
    plan = state["plan"]
    actual_run_id = run_id or str(uuid.uuid4())
    if run_id:
        pending = read_pending(root)
        if not pending or pending.get("run_id") != run_id or pending.get("state") != "PENDING":
            raise ValueError("scheduled run is no longer pending")
    factory = pump_factory or _factory(False)
    with exclusive_run_lock(root, actual_run_id):
        write_state(
            root,
            {
                **state,
                "state": "STARTING",
                "run_id": actual_run_id,
                "started_at": now_iso(),
                "dish_id": dish_id,
                "condition": condition,
                "trigger_source": trigger_source,
            },
        )
        append_protocol_log(
            root,
            {"event": "state_transition", "from": state["state"], "to": "STARTING", "plan_id": plan["plan_id"], "run_id": actual_run_id},
        )
        results: dict[str, Any] = {}
        try:
            results["IN"] = factory("IN", data["pumps"]["IN"]).start_forward()
            _log_start_result(root, plan, actual_run_id, "IN", results["IN"], dish_id, condition, trigger_source)
            delay = float(plan["requested"]["in_to_out_delay_s"])
            if not _cancellable_wait(root, delay, plan["plan_id"], actual_run_id, run_id, wait_event):
                _stop_configured(data, dry_run=False, pump_factory=factory)
                stopped = {**state, "state": "STOPPED", "run_id": actual_run_id, "stopped_at": now_iso(), "reason": "cancelled during IN-to-OUT delay"}
                write_state(root, stopped)
                return stopped
            results["OUT"] = factory("OUT", data["pumps"]["OUT"]).start_reverse()
            _log_start_result(root, plan, actual_run_id, "OUT", results["OUT"], dish_id, condition, trigger_source)
        except Exception as exc:
            stop_results = _stop_configured(data, dry_run=False, pump_factory=factory)
            fault = {
                **state,
                "state": "FAULT",
                "run_id": actual_run_id,
                "fault": {"operation": "start_armed_pair", "error": str(exc), "at": now_iso()},
                "stop_results": stop_results,
            }
            write_state(root, fault)
            append_protocol_log(root, {"event": "fault", "plan_id": plan["plan_id"], "run_id": actual_run_id, **fault["fault"]})
            if run_id:
                write_pending(root, {"run_id": run_id, "state": "FAULT", "error": str(exc)})
            raise

        duration = int(plan["programmed_duration_s"])
        expected_end = (datetime.now(timezone.utc) + timedelta(seconds=duration)).astimezone().isoformat(timespec="seconds")
        started = {
            **state,
            "state": "STARTED",
            "run_id": actual_run_id,
            "actual_started_at": now_iso(),
            "expected_end": expected_end,
            "start_results": results,
            "dish_id": dish_id,
            "condition": condition,
            "trigger_source": trigger_source,
        }
        write_state(root, started)
        if run_id:
            write_pending(root, {"run_id": run_id, "state": "STARTED", "started_at": now_iso()})
        append_protocol_log(
            root,
            {"event": "state_transition", "from": "STARTING", "to": "STARTED", "plan_id": plan["plan_id"], "run_id": actual_run_id, "expected_end": expected_end},
        )
        return started


def stop_all_safe(
    config: str | Path | ConfigResolution,
    *,
    dry_run: bool = False,
    dish_id: str = "",
    condition: str = "",
    trigger_source: str = "CLI",
    pump_factory: PumpFactory | None = None,
) -> dict[str, Any]:
    resolution = config if isinstance(config, ConfigResolution) else resolve_config(config)
    root = resolution.active_config_dir
    cancel_result = cancel_pending_state(root, "STOP ALL")
    data = load_config(resolution)
    factory = pump_factory or _factory(dry_run)
    results = _stop_configured(data, dry_run=dry_run, pump_factory=factory, parallel=True)
    failures = [item for item in results if not item.get("ok")]
    state_name = "FAULT" if failures else "STOPPED"
    existing = read_state(root) or {}
    state = {
        **existing,
        "state": state_name,
        "stopped_at": now_iso(),
        "stop_results": results,
        "pending_cancellation": cancel_result,
        "dish_id": dish_id,
        "condition": condition,
        "trigger_source": trigger_source,
    }
    if failures:
        state["fault"] = {"operation": "stop_all", "error": "one or more STOP commands failed", "at": now_iso()}
    write_state(root, state)
    append_protocol_log(root, {"event": "stop_all", "state": state_name, "results": results})
    return state


def get_arm_status(config: str | Path | ConfigResolution) -> dict[str, Any]:
    resolution = config if isinstance(config, ConfigResolution) else resolve_config(config)
    state = read_state(resolution.active_config_dir) or {"state": "MISSING"}
    pending = read_pending(resolution.active_config_dir)
    result = {**state, "active_config_dir": str(resolution.active_config_dir), "pending": pending}
    expected = state.get("expected_end")
    if state.get("state") == "STARTED" and isinstance(expected, str):
        try:
            if datetime.fromisoformat(expected) <= datetime.now(timezone.utc).astimezone():
                result["state"] = "COMPLETED_ESTIMATED"
        except ValueError:
            pass
    return result


def cancel_pending(config: str | Path | ConfigResolution, reason: str = "cancel-pending") -> dict[str, Any]:
    resolution = config if isinstance(config, ConfigResolution) else resolve_config(config)
    result = cancel_pending_state(resolution.active_config_dir, reason)
    state = read_state(resolution.active_config_dir)
    if state and state.get("state") == "PENDING":
        write_state(
            resolution.active_config_dir,
            {**state, "state": "STOPPED", "stopped_at": now_iso(), "reason": reason},
        )
    append_protocol_log(resolution.active_config_dir, {"event": "cancel_pending", "result": result})
    return result


def _build_plan(
    resolution: ConfigResolution,
    data: dict[str, Any],
    setpoint: PerfusionSetpoint,
    plan_id: str,
    in_identity: dict[str, Any],
    out_identity: dict[str, Any],
    **metadata: Any,
) -> dict[str, Any]:
    requested = {
        "mode": setpoint.mode,
        "in_flow_ml_min": setpoint.requested_in_flow_ml_min,
        "out_flow_ml_min": setpoint.requested_out_flow_ml_min,
        "target_in_volume_ml": setpoint.target_in_volume_ml,
        "duration_s": setpoint.requested_duration_s,
        "out_ratio_locked": setpoint.out_ratio_locked,
        "out_in_ratio": setpoint.out_in_ratio,
        "start_delay_s": setpoint.requested_start_delay_s,
        "in_to_out_delay_s": setpoint.in_to_out_delay_s,
    }
    pumps: dict[str, Any] = {}
    for key, calculated, identity in (
        ("IN", setpoint.in_setpoint, in_identity),
        ("OUT", setpoint.out_setpoint, out_identity),
    ):
        cfg = data["pumps"][key]
        pumps[key] = {
            "enabled": bool(cfg.get("enabled", True)),
            "port": str(cfg.get("port", "")),
            "baudrate": int(cfg.get("baudrate", 9600)),
            "terminator": str(cfg.get("terminator", "\\r\\n")),
            "timeout": float(cfg.get("timeout", 1.0)),
            "hardware_identity": identity,
            "syringe_key": calculated.syringe_key,
            "calibrated_ul_per_mm": calculated.ul_per_mm,
            "direction": calculated.direction,
            "requested_flow_ml_min": calculated.requested_flow_ml_min,
            "programmed_speed_mm_min": calculated.programmed_speed_mm_min,
            "estimated_actual_flow_ml_min": calculated.estimated_actual_flow_ml_min,
            "expected_volume_ml": calculated.expected_volume_ml,
            "flow_difference_ml_min": calculated.flow_difference_ml_min,
            "uart_commands": calculated.uart_commands,
        }
    return {
        "schema_version": 1,
        "plan_id": plan_id,
        "created_at": now_iso(),
        "active_config_dir": str(resolution.active_config_dir),
        "source": resolution.source,
        "config_fingerprint": config_fingerprint(resolution.active_config_dir),
        "requested": requested,
        "programmed_duration_s": setpoint.programmed_duration_s,
        "pumps": pumps,
        "warning": setpoint.warning,
        "not_read_back": True,
        **metadata,
    }


def _validate_pair_config(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        in_cfg = data["pumps"]["IN"]
        out_cfg = data["pumps"]["OUT"]
    except KeyError as exc:
        raise ValueError("both IN and OUT pump configurations are required") from exc
    if not in_cfg.get("enabled", True):
        raise ValueError("IN pump is disabled")
    if not out_cfg.get("enabled", False):
        raise ValueError("OUT pump must be enabled for paired perfusion")
    require_distinct_ports(str(in_cfg.get("port", "")), str(out_cfg.get("port", "")), True)
    return in_cfg, out_cfg


def _stop_configured(
    data: dict[str, Any],
    *,
    dry_run: bool,
    pump_factory: PumpFactory,
    parallel: bool = False,
) -> list[dict[str, Any]]:
    targets: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for key, cfg in data.get("pumps", {}).items():
        if not cfg.get("enabled", True):
            continue
        port = str(cfg.get("port", "")).strip()
        identity = port.casefold() or f"blank:{key}"
        if identity in seen:
            continue
        seen.add(identity)
        targets.append((key, cfg))

    def stop_one(key: str, cfg: dict[str, Any]) -> dict[str, Any]:
        try:
            result = pump_factory(key, cfg).stop()
            return {"pump": key, "port": cfg.get("port", ""), "ok": True, "result": result}
        except Exception as exc:
            return {"pump": key, "port": cfg.get("port", ""), "ok": False, "error": str(exc)}

    if parallel and len(targets) > 1:
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=len(targets), thread_name_prefix="a4-stop") as executor:
            futures = {executor.submit(stop_one, key, cfg): key for key, cfg in targets}
            for future in as_completed(futures):
                results.append(future.result())
        return sorted(results, key=lambda item: item["pump"])
    return [stop_one(key, cfg) for key, cfg in targets]


def _cancellable_wait(
    config_dir: Path,
    seconds: float,
    plan_id: str,
    actual_run_id: str,
    scheduled_run_id: str | None,
    event: Event | None,
) -> bool:
    waiter = event or Event()
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        if waiter.wait(min(0.25, remaining)):
            return False
        state = read_state(config_dir)
        if not state or state.get("plan_id") != plan_id or state.get("state") != "STARTING":
            return False
        if scheduled_run_id:
            pending = read_pending(config_dir)
            if not pending or pending.get("run_id") != scheduled_run_id or pending.get("state") != "PENDING":
                return False


def _log_program_results(
    root: Path,
    plan_id: str,
    pump: str,
    results: list[dict[str, Any]],
    plan: dict[str, Any],
    dish_id: str,
    condition: str,
    trigger_source: str,
) -> None:
    details = plan["pumps"][pump]
    for result in results:
        log_command(
            result=result,
            action="program-armed",
            dish_id=dish_id,
            condition=condition,
            trigger_source=trigger_source,
            plan_id=plan_id,
            perfusion_state="PROGRAMMING",
            syringe=details["syringe_key"],
            speed_mm_min=details["programmed_speed_mm_min"],
            duration_s=plan["programmed_duration_s"],
            estimated_volume_ul=details["expected_volume_ml"] * 1000,
            requested_flow_ml_min=details["requested_flow_ml_min"],
            estimated_actual_flow_ml_min=details["estimated_actual_flow_ml_min"],
            in_to_out_delay_s=plan["requested"]["in_to_out_delay_s"],
            note=f"plan_id={plan_id}; PROGRAMMED — NOT READ BACK",
            mode="armed_perfusion",
        )
        append_protocol_log(
            root,
            {"event": "program_command", "plan_id": plan_id, "pump": pump, "command": result.get("command"), "result": result},
        )


def _log_start_result(
    root: Path,
    plan: dict[str, Any],
    run_id: str,
    pump: str,
    result: dict[str, Any],
    dish_id: str,
    condition: str,
    trigger_source: str,
) -> None:
    details = plan["pumps"][pump]
    log_command(
        result=result,
        action=f"start-{details['direction']}",
        dish_id=dish_id,
        condition=condition,
        trigger_source=trigger_source,
        plan_id=plan["plan_id"],
        run_id=run_id,
        perfusion_state="STARTING",
        syringe=details["syringe_key"],
        speed_mm_min=details["programmed_speed_mm_min"],
        duration_s=plan["programmed_duration_s"],
        estimated_volume_ul=details["expected_volume_ml"] * 1000,
        requested_flow_ml_min=details["requested_flow_ml_min"],
        estimated_actual_flow_ml_min=details["estimated_actual_flow_ml_min"],
        in_to_out_delay_s=plan["requested"]["in_to_out_delay_s"],
        note=f"plan_id={plan['plan_id']}; run_id={run_id}",
        mode="armed_perfusion",
    )
    append_protocol_log(root, {"event": "start_command", "plan_id": plan["plan_id"], "run_id": run_id, "pump": pump, "result": result})


# Legacy service functions retained here so GUI and CLI share one application layer.
def send_action(
    data: dict[str, Any],
    pump_key: str,
    action: str,
    *,
    dry_run: bool = False,
    dish_id: str = "",
    condition: str = "",
    trigger_source: str = "CLI",
    profile_key: str = "",
    profile_calc: dict[str, Any] | None = None,
    mode: str = "",
    jog_duration_ms: int | None = None,
) -> dict[str, Any]:
    pump = make_pump(data, pump_key, dry_run=dry_run)
    result = call_action(pump, action)
    calc = profile_calc or {}
    log_command(
        result=result,
        action=action,
        dish_id=dish_id,
        condition=condition,
        trigger_source=trigger_source,
        profile=profile_key,
        syringe=calc.get("syringe", ""),
        speed_mm_min=calc.get("speed_mm_min"),
        duration_s=calc.get("duration_s"),
        target_volume_ul=calc.get("target_volume_ul"),
        estimated_volume_ul=calc.get("estimated_volume_ul"),
        note=calc.get("note", ""),
        mode=mode,
        jog_duration_ms=jog_duration_ms,
    )
    return result


def jog_pump(data: dict[str, Any], pump_key: str, direction: str, duration_ms: int, **metadata: Any) -> list[dict[str, Any]]:
    if duration_ms < 50 or duration_ms > 10000:
        raise ValueError("duration_ms must be between 50 and 10000")
    if direction not in {"forward", "reverse"}:
        raise ValueError("direction must be forward or reverse")
    dry_run = bool(metadata.pop("dry_run", False))
    pump = make_pump(data, pump_key, dry_run=dry_run)
    results = (pump.jog_forward if direction == "forward" else pump.jog_reverse)(duration_ms)
    for result, action, mode in zip(results, [f"manual-{direction}", "stop"], ["jog_start", "jog_stop"]):
        log_command(result=result, action=action, mode=mode, jog_duration_ms=duration_ms, **metadata)
    return results


def write_settings(
    data: dict[str, Any],
    pump_key: str,
    speed_mm_min: float,
    duration_s: float,
    *,
    save: bool = True,
    dry_run: bool = False,
    dish_id: str = "",
    condition: str = "",
    trigger_source: str = "CLI",
    profile_key: str = "",
    mode: str = "write_settings",
) -> list[dict[str, Any]]:
    results = make_pump(data, pump_key, dry_run=dry_run).write_settings(speed_mm_min, duration_s, save=save)
    for result in results:
        log_command(
            result=result, action="write-settings", dish_id=dish_id, condition=condition,
            trigger_source=trigger_source, profile=profile_key, speed_mm_min=speed_mm_min,
            duration_s=duration_s, mode=mode,
        )
    return results


def write_profile(
    data: dict[str, Any], pump_key: str, profile_key: str, *, save: bool = True,
    start_after_write: bool = False, dry_run: bool = False, dish_id: str = "",
    condition: str = "", trigger_source: str = "CLI",
) -> list[dict[str, Any]]:
    calc = profile_log_info(data, profile_key)
    if calc.get("speed_mm_min") is None or calc.get("duration_s") is None:
        raise ValueError(f"profile {profile_key} does not provide speed_mm_min and duration_s")
    results = write_settings(
        data, pump_key, float(calc["speed_mm_min"]), float(calc["duration_s"]), save=save,
        dry_run=dry_run, dish_id=dish_id, condition=condition, trigger_source=trigger_source,
        profile_key=profile_key, mode="write_profile",
    )
    if start_after_write:
        action = "start-reverse" if data["profiles"][profile_key].get("direction", "forward") == "reverse" else "start-forward"
        results.append(send_action(
            data, pump_key, action, dry_run=dry_run, dish_id=dish_id, condition=condition,
            trigger_source=trigger_source, profile_key=profile_key, profile_calc=calc,
            mode="write_profile_start",
        ))
    return results


def run_profile(
    data: dict[str, Any], pump_key: str, profile_key: str, *, dry_run: bool = False,
    dish_id: str = "", condition: str = "", trigger_source: str = "CLI",
) -> dict[str, Any]:
    info = profile_log_info(data, profile_key)
    action = "start-reverse" if data["profiles"][profile_key].get("direction", "forward") == "reverse" else "start-forward"
    return send_action(
        data, pump_key, action, dry_run=dry_run, dish_id=dish_id, condition=condition,
        trigger_source=trigger_source, profile_key=profile_key, profile_calc=info,
    )


def pushpull(
    data: dict[str, Any], *, in_pump: str, out_pump: str, profile_in: str,
    profile_out: str, out_delay: float, safety_stop_after: float | None = None,
    dry_run: bool = False, dish_id: str = "", condition: str = "",
    trigger_source: str = "CLI", wait_event: Event | None = None,
) -> list[dict[str, Any]]:
    if out_delay < 0:
        raise ValueError("out_delay must be zero or positive")
    ensure_pump_enabled(data, in_pump)
    ensure_pump_enabled(data, out_pump)
    waiter = wait_event or Event()
    results = [run_profile(data, in_pump, profile_in, dry_run=dry_run, dish_id=dish_id, condition=condition, trigger_source=trigger_source)]
    if out_delay and waiter.wait(out_delay):
        results.extend(stop_all(data, dry_run=dry_run, dish_id=dish_id, condition=condition, trigger_source=trigger_source, note="cancelled-out-delay"))
        return results
    results.append(run_profile(data, out_pump, profile_out, dry_run=dry_run, dish_id=dish_id, condition=condition, trigger_source=trigger_source))
    if safety_stop_after is not None:
        if safety_stop_after <= 0:
            raise ValueError("safety_stop_after must be positive")
        waiter.wait(safety_stop_after)
        results.extend(stop_all(data, dry_run=dry_run, dish_id=dish_id, condition=condition, trigger_source=trigger_source, note="safety-stop-after"))
    return results


def stop_all(
    data: dict[str, Any], *, dry_run: bool = False, dish_id: str = "",
    condition: str = "", trigger_source: str = "CLI", note: str = "",
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, cfg in data["pumps"].items():
        if not cfg.get("enabled", True):
            continue
        port = str(cfg.get("port", ""))
        if port and port.casefold() in seen:
            continue
        if port:
            seen.add(port.casefold())
        results.append(send_action(
            data, key, "stop", dry_run=dry_run, dish_id=dish_id, condition=condition,
            trigger_source=trigger_source, profile_calc={"note": note},
        ))
    return results


def profile_log_info(data: dict[str, Any], profile_key: str) -> dict[str, Any]:
    profile = data["profiles"][profile_key]
    syringe_key = profile["syringe"]
    calc = calculate_profile(profile, data["syringes"][syringe_key], syringe_key)
    return {
        "syringe": syringe_key, "speed_mm_min": calc.speed_mm_min, "duration_s": calc.duration_s,
        "target_volume_ul": calc.target_volume_ul, "estimated_volume_ul": calc.estimated_volume_ul,
        "note": profile.get("note", ""),
    }


def make_pump(data: dict[str, Any], pump_key: str, *, dry_run: bool = False) -> A4Pump:
    try:
        cfg = data["pumps"][pump_key]
    except KeyError as exc:
        raise KeyError(f"Unknown pump: {pump_key}") from exc
    ensure_pump_enabled(data, pump_key)
    if not str(cfg.get("port", "")).strip():
        raise ValueError(f"Pump {pump_key} is enabled but port is blank")
    return pump_from_config(pump_key, cfg, dry_run=dry_run)


def ensure_pump_enabled(data: dict[str, Any], pump_key: str) -> None:
    try:
        cfg = data["pumps"][pump_key]
    except KeyError as exc:
        raise KeyError(f"Unknown pump: {pump_key}") from exc
    if not cfg.get("enabled", True):
        raise ValueError(f"Pump {pump_key} is disabled")


def call_action(pump: A4Pump, action: str) -> dict[str, Any]:
    try:
        name = ACTION_METHODS[action]
    except KeyError as exc:
        raise ValueError(f"Unknown action: {action}") from exc
    return getattr(pump, name)()
