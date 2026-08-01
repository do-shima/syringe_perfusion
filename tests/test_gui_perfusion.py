from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Event
from typing import Any

from gui_app_helper import make_app
from syringe_perfusion.config import REQUIRED_CONFIG_FILES, validate_config_directory
from syringe_perfusion.perfusion_state import write_state


ROOT_CONFIG = Path(__file__).resolve().parents[1] / "config"


def make_active(tmp_path: Path) -> Path:
    active = tmp_path / "config"
    active.mkdir()
    for filename in REQUIRED_CONFIG_FILES:
        (active / filename).write_bytes((ROOT_CONFIG / filename).read_bytes())
    document = json.loads((active / "pumps.json").read_text(encoding="utf-8"))
    document["pumps"]["IN"]["port"] = "COM_A"
    document["pumps"]["OUT"]["port"] = "COM_B"
    document["pumps"]["OUT"]["enabled"] = True
    (active / "pumps.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return active


def settle(app, predicate, timeout: float = 1.5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.update()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("GUI condition was not reached")


def test_startup_scan_is_background_and_keeps_saved_undetected(
    tmp_path: Path, monkeypatch
) -> None:
    active = make_active(tmp_path)

    scan_started = Event()
    release_scan = Event()
    scan_finished = Event()

    def slow_scan():
        scan_started.set()
        assert release_scan.wait(1)
        scan_finished.set()
        return [{"device": "COM2", "description": "Detected", "hwid": "HW2"}]

    monkeypatch.setattr("syringe_perfusion.gui.list_serial_ports", slow_scan)
    app = make_app(auto_scan=True)
    try:
        settle(app, scan_started.is_set)
        assert not scan_finished.is_set()
        assert app.winfo_exists()
        release_scan.set()
        app.config_resolution = validate_config_directory(active)
        app.reload_from_json(confirm=False)
        settle(app, lambda: not getattr(app, "_port_scan_running", False))
        assert app.in_port_combo.cget("values") == ("COM2", "COM_A", "COM_B")
        assert "NOT DETECTED" in app.in_port_metadata_var.get()
        assert "device(s)" in app.port_scan_status_var.get()
    finally:
        app.destroy()


def test_slider_and_numeric_entry_only_change_preview(monkeypatch) -> None:
    serial_calls: list[str] = []
    monkeypatch.setattr("syringe_perfusion.gui.program_pair", lambda *_a, **_k: serial_calls.append("program"))
    app = make_app()
    try:
        app.on_flow_slider("1.37")
        settle(app, lambda: app.current_perfusion_setpoint is not None)
        assert app.in_flow_var.get() == "1.4"
        assert serial_calls == []
        app.in_flow_var.set("4.25")
        settle(app, lambda: "OUTSIDE SLIDER RANGE" in app.perfusion_preview_var.get())
        assert app.in_flow_var.get() == "4.25"
        assert serial_calls == []
    finally:
        app.destroy()


def test_program_arm_uses_shared_operation_and_state_controls(
    tmp_path: Path, monkeypatch
) -> None:
    active = make_active(tmp_path)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr("syringe_perfusion.gui.list_serial_ports", lambda: [
        {"device": "COM_A", "description": "IN", "hwid": "A"},
        {"device": "COM_B", "description": "OUT", "hwid": "B"},
    ])
    monkeypatch.setattr("syringe_perfusion.gui.messagebox.showerror", lambda *_a, **_k: None)

    def fake_program(_config, setpoint, **kwargs):
        calls.append({"setpoint": setpoint, **kwargs})
        return {"state": "ARMED", "plan_id": "PLAN", "message": "PROGRAMMED — NOT READ BACK"}

    monkeypatch.setattr("syringe_perfusion.gui.program_pair", fake_program)
    app = make_app()
    try:
        app.config_resolution = validate_config_directory(active)
        app.reload_from_json(confirm=False)
        settle(app, lambda: app.current_perfusion_setpoint is not None)
        app.dry_run_var.set(False)
        monkeypatch.setattr(app, "require_daily_live_ready", lambda: True)
        app.program_arm_gui()
        settle(app, lambda: bool(calls) and not app._program_running)
        assert calls[0]["setpoint"].in_setpoint.direction == "forward"
        assert app.perfusion_state_var.get() == "ARMED"
        assert app.programmed_message_var.get() == "PROGRAMMED — NOT READ BACK"
        assert "disabled" not in app.experiment_start_button.state()
        app.set_operational_state("STARTED")
        assert "disabled" in app.in_flow_entry.state()
        assert "disabled" not in app.global_stop_button.state()
    finally:
        app.destroy()


def test_external_runtime_state_is_reflected(tmp_path: Path, monkeypatch) -> None:
    active = make_active(tmp_path)
    monkeypatch.setattr("syringe_perfusion.gui.list_serial_ports", lambda: [])
    app = make_app()
    try:
        app.config_resolution = validate_config_directory(active)
        app.reload_from_json(confirm=False)
        write_state(active, {"state": "PENDING", "plan_id": "P", "plan": {}})
        app.poll_runtime_state()
        assert app.perfusion_state_var.get() == "PENDING"
        assert "disabled" in app.in_flow_entry.state()
        assert "disabled" not in app.global_stop_button.state()
    finally:
        app.destroy()


def test_primary_controls_are_gridded_at_900x600() -> None:
    app = make_app()
    try:
        app.geometry("900x600")
        app.select_page("experiment")
        app.update_idletasks()
        assert app.experiment_write_button.winfo_manager() == "grid"
        assert app.experiment_start_button.winfo_manager() == "grid"
        assert app.global_stop_button.winfo_manager() == "grid"
        assert app.perfusion_state_label.winfo_manager() == "grid"
    finally:
        app.destroy()
