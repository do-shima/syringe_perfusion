from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Any, Callable, Iterable

from .app_info import CONTROL_COMPATIBILITY_VERSION
from .coordinator import OperationCoordinator
from .flow_control import calibrated_ul_per_mm, quantize_speed, speed_for_flow
from .perfusion_state import config_fingerprint, now_iso


SOFTWARE_CHECK = "SOFTWARE CHECK"
UART_COMPLETED = "UART COMMAND COMPLETED"
MANUAL_CONFIRMATION = "MANUAL PHYSICAL CONFIRMATION"
MEASURED_RESULT = "MEASURED RESULT"
NOT_VALIDATED = "NOT VALIDATED"
STALE = "STALE"
FAILED = "FAILED"

PHYSICAL_EVIDENCE = {MANUAL_CONFIRMATION, MEASURED_RESULT}
PASS_CONFIRMATIONS = {"correct", "stopped", "pass", "confirmed"}
TEST_DEFINITIONS = (
    ("environment", "Environment", SOFTWARE_CHECK),
    ("port_identity_in", "IN adapter identity", MANUAL_CONFIRMATION),
    ("port_identity_out", "OUT adapter identity", MANUAL_CONFIRMATION),
    ("direction_in", "IN forward delivery", MANUAL_CONFIRMATION),
    ("direction_out", "OUT reverse withdrawal", MANUAL_CONFIRMATION),
    ("stop_in", "IN emergency STOP", MANUAL_CONFIRMATION),
    ("stop_out", "OUT emergency STOP", MANUAL_CONFIRMATION),
    ("stop_both", "Paired emergency STOP", MANUAL_CONFIRMATION),
    ("delayed_cancellation", "Delayed-start cancellation rehearsal", SOFTWARE_CHECK),
    ("flow_in", "IN forward flow measurement", MEASURED_RESULT),
    ("flow_out", "OUT reverse flow measurement", MEASURED_RESULT),
    ("balance", "IN/OUT balance", MEASURED_RESULT),
    ("nis_workstation", "NIS/workstation checklist", MANUAL_CONFIRMATION),
)
STANDARD_FLOW_POINTS_ML_MIN = (0.5, 1.0, 2.0, 3.0)


def commissioning_flow_points(
    config_data: dict[str, Any],
    *,
    syringe_key: str,
) -> list[dict[str, Any]]:
    syringe = config_data.get("syringes", {}).get(syringe_key)
    if not isinstance(syringe, dict):
        raise ValueError(f"unknown syringe: {syringe_key}")
    conversion = calibrated_ul_per_mm(syringe)
    result: list[dict[str, Any]] = []
    for flow in STANDARD_FLOW_POINTS_ML_MIN:
        try:
            speed = quantize_speed(speed_for_flow(flow, conversion))
            result.append({"flow_ml_min": flow, "supported": True, "speed_mm_min": speed, "error": ""})
        except ValueError as exc:
            result.append({"flow_ml_min": flow, "supported": False, "speed_mm_min": None, "error": str(exc)})
    return result


def dependency_snapshot(
    config_data: dict[str, Any],
    *,
    config_dir: str,
    application_version: str = "",
    control_compatibility_version: int = CONTROL_COMPATIBILITY_VERSION,
) -> dict[str, Any]:
    pumps = config_data.get("pumps", {})
    selected = _selected_syringes(config_data)
    return {
        "config_fingerprint": config_fingerprint(config_dir),
        "application_version": application_version,
        "control_compatibility_version": int(control_compatibility_version),
        "pumps": {
            role: {
                "port": cfg.get("port", ""),
                "hardware_identity": dict(cfg.get("hardware_identity") or {}),
                "baudrate": cfg.get("baudrate", 9600),
                "terminator": cfg.get("terminator", "\\r\\n"),
                "timeout": cfg.get("timeout", 1.0),
                "direction": "forward" if role == "IN" else "reverse",
                "enabled": bool(cfg.get("enabled", True)),
            }
            for role, cfg in pumps.items()
        },
        "syringes": {
            key: {
                "calibrated_ul_per_mm": value.get("calibrated_ul_per_mm"),
                "calibration_date": value.get("calibration_date", ""),
            }
            for key, value in config_data.get("syringes", {}).items()
            if key in selected
        },
        "selected_syringes": selected,
    }


def staleness_reasons(
    stored: dict[str, Any] | None,
    current: dict[str, Any],
) -> list[str]:
    if not stored:
        return ["no commissioning dependency snapshot"]
    reasons: list[str] = []
    old_pumps = stored.get("pumps", {})
    new_pumps = current.get("pumps", {})
    for role in ("IN", "OUT"):
        old = old_pumps.get(role, {})
        new = new_pumps.get(role, {})
        if role == "OUT" and not old.get("enabled") and not new.get("enabled"):
            continue
        for key, label in (
            ("port", "COM port"),
            ("baudrate", "baudrate"),
            ("terminator", "terminator"),
            ("timeout", "timeout"),
            ("direction", "direction assignment"),
        ):
            if old.get(key) != new.get(key):
                reasons.append(f"{role} {label} changed")
        old_identity = old.get("hardware_identity") or {}
        new_identity = new.get("hardware_identity") or {}
        for key in ("serial_number", "hwid", "vid", "pid", "location"):
            if old_identity.get(key) and new_identity.get(key) and old_identity.get(key) != new_identity.get(key):
                reasons.append(f"{role} hardware identity changed ({key})")
                break
    if stored.get("selected_syringes") != current.get("selected_syringes"):
        reasons.append("selected syringe changed")
    old_syringes = stored.get("syringes", {})
    for key, value in current.get("syringes", {}).items():
        if old_syringes.get(key, {}).get("calibrated_ul_per_mm") != value.get("calibrated_ul_per_mm"):
            reasons.append(f"syringe calibration changed ({key})")
    stored_compatibility = stored.get("control_compatibility_version")
    current_compatibility = current.get("control_compatibility_version")
    if stored_compatibility is None:
        reasons.append("validation predates control compatibility tracking")
    elif stored_compatibility != current_compatibility:
        reasons.append("validation-sensitive control compatibility changed")
    if stored.get("config_fingerprint") != current.get("config_fingerprint") and not reasons:
        reasons.append("relevant config fingerprint changed")
    return _unique(reasons)


def probable_identity_matches(
    stored_identity: dict[str, Any] | None,
    detected_ports: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    stored = stored_identity or {}
    stable_keys = ("serial_number", "hwid")
    matches: list[dict[str, Any]] = []
    for port in detected_ports:
        if any(
            stored.get(key)
            and port.get(key)
            and str(stored[key]).casefold() == str(port[key]).casefold()
            for key in stable_keys
        ):
            matches.append(dict(port))
    return matches


def evaluate_test_result(result: dict[str, Any]) -> dict[str, Any]:
    evidence = str(result.get("evidence_type", SOFTWARE_CHECK))
    uart_ok = bool(result.get("uart_completed"))
    confirmation = str(
        (result.get("operator_confirmation") or {}).get("observation", "")
    ).casefold()
    measurements = result.get("measured_values") or {}
    criteria_met = bool(result.get("criteria_met"))
    if result.get("error"):
        outcome = FAILED
    elif evidence == SOFTWARE_CHECK:
        outcome = "PASS" if bool(result.get("software_pass")) else NOT_VALIDATED
    elif evidence == UART_COMPLETED:
        outcome = UART_COMPLETED if uart_ok else FAILED
    elif evidence == MANUAL_CONFIRMATION:
        outcome = "PASS" if confirmation in PASS_CONFIRMATIONS else FAILED if confirmation in {"incorrect", "no movement", "failed"} else "AWAITING MANUAL CONFIRMATION"
    elif evidence == MEASURED_RESULT:
        outcome = "PASS" if measurements and criteria_met else FAILED if measurements else NOT_VALIDATED
    else:
        outcome = NOT_VALIDATED
    return {**result, "outcome": outcome, "state": outcome}


def make_test_result(
    test_id: str,
    *,
    pump_role: str = "",
    direction: str = "",
    evidence_type: str | None = None,
    commanded_values: dict[str, Any] | None = None,
    measured_values: dict[str, Any] | None = None,
    acceptance_criteria: dict[str, Any] | None = None,
    operator_confirmation: dict[str, Any] | None = None,
    note: str = "",
    run_id: str = "",
    log_references: list[str] | None = None,
    **status: Any,
) -> dict[str, Any]:
    definition = next((item for item in TEST_DEFINITIONS if item[0] == test_id), None)
    if definition is None:
        raise ValueError(f"unknown commissioning test: {test_id}")
    result = {
        "test_id": test_id,
        "display_name": definition[1],
        "evidence_type": evidence_type or definition[2],
        "state": NOT_VALIDATED,
        "started_at": status.pop("started_at", now_iso()),
        "completed_at": status.pop("completed_at", ""),
        "pump_role": pump_role,
        "direction": direction,
        "commanded_values": commanded_values or {},
        "measured_values": measured_values or {},
        "acceptance_criteria": acceptance_criteria or {},
        "outcome": NOT_VALIDATED,
        "operator_confirmation": operator_confirmation or {},
        "note": note,
        "related_run_id": run_id,
        "related_log_references": log_references or [],
        **status,
    }
    return evaluate_test_result(result)


@dataclass
class CommissioningService:
    coordinator: OperationCoordinator
    config_data: dict[str, Any]

    def bounded_direction_check(
        self,
        *,
        role: str,
        direction: str,
        duration_ms: int = 750,
        cancel_event: Event | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if duration_ms < 100 or duration_ms > 5000:
            raise ValueError("commissioning movement must be bounded to 100–5000 ms")
        token = self.coordinator.begin_recipe(
            self.config_data, operation_type="commissioning_direction"
        )
        result: dict[str, Any] | None = None
        try:
            pump = self.coordinator.pump_factory(role, self.config_data["pumps"][role])
            result = self.coordinator.emit_manual(token, role, pump, direction)
            wait_result = self.coordinator.wait(
                token,
                duration_ms / 1000.0,
                allowed_states={"RECIPE_RUNNING"},
                event=cancel_event,
            )
        finally:
            stopped = self.coordinator.emergency_stop(
                dry_run=dry_run,
                metadata={"reason": "bounded commissioning direction check"},
                fallback_data=self.config_data,
            )
        return {
            "run_id": token.run_id,
            "uart_result": result,
            "wait_result": wait_result,
            "stop_state": stopped.get("state"),
            "state": "AWAITING MANUAL CONFIRMATION",
            "message": "PROGRAMMED — NOT READ BACK",
        }

    def cancellation_rehearsal(
        self,
        *,
        delay_s: float,
        cancel_event: Event,
        before_final_check: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        if delay_s < 0 or delay_s > 600:
            raise ValueError("rehearsal delay must be bounded to 0–600 seconds")
        token = self.coordinator.begin_rehearsal(
            self.config_data, delay_s=delay_s
        )
        started = now_iso()
        wait_result = self.coordinator.wait(
            token,
            delay_s,
            allowed_states={"REHEARSAL_PENDING"},
            event=cancel_event,
            before_final_check=before_final_check,
        )
        stopped = self.coordinator.emergency_stop(
            dry_run=True,
            metadata={"reason": "commissioning cancellation rehearsal"},
            fallback_data=self.config_data,
        )
        return {
            "run_id": token.run_id,
            "scheduled_at": started,
            "cancelled_at": now_iso() if wait_result != "completed" else "",
            "wait_result": wait_result,
            "in_start_authorized": False,
            "out_start_authorized": False,
            "final_state": stopped.get("state"),
            "software_pass": wait_result in {"cancelled", "stale"} and stopped.get("state") == "STOPPED",
        }

    def bounded_pair_stop_check(
        self,
        *,
        duration_ms: int = 750,
        cancel_event: Event | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if duration_ms < 100 or duration_ms > 5000:
            raise ValueError("commissioning movement must be bounded to 100–5000 ms")
        token = self.coordinator.begin_recipe(
            self.config_data, operation_type="commissioning_stop_both"
        )
        starts: dict[str, Any] = {}
        try:
            for role, direction in (("IN", "forward"), ("OUT", "reverse")):
                pump = self.coordinator.pump_factory(role, self.config_data["pumps"][role])
                starts[role] = self.coordinator.emit_manual(token, role, pump, direction)
            wait_result = self.coordinator.wait(
                token,
                duration_ms / 1000.0,
                allowed_states={"RECIPE_RUNNING"},
                event=cancel_event,
            )
        finally:
            stopped = self.coordinator.emergency_stop(
                dry_run=dry_run,
                metadata={"reason": "bounded paired commissioning STOP check"},
                fallback_data=self.config_data,
            )
        return {
            "run_id": token.run_id,
            "start_results": starts,
            "wait_result": wait_result,
            "stop_results": stopped.get("stop_results", []),
            "stop_state": stopped.get("state"),
            "state": "AWAITING MANUAL CONFIRMATION",
            "message": "PROGRAMMED — NOT READ BACK",
        }

    def bounded_flow_run(
        self,
        *,
        role: str,
        direction: str,
        speed_mm_min: float,
        duration_s: int,
        cancel_event: Event | None = None,
    ) -> dict[str, Any]:
        if duration_s < 1 or duration_s > 600:
            raise ValueError("commissioning flow run must be bounded to 1–600 seconds")
        speed = quantize_speed(float(speed_mm_min))
        token = self.coordinator.begin_recipe(
            self.config_data, operation_type="commissioning_flow"
        )
        programming: list[dict[str, Any]] = []
        started: dict[str, Any] | None = None
        try:
            pump = self.coordinator.pump_factory(role, self.config_data["pumps"][role])
            programming = pump.write_settings(speed, duration_s, save=False)
            if self.coordinator.token_status(token, {"RECIPE_RUNNING"}) != "valid":
                raise RuntimeError("commissioning flow run cancelled before START")
            started = self.coordinator.emit_start(token, role, pump, direction)
            wait_result = self.coordinator.wait(
                token,
                duration_s,
                allowed_states={"RECIPE_RUNNING"},
                event=cancel_event,
            )
        finally:
            stopped = self.coordinator.emergency_stop(
                metadata={"reason": "bounded commissioning flow run"},
                fallback_data=self.config_data,
            )
        return {
            "run_id": token.run_id,
            "programming_results": programming,
            "start_result": started,
            "wait_result": wait_result,
            "stop_state": stopped.get("state"),
            "stop_results": stopped.get("stop_results", []),
            "state": "AWAITING MEASURED RESULT",
            "message": "PROGRAMMED — NOT READ BACK",
        }


def required_physical_current(
    test_results: Iterable[dict[str, Any]],
    *,
    out_enabled: bool = False,
) -> bool:
    indexed = {str(item.get("test_id")): item for item in test_results}
    required = ["port_identity_in", "direction_in", "stop_in", "delayed_cancellation"]
    if out_enabled:
        required.extend(("port_identity_out", "direction_out", "stop_out", "stop_both"))
    return all(indexed.get(key, {}).get("outcome") == "PASS" for key in required)


def _selected_syringes(data: dict[str, Any]) -> list[str]:
    selected: set[str] = set()
    for profile in data.get("profiles", {}).values():
        key = str(profile.get("syringe", ""))
        if key:
            selected.add(key)
    return sorted(selected)


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
