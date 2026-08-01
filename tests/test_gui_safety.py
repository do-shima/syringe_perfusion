from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from gui_app_helper import make_app
from syringe_perfusion.config import REQUIRED_CONFIG_FILES, validate_config_directory
from syringe_perfusion.perfusion_state import write_state


ROOT_CONFIG = Path(__file__).resolve().parents[1] / "config"


def make_active(tmp_path: Path) -> Path:
    active = tmp_path / "config"
    active.mkdir()
    for filename in REQUIRED_CONFIG_FILES:
        (active / filename).write_bytes((ROOT_CONFIG / filename).read_bytes())
    return active


def settle(app, predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.update()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("GUI condition not reached")


def test_manual_send_is_background_and_snapshots_tk_on_main(monkeypatch) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def fake_send(*_args, **_kwargs):
        calls.append(threading.current_thread().name)
        entered.set()
        release.wait(1)
        return {"response": "OK"}

    monkeypatch.setattr("syringe_perfusion.gui.send_action", fake_send)
    app = make_app()
    try:
        app.gui_send_manual("IN", "manual-forward", mode="manual_hold_start")
        assert entered.wait(1)
        assert calls and calls[0] != threading.main_thread().name
        app.update()
        assert app._active_operation == "manual"
        release.set()
        settle(app, lambda: "OK" in app.pump_log.get("1.0", "end"))
    finally:
        release.set()
        app.destroy()


def test_profile_and_calculator_writes_do_not_block_tk(monkeypatch) -> None:
    entered = threading.Event()
    release = threading.Event()

    def fake_write(*_args, **_kwargs):
        entered.set()
        release.wait(1)
        return [{"response": "OK"}]

    monkeypatch.setattr("syringe_perfusion.gui.write_profile", fake_write)
    monkeypatch.setattr("syringe_perfusion.gui.messagebox.askokcancel", lambda *_a, **_k: True)
    monkeypatch.setattr("syringe_perfusion.gui.messagebox.showerror", lambda *_a, **_k: None)
    app = make_app()
    try:
        app.write_profile_settings_async()
        assert entered.wait(1)
        app.update()
        assert app._active_operation == "profile_write"
        release.set()
        settle(app, lambda: app._active_operation is None)

        entered.clear()
        release.clear()
        monkeypatch.setattr("syringe_perfusion.gui.write_settings", fake_write)
        app.calculate_gui()
        app.write_calculated_settings_async()
        assert entered.wait(1)
        app.update()
        assert app._active_operation == "calculator_write"
        release.set()
        settle(app, lambda: app._active_operation is None)
    finally:
        release.set()
        app.destroy()


def test_connection_test_is_background_and_serialized(monkeypatch) -> None:
    entered = threading.Event()
    release = threading.Event()
    count = 0

    def fake_test(*_args):
        nonlocal count
        count += 1
        entered.set()
        release.wait(1)
        return ["OK"]

    monkeypatch.setattr(
        "syringe_perfusion.gui.A4PumpApp._perform_connection_test",
        staticmethod(fake_test),
    )
    app = make_app()
    try:
        app.connection_test_async()
        assert entered.wait(1)
        app.connection_test_async()
        assert count == 1
        app.update()
        release.set()
        settle(app, lambda: app._active_operation is None)
    finally:
        release.set()
        app.destroy()


def test_ui_queue_callback_exception_does_not_stop_queue(monkeypatch) -> None:
    monkeypatch.setattr("builtins.print", lambda *_a, **_k: None)
    app = make_app()
    completed: list[str] = []
    try:
        app.post_ui(lambda: (_ for _ in ()).throw(RuntimeError("bad callback")))
        app.post_ui(completed.append, "after-error")
        app._drain_ui_queue()
        assert completed == ["after-error"]
        assert app._ui_queue_after_id is not None
    finally:
        app.destroy()


def test_gui_requested_delay_uses_shared_scheduler(tmp_path: Path, monkeypatch) -> None:
    active = make_active(tmp_path)
    write_state(active, {"state": "ARMED", "plan_id": "PLAN", "plan": {"plan_id": "PLAN"}})
    captured: dict[str, object] = {}

    def fake_schedule(_resolution, **kwargs):
        captured.update(kwargs)
        return {
            "run_id": "RUN-DELAY",
            "scheduled_for": "2026-01-01T00:00:00+00:00",
        }

    monkeypatch.setattr("syringe_perfusion.gui.schedule_armed", fake_schedule)
    monkeypatch.setattr("syringe_perfusion.gui.messagebox.showerror", lambda *_a, **_k: None)
    app = make_app()
    try:
        app.config_resolution = validate_config_directory(active)
        app.dry_run_var.set(False)
        app.requested_start_delay_var.set("12.5")
        # The guided workflow treats start timing as a Step 1 condition, so a
        # previously armed plan is intentionally invalidated.  Re-arm the
        # fixture after applying the requested delay to isolate scheduler use.
        app.update_idletasks()
        write_state(active, {"state": "ARMED", "plan_id": "PLAN", "plan": {"plan_id": "PLAN"}})
        app.start_armed_gui()
        settle(app, lambda: captured.get("delay_s") == 12.5)
        settle(app, lambda: app._active_operation is None)
        assert app.perfusion_state_var.get() == "PENDING"
    finally:
        app.destroy()


def test_repeated_stop_clicks_create_one_worker(monkeypatch) -> None:
    entered = threading.Event()
    release = threading.Event()
    count = 0

    def fake_stop(*_args, **_kwargs):
        nonlocal count
        count += 1
        entered.set()
        release.wait(1)
        return {"state": "STOPPED", "stop_results": []}

    monkeypatch.setattr("syringe_perfusion.gui.stop_all_safe", fake_stop)
    app = make_app()
    try:
        app.gui_stop_all_now()
        assert entered.wait(1)
        app.gui_stop_all_now()
        assert count == 1
        assert app._stop_in_flight
        release.set()
        settle(app, lambda: not app._stop_in_flight)
    finally:
        release.set()
        app.destroy()


def test_close_waits_for_stop_completion(monkeypatch) -> None:
    entered = threading.Event()
    release = threading.Event()

    def fake_stop(*_args, **_kwargs):
        entered.set()
        release.wait(1)
        return {"state": "STOPPED", "stop_results": []}

    monkeypatch.setattr("syringe_perfusion.gui.stop_all_safe", fake_stop)
    app = make_app()
    app.on_close()
    assert entered.wait(1)
    app.update()
    assert app.winfo_exists()
    release.set()
    settle(app, lambda: getattr(app, "_destroyed", False))


@pytest.mark.parametrize(
    "state",
    ["PROGRAMMING", "PENDING", "STARTING", "RECIPE_RUNNING"],
)
def test_close_cancels_each_active_runtime_state(
    tmp_path: Path, monkeypatch, state: str
) -> None:
    active = make_active(tmp_path)
    write_state(
        active,
        {
            "state": state,
            "run_id": f"RUN-{state}",
            "operation_id": f"OP-{state}",
            "cancellation_generation": 0,
            "active_targets": [],
        },
    )
    calls: list[str] = []

    def fake_stop(*_args, **_kwargs):
        calls.append(state)
        return {"state": "STOPPED", "stop_results": []}

    monkeypatch.setattr("syringe_perfusion.gui.stop_all_safe", fake_stop)
    app = make_app()
    app.config_resolution = validate_config_directory(active)
    app.on_close()
    settle(app, lambda: getattr(app, "_destroyed", False))
    assert calls == [state]


def test_close_stop_failure_keeps_window_open(monkeypatch) -> None:
    errors: list[str] = []
    monkeypatch.setattr(
        "syringe_perfusion.gui.stop_all_safe",
        lambda *_a, **_k: {"state": "STOP_FAILED", "stop_results": [{"ok": False}]},
    )
    monkeypatch.setattr(
        "syringe_perfusion.gui.messagebox.showerror",
        lambda _title, message: errors.append(message),
    )
    app = make_app()
    try:
        app.on_close()
        settle(app, lambda: bool(errors))
        assert app.winfo_exists()
        assert app._closing is False
    finally:
        app.destroy()
