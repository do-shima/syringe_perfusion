from __future__ import annotations

import re
from typing import Any, Callable, Iterable

from .a4 import list_serial_ports


PORT_FIELDS = (
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


def normalize_port(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        source = value
        getter = source.get
    else:
        getter = lambda name, default=None: getattr(value, name, default)
    normalized: dict[str, Any] = {}
    for field in PORT_FIELDS:
        item = getter(field, None)
        normalized[field] = "" if item is None else item
    normalized["device"] = str(normalized["device"]).strip()
    normalized["description"] = str(normalized["description"])
    normalized["hwid"] = str(normalized["hwid"])
    return normalized


def scan_serial_ports(
    provider: Callable[[], Iterable[Any]] | None = None,
) -> list[dict[str, Any]]:
    raw_ports = provider() if provider is not None else list_serial_ports()
    ports = [normalize_port(port) for port in raw_ports]
    return sorted((port for port in ports if port["device"]), key=lambda port: natural_port_key(port["device"]))


def natural_port_key(value: str) -> tuple[Any, ...]:
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value))


def merge_port_devices(
    detected: Iterable[dict[str, Any] | str],
    saved: Iterable[str],
    current: Iterable[str],
) -> list[str]:
    values: set[str] = set()
    for item in detected:
        device = item.get("device", "") if isinstance(item, dict) else item
        if str(device).strip():
            values.add(str(device).strip())
    for value in (*saved, *current):
        if str(value).strip():
            values.add(str(value).strip())
    return sorted(values, key=natural_port_key)


def port_map(ports: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(port["device"]).casefold(): port for port in ports}


def require_distinct_ports(in_port: str, out_port: str, out_enabled: bool = True) -> None:
    if not in_port.strip():
        raise ValueError("IN port is required")
    if out_enabled and not out_port.strip():
        raise ValueError("OUT port is required")
    if out_enabled and in_port.strip().casefold() == out_port.strip().casefold():
        raise ValueError("IN and OUT must use different serial ports")


def verify_port_identity(
    device: str,
    stored_identity: dict[str, Any] | None,
    current_ports: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    current = port_map(current_ports).get(device.casefold())
    if current is None:
        raise ValueError(f"required serial port is not detected: {device}")
    stored_hwid = str((stored_identity or {}).get("hwid", "")).strip()
    current_hwid = str(current.get("hwid", "")).strip()
    if stored_hwid and current_hwid and stored_hwid != current_hwid:
        raise ValueError(f"serial hardware identity mismatch for {device}")
    return current
