from __future__ import annotations

import threading
from pathlib import Path
from datetime import datetime

import pytest

from gui_app_helper import make_app
from syringe_perfusion.daily_setup import (
    confirm_assignments,
    empty_daily_setup,
    evaluate_daily_setup,
    identities_match,
    record_successful_scan,
    unlock_assignments,
)
from syringe_perfusion.config import REQUIRED_CONFIG_FILES, save_pump_settings
from syringe_perfusion.perfusion_state import read_state, write_state


NOW = datetime.fromisoformat("2026-08-01T09:30:00+09:00")
ROOT = Path(__file__).resolve().parents[1]


def config(*, out_enabled: bool = True) -> dict:
    return {
        "pumps": {
            "IN": {"enabled": True, "port": "COM_IN"},
            "OUT": {"enabled": out_enabled, "port": "COM_OUT"},
        }
    }


def ports() -> list[dict]:
    return [
        {"device": "COM_IN", "serial_number": "SER-IN", "product": "Adapter IN", "hwid": "HW-IN"},
        {"device": "COM_OUT", "serial_number": "SER-OUT", "product": "Adapter OUT", "hwid": "HW-OUT"},
    ]


def ready_record() -> dict:
    record = empty_daily_setup(".")
    record = record_successful_scan(record, ports(), now=NOW)
    return confirm_assignments(record, config(), ports(), now=NOW)


def test_daily_scan_date_topology_and_lock_readiness() -> None:
    record = ready_record()
    assert evaluate_daily_setup(record, config(), ports(), now=NOW)["ready"]
    tomorrow = datetime.fromisoformat("2026-08-02T00:01:00+09:00")
    stale = evaluate_daily_setup(record, config(), ports(), now=tomorrow)
    assert not stale["ready"]
    assert "DAILY_SCAN_REQUIRED" in {item["code"] for item in stale["findings"]}

    changed_ports = [*ports(), {"device": "COM_OTHER", "serial_number": "OTHER"}]
    rescanned = record_successful_scan(record, changed_ports, now=NOW)
    topology = evaluate_daily_setup(rescanned, config(), changed_ports, now=NOW)
    assert not topology["ready"]
    assert "USB_TOPOLOGY_CHANGED" in {item["code"] for item in topology["findings"]}


def test_saved_unavailable_port_and_probable_renumber_are_retained_for_confirmation() -> None:
    record = ready_record()
    renumbered = [
        {"device": "COM_NEW", "serial_number": "SER-IN", "product": "Adapter IN"},
        ports()[1],
    ]
    rescanned = record_successful_scan(record, renumbered, now=NOW)
    status = evaluate_daily_setup(rescanned, config(), renumbered, now=NOW)
    assert status["roles"]["IN"]["port"] == "COM_IN"
    assert status["roles"]["IN"]["probable_ports"] == ["COM_NEW"]
    assert not status["ready"]


def test_identity_conflict_blocks_and_serial_is_authoritative() -> None:
    record = ready_record()
    conflict = [
        {"device": "COM_IN", "serial_number": "DIFFERENT", "product": "Adapter IN"},
        ports()[1],
    ]
    status = evaluate_daily_setup(record_successful_scan(record, conflict, now=NOW), config(), conflict, now=NOW)
    assert status["roles"]["IN"]["identity_conflict"]
    assert "IN_IDENTITY_CONFLICT" in {item["code"] for item in status["findings"]}
    assert not identities_match({"serial_number": "A", "hwid": "same"}, {"serial_number": "B", "hwid": "same"})


def test_unlock_and_duplicate_port_rules() -> None:
    unlocked = unlock_assignments(ready_record())
    assert not evaluate_daily_setup(unlocked, config(), ports(), now=NOW)["ready"]
    duplicate = config()
    duplicate["pumps"]["OUT"]["port"] = "COM_IN"
    with pytest.raises(ValueError, match="different"):
        confirm_assignments(empty_daily_setup("."), duplicate, ports(), now=NOW)


def test_startup_scan_runs_in_background_and_never_opens_serial(monkeypatch) -> None:
    entered = threading.Event()
    release = threading.Event()
    thread_names: list[str] = []
    serial_constructed: list[bool] = []

    def fake_scan(*_args, **_kwargs):
        thread_names.append(threading.current_thread().name)
        entered.set()
        release.wait(1)
        return []

    monkeypatch.setattr("syringe_perfusion.gui.scan_serial_ports", fake_scan)
    monkeypatch.setattr(
        "syringe_perfusion.a4.A4Pump.__init__",
        lambda *_args, **_kwargs: serial_constructed.append(True),
    )
    app = make_app(auto_scan=True)
    try:
        app.update()
        assert entered.wait(1)
        assert thread_names[0] != threading.main_thread().name
        assert serial_constructed == []
    finally:
        release.set()
        app.destroy()


def test_live_gate_blocks_before_daily_scan_but_dry_run_preview_is_available(monkeypatch) -> None:
    app = make_app()
    errors: list[str] = []
    programmed: list[bool] = []
    try:
        monkeypatch.setattr(app, "show_error", lambda _title, message, **_kwargs: errors.append(message))
        monkeypatch.setattr("syringe_perfusion.gui.program_pair", lambda *_a, **_k: programmed.append(True))
        app.dry_run_var.set(False)
        assert not app.require_daily_live_ready()
        app.program_arm_gui()
        assert errors
        assert programmed == []
        app.dry_run_var.set(True)
        assert app.require_daily_live_ready()
        app.update_perfusion_preview()
        assert app.current_perfusion_setpoint is not None
    finally:
        app.destroy()


def test_locked_gui_assignment_controls_and_narrow_rail(monkeypatch) -> None:
    monkeypatch.setattr("syringe_perfusion.gui.persist_ui_preferences", lambda _value: None)
    app = make_app()
    try:
        app.detected_ports = ports()
        app.port_vars["IN"].set("COM_IN")
        app.port_vars["OUT"].set("COM_OUT")
        app.daily_setup_record = ready_record()
        app.guided_workflow.refresh_daily_setup()
        assert str(app.guided_workflow.daily_in_combo.cget("state")) == "disabled"
        app.geometry("900x600")
        app.deiconify()
        for _ in range(6):
            app.update()
        workflow = app.guided_workflow
        assert workflow.layout_mode == "narrow"
        assert workflow.daily_rail.winfo_ismapped()
        assert workflow.daily_scan_button.winfo_ismapped()
        assert workflow.daily_scan_button.winfo_rooty() + workflow.daily_scan_button.winfo_height() <= (
            workflow.daily_rail.winfo_rooty() + workflow.daily_rail.winfo_height()
        )
        assert workflow.step_scroll.canvas.xview() == (0.0, 1.0)
        snapshot = (app.port_vars["IN"].get(), app.in_syringe_var.get())
        app.set_language_preference("ja")
        assert snapshot == (app.port_vars["IN"].get(), app.in_syringe_var.get())
    finally:
        app.destroy()


def test_wide_daily_rail_does_not_squeeze_workflow() -> None:
    app = make_app()
    try:
        app.geometry("1170x790")
        app.deiconify()
        for _ in range(8):
            app.update()
        workflow = app.guided_workflow
        assert workflow.layout_mode == "wide"
        assert workflow.daily_rail.winfo_width() <= 260
        assert workflow.step_scroll.winfo_width() >= 500
        assert workflow.daily_lock_button.winfo_ismapped()
        assert workflow.daily_lock_button.winfo_rooty() + workflow.daily_lock_button.winfo_height() <= (
            workflow.daily_rail.winfo_rooty() + workflow.daily_rail.winfo_height()
        )
    finally:
        app.destroy()


def test_assignment_change_does_not_replace_emergency_stop_snapshots(tmp_path: Path) -> None:
    active = tmp_path / "config"
    active.mkdir()
    for filename in REQUIRED_CONFIG_FILES:
        (active / filename).write_bytes((ROOT / "config" / filename).read_bytes())
    targets = [
        {"role": "IN", "port": "COM_OLD_IN"},
        {"role": "OUT", "port": "COM_OLD_OUT"},
    ]
    write_state(active, {"state": "STOPPED", "last_known_targets": targets})
    save_pump_settings(
        active,
        in_port="COM_NEW_IN",
        out_enabled=True,
        out_port="COM_NEW_OUT",
        baudrate=9600,
        terminator="\\r\\n",
        timeout=1.0,
    )
    assert read_state(active)["last_known_targets"] == targets
