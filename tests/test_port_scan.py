from __future__ import annotations

import pytest

from syringe_perfusion.port_scan import (
    merge_port_devices,
    normalize_port,
    require_distinct_ports,
    scan_serial_ports,
    verify_port_identity,
)


class Port:
    device = "COM10"
    description = "USB UART"
    hwid = "USB VID:PID"
    manufacturer = "Vendor"
    product = "Adapter"
    serial_number = "ABC"
    vid = 0x1234
    pid = 0x5678
    location = "1-2"


def test_metadata_normalization_and_natural_sort() -> None:
    normalized = normalize_port(Port())
    assert normalized["device"] == "COM10"
    assert normalized["manufacturer"] == "Vendor"
    assert normalized["vid"] == 0x1234
    ports = scan_serial_ports(lambda: [
        {"device": "COM10", "description": "", "hwid": ""},
        {"device": "COM2", "description": "", "hwid": ""},
    ])
    assert [port["device"] for port in ports] == ["COM2", "COM10"]


def test_detected_saved_current_union_keeps_undetected_without_assignment() -> None:
    values = merge_port_devices(
        [{"device": "COM10"}, {"device": "COM2"}],
        ["COM7"],
        ["COM3", "COM7"],
    )
    assert values == ["COM2", "COM3", "COM7", "COM10"]
    assert merge_port_devices([], [], []) == []


def test_duplicate_ports_rejected() -> None:
    with pytest.raises(ValueError, match="different"):
        require_distinct_ports("COM_A", "com_a", True)


def test_hwid_match_mismatch_and_missing() -> None:
    current = [{"device": "COM_A", "hwid": "HW-1"}]
    assert verify_port_identity("COM_A", {"hwid": "HW-1"}, current)["hwid"] == "HW-1"
    with pytest.raises(ValueError, match="identity mismatch"):
        verify_port_identity("COM_A", {"hwid": "OTHER"}, current)
    assert verify_port_identity("COM_A", {"hwid": ""}, current)["device"] == "COM_A"
    assert verify_port_identity("COM_A", {"hwid": "HW-1"}, [{"device": "COM_A", "hwid": ""}])
    with pytest.raises(ValueError, match="not detected"):
        verify_port_identity("COM_B", None, current)
