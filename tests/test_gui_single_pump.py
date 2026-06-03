from __future__ import annotations

import sys
import types

import pytest

from gui_app_helper import make_app


def test_out_disabled_gui_initializes_with_in_only() -> None:
    app = make_app()
    try:
        assert app.available_pumps() == ["IN"]
        assert app.manual_pump_combo.cget("values") == ("IN",)
        assert app.run_mode_combo.cget("values") == ("IN only",)
    finally:
        app.destroy()


def test_connection_test_checks_only_enabled_pumps(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeSerial:
        def __init__(self, port: str, *_args, **_kwargs) -> None:
            calls.append(port)

        def __enter__(self) -> "FakeSerial":
            return self

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=FakeSerial))
    app = make_app()
    try:
        app.dry_run_var.set(False)
        app.connection_test()
        assert calls == [app.port_vars["IN"].get()]
    finally:
        app.destroy()


def test_out_disabled_pushpull_mode_is_rejected() -> None:
    app = make_app()
    try:
        app.run_mode_var.set("Push-pull")
        with pytest.raises(ValueError, match="requires OUT"):
            app.start_run_mode()
    finally:
        app.destroy()


def test_out_enabled_restores_out_run_modes() -> None:
    app = make_app()
    try:
        app.port_vars["OUT"].set("COM6")
        app.set_out_enabled(True)
        assert app.available_pumps() == ["IN", "OUT"]
        assert app.run_mode_combo.cget("values") == ("IN only", "OUT only", "Push-pull", "Two forward")
    finally:
        app.destroy()
