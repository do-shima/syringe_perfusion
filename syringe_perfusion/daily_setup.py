from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


IDENTITY_FIELDS = (
    "device",
    "description",
    "hwid",
    "manufacturer",
    "product",
    "serial_number",
    "vid",
    "pid",
    "location",
)
STABLE_IDENTITY_FIELDS = (
    "hwid",
    "vid",
    "pid",
    "product",
    "manufacturer",
    "location",
)


def empty_daily_setup(active_config_dir: str | Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "active_config_dir": str(Path(active_config_dir).resolve()),
        "locked": False,
        "assignments": {},
        "last_scan_at": "",
        "last_scan_local_date": "",
        "last_scan_topology_fingerprint": "",
        "reviewed_topology_fingerprint": "",
        "topology_changed": False,
        "confirmed_at": "",
    }


def load_daily_setup(
    ui_preferences: Mapping[str, Any] | None,
    active_config_dir: str | Path,
) -> dict[str, Any]:
    expected = str(Path(active_config_dir).resolve())
    raw = (ui_preferences or {}).get("daily_port_setup")
    if not isinstance(raw, Mapping) or str(raw.get("active_config_dir", "")) != expected:
        return empty_daily_setup(expected)
    record = empty_daily_setup(expected)
    record.update(deepcopy(dict(raw)))
    record["active_config_dir"] = expected
    if not isinstance(record.get("assignments"), dict):
        record["assignments"] = {}
    return record


def identity_snapshot(port: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in IDENTITY_FIELDS:
        value = port.get(field, "")
        result[field] = "" if value is None else value
    result["device"] = str(result["device"]).strip()
    return result


def stable_identity(identity: Mapping[str, Any] | None) -> str:
    value = identity or {}
    serial = str(value.get("serial_number", "")).strip().casefold()
    if serial:
        return f"serial:{serial}"
    parts = []
    for field in STABLE_IDENTITY_FIELDS:
        item = value.get(field, "")
        text = str(item).strip().casefold()
        if text:
            parts.append((field, text))
    if not parts:
        return ""
    return "identity:" + hashlib.sha256(
        json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def identities_match(
    stored: Mapping[str, Any] | None,
    detected: Mapping[str, Any] | None,
) -> bool:
    if not stored or not detected:
        return False
    old_serial = str(stored.get("serial_number", "")).strip().casefold()
    new_serial = str(detected.get("serial_number", "")).strip().casefold()
    if old_serial or new_serial:
        return bool(old_serial and new_serial and old_serial == new_serial)
    old_key = stable_identity(stored)
    new_key = stable_identity(detected)
    return bool(old_key and new_key and old_key == new_key)


def topology_fingerprint(ports: Iterable[Mapping[str, Any]]) -> str:
    topology = []
    for port in ports:
        snapshot = identity_snapshot(port)
        topology.append(
            {
                "device": snapshot["device"].casefold(),
                "stable_identity": stable_identity(snapshot),
                "hwid": str(snapshot.get("hwid", "")).strip().casefold(),
            }
        )
    topology.sort(key=lambda item: (item["device"], item["stable_identity"], item["hwid"]))
    return hashlib.sha256(
        json.dumps(topology, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def record_successful_scan(
    record: Mapping[str, Any],
    ports: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _local_now(now)
    updated = deepcopy(dict(record))
    previous = str(updated.get("last_scan_topology_fingerprint", ""))
    fingerprint = topology_fingerprint(ports)
    updated["last_scan_at"] = current.isoformat(timespec="seconds")
    updated["last_scan_local_date"] = current.date().isoformat()
    updated["last_scan_topology_fingerprint"] = fingerprint
    updated["topology_changed"] = bool(
        updated.get("topology_changed", False)
        or (previous and previous != fingerprint)
    )
    return updated


def confirm_assignments(
    record: Mapping[str, Any],
    config_data: Mapping[str, Any],
    ports: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    port_list = [identity_snapshot(port) for port in ports]
    by_device = {str(port["device"]).casefold(): port for port in port_list}
    pumps = config_data.get("pumps")
    if not isinstance(pumps, Mapping):
        raise ValueError("pump configuration is missing")
    roles = ["IN"]
    out = pumps.get("OUT") if isinstance(pumps.get("OUT"), Mapping) else {}
    if bool(out.get("enabled", False)):
        roles.append("OUT")
    devices: list[str] = []
    assignments: dict[str, Any] = {}
    for role in roles:
        pump = pumps.get(role)
        if not isinstance(pump, Mapping):
            raise ValueError(f"{role} pump configuration is missing")
        device = str(pump.get("port", "")).strip()
        if not device:
            raise ValueError(f"{role} port is required")
        if device.casefold() in {item.casefold() for item in devices}:
            raise ValueError("IN and enabled OUT must use different serial ports")
        detected = by_device.get(device.casefold())
        if detected is None:
            raise ValueError(f"{role} saved port is not detected: {device}")
        identity_key = stable_identity(detected)
        if not identity_key:
            raise ValueError(f"{role} adapter has no stable identity metadata")
        assignments[role] = {
            "port": device,
            "identity": detected,
            "stable_identity": identity_key,
        }
        devices.append(device)
    current = _local_now(now)
    updated = deepcopy(dict(record))
    updated.update(
        {
            "locked": True,
            "assignments": assignments,
            "confirmed_at": current.isoformat(timespec="seconds"),
            "reviewed_topology_fingerprint": topology_fingerprint(port_list),
            "topology_changed": False,
        }
    )
    if not updated.get("last_scan_at"):
        updated = record_successful_scan(updated, port_list, now=current)
    return updated


def unlock_assignments(record: Mapping[str, Any]) -> dict[str, Any]:
    updated = deepcopy(dict(record))
    updated["locked"] = False
    return updated


def evaluate_daily_setup(
    record: Mapping[str, Any],
    config_data: Mapping[str, Any],
    ports: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _local_now(now)
    port_list = [identity_snapshot(port) for port in ports]
    by_device = {str(port["device"]).casefold(): port for port in port_list}
    assignments = record.get("assignments") if isinstance(record.get("assignments"), Mapping) else {}
    pumps = config_data.get("pumps") if isinstance(config_data.get("pumps"), Mapping) else {}
    scanned_today = str(record.get("last_scan_local_date", "")) == current.date().isoformat()
    current_topology = topology_fingerprint(port_list)
    scan_topology_current = str(record.get("last_scan_topology_fingerprint", "")) == current_topology
    topology_reviewed = str(record.get("reviewed_topology_fingerprint", "")) == current_topology
    findings: list[dict[str, str]] = []
    if not scanned_today:
        findings.append({"level": "BLOCK", "code": "DAILY_SCAN_REQUIRED"})
    if not scan_topology_current or bool(record.get("topology_changed", False)):
        findings.append({"level": "BLOCK", "code": "USB_TOPOLOGY_CHANGED"})
    if not topology_reviewed:
        findings.append({"level": "BLOCK", "code": "TOPOLOGY_REVIEW_REQUIRED"})
    if not bool(record.get("locked", False)):
        findings.append({"level": "BLOCK", "code": "ASSIGNMENTS_UNLOCKED"})

    roles = ["IN"]
    out_cfg = pumps.get("OUT") if isinstance(pumps.get("OUT"), Mapping) else {}
    if bool(out_cfg.get("enabled", False)):
        roles.append("OUT")
    role_status: dict[str, Any] = {}
    configured_devices: list[str] = []
    for role in roles:
        cfg = pumps.get(role) if isinstance(pumps.get(role), Mapping) else {}
        device = str(cfg.get("port", "")).strip()
        configured_devices.append(device.casefold())
        detected = by_device.get(device.casefold()) if device else None
        assignment = assignments.get(role) if isinstance(assignments.get(role), Mapping) else {}
        stored_identity = assignment.get("identity") if isinstance(assignment.get("identity"), Mapping) else {}
        probable = [
            port for port in port_list
            if port["device"].casefold() != device.casefold()
            and identities_match(stored_identity, port)
        ]
        identity_conflict = bool(detected and stored_identity and not identities_match(stored_identity, detected))
        confirmed_port_matches = str(assignment.get("port", "")).casefold() == device.casefold()
        role_status[role] = {
            "port": device,
            "detected": detected is not None,
            "identity": detected or stored_identity,
            "confirmed": bool(assignment) and confirmed_port_matches,
            "identity_conflict": identity_conflict,
            "probable_ports": [str(item["device"]) for item in probable],
        }
        if not device:
            findings.append({"level": "BLOCK", "code": f"{role}_PORT_MISSING"})
        elif detected is None:
            findings.append(
                {
                    "level": "BLOCK",
                    "code": f"{role}_PORT_NOT_DETECTED",
                    "probable_port": str(probable[0]["device"]) if len(probable) == 1 else "",
                }
            )
        if assignment and not confirmed_port_matches:
            findings.append({"level": "BLOCK", "code": f"{role}_ASSIGNMENT_CHANGED"})
        if identity_conflict:
            findings.append({"level": "BLOCK", "code": f"{role}_IDENTITY_CONFLICT"})
        if not assignment:
            findings.append({"level": "BLOCK", "code": f"{role}_NOT_CONFIRMED"})
    if len([device for device in configured_devices if device]) != len(
        {device for device in configured_devices if device}
    ):
        findings.append({"level": "BLOCK", "code": "DUPLICATE_PORT"})

    return {
        "ready": not findings,
        "scanned_today": scanned_today,
        "scan_topology_current": scan_topology_current,
        "topology_reviewed": topology_reviewed,
        "locked": bool(record.get("locked", False)),
        "last_scan_at": str(record.get("last_scan_at", "")),
        "topology_fingerprint": current_topology,
        "roles": role_status,
        "findings": findings,
    }


def _local_now(value: datetime | None) -> datetime:
    current = value or datetime.now().astimezone()
    if current.tzinfo is None:
        return current.astimezone()
    return current.astimezone()
