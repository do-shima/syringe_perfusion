from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from gui_app_helper import make_app
from syringe_perfusion.perfusion_state import config_fingerprint
from syringe_perfusion.ui_theme import ScrollableFrame, apply_theme, select_ui_font


def settle_geometry(app, width: int, height: int, *, scaling: float = 1.0) -> None:
    app.tk.call("tk", "scaling", scaling)
    app.geometry(f"{width}x{height}")
    app.deiconify()
    for _ in range(4):
        app.update()
    app._apply_experiment_layout()
    app.update_idletasks()


@pytest.mark.parametrize("scaling", [1.0, 1.25, 1.5])
def test_experiment_bottom_is_scroll_reachable_and_fixed_controls_remain_visible(scaling: float) -> None:
    app = make_app()
    try:
        settle_geometry(app, 900, 600, scaling=scaling)
        first, last = app.experiment_scroll.canvas.yview()
        assert last < 1.0
        app.experiment_scroll.scroll_end()
        app.update_idletasks()
        first, last = app.experiment_scroll.canvas.yview()
        assert last == pytest.approx(1.0)
        assert app.run_log.winfo_rooty() < app.experiment_scroll.canvas.winfo_rooty() + app.experiment_scroll.canvas.winfo_height()
        assert app.experiment_action_strip.winfo_ismapped()
        assert app.global_stop_button.winfo_ismapped()
        assert app.experiment_scroll.canvas.xview() == (0.0, 1.0)
    finally:
        app.destroy()


def test_mousewheel_page_home_end_and_resize_update_viewport() -> None:
    app = make_app()
    try:
        settle_geometry(app, 900, 600)
        before = app.experiment_scroll.canvas.yview()
        event = type("Event", (), {"num": None, "delta": -240})()
        assert app.experiment_scroll._on_mousewheel(event) == "break"
        assert app.experiment_scroll.canvas.yview()[0] > before[0]
        app.experiment_scroll.scroll_end()
        assert app.experiment_scroll.canvas.yview()[1] == pytest.approx(1.0)
        app.experiment_scroll.scroll_home()
        assert app.experiment_scroll.canvas.yview()[0] == pytest.approx(0.0)
        initial_width = int(float(app.experiment_scroll.canvas.itemcget(app.experiment_scroll.window_id, "width")))
        settle_geometry(app, 1100, 720)
        resized_width = int(float(app.experiment_scroll.canvas.itemcget(app.experiment_scroll.window_id, "width")))
        assert resized_width != initial_width
        assert resized_width == pytest.approx(app.experiment_scroll.canvas.winfo_width(), abs=2)
        assert app.experiment_scroll.canvas.bbox("all") is not None
    finally:
        app.destroy()


def test_wide_layout_has_two_columns_and_narrow_layout_stacks() -> None:
    app = make_app()
    try:
        settle_geometry(app, 1300, 800)
        assert app.experiment_layout_mode == "wide"
        assert app.experiment_setpoint_card.grid_info()["column"] == 0
        assert app.experiment_pair_card.grid_info()["column"] == 1
        settle_geometry(app, 900, 600)
        assert app.experiment_layout_mode == "narrow"
        # The guided layout keeps the step workspace full-width and moves its
        # compact summary into the fixed progress card at narrow widths.
        assert app.guided_workflow.step_scroll.grid_info()["column"] == 0
        assert app.guided_workflow.narrow_summary_label.winfo_ismapped()
        assert not app.guided_workflow.summary_card.winfo_ismapped()
        positions = {
            (button.grid_info()["row"], button.grid_info()["column"])
            for button in (
                app.scan_ports_button,
                app.experiment_write_button,
                app.experiment_start_button,
                app.experiment_stop_button,
            )
        }
        assert len(positions) == 4
    finally:
        app.destroy()


def test_scroll_frames_do_not_use_global_mousewheel_bindings_or_unbind_each_other() -> None:
    app = make_app()
    root = tk.Toplevel(app)
    root.withdraw()
    try:
        apply_theme(root)
        original = root.bind_all("<MouseWheel>")
        first = ScrollableFrame(root)
        second = ScrollableFrame(root)
        first.grid()
        second.grid()
        assert root.bind_all("<MouseWheel>") == original
        first.destroy()
        assert second in second._dispatcher.frames
        assert root.bind_all("<MouseWheel>") == original
        dispatcher = second._dispatcher
        second.destroy()
        assert not dispatcher._bindings
        assert root.bind_all("<MouseWheel>") == original
    finally:
        root.destroy()
        app.destroy()


def test_scroll_dispatcher_leaves_editable_text_mousewheel_behavior_alone() -> None:
    app = make_app()
    root = tk.Toplevel(app)
    try:
        apply_theme(root)
        frame = ScrollableFrame(root)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame.inner, height=3)
        text.pack()
        text.insert("1.0", "\n".join(str(index) for index in range(30)))
        root.update()
        event = type(
            "Event",
            (),
            {
                "x_root": text.winfo_rootx() + 2,
                "y_root": text.winfo_rooty() + 2,
                "delta": -120,
                "num": None,
            },
        )()
        assert frame._dispatcher._mouse(event) is None
    finally:
        root.destroy()
        app.destroy()


def test_setup_commissioning_and_advanced_use_shared_scroll_component() -> None:
    app = make_app()
    try:
        commissioning = app.ensure_commissioning_workspace()
        assert commissioning.winfo_exists()
        for frame in (
            app.setup_scroll,
            app.commissioning_scroll,
            app.profile_scroll,
            app.calculator_scroll,
        ):
            assert isinstance(frame, ScrollableFrame)
            assert frame._dispatcher is app.experiment_scroll._dispatcher
    finally:
        app.destroy()


def test_runtime_language_switch_preserves_internal_values_and_scientific_state(monkeypatch) -> None:
    app = make_app()
    writes: list[dict[str, str]] = []
    try:
        monkeypatch.setattr("syringe_perfusion.gui.persist_ui_preferences", lambda value: writes.append(dict(value)))
        before_fingerprint = config_fingerprint(app.config_resolution.active_config_dir)
        app.perfusion_mode_var.set("fixed_duration")
        app.update_perfusion_preview()
        before_uart = [
            line for line in app.perfusion_preview_var.get().splitlines() if "UART:" in line
        ]
        app.set_operational_state("ARMED")
        app.set_language_preference("ja")
        assert app.perfusion_mode_var.get() == "fixed_duration"
        assert app.perfusion_mode_display_var.get() == "時間指定"
        assert "ARMED" in app.perfusion_state_var.get()
        assert config_fingerprint(app.config_resolution.active_config_dir) == before_fingerprint
        after_uart = [
            line for line in app.perfusion_preview_var.get().splitlines() if "UART:" in line
        ]
        assert after_uart == before_uart
        assert app.nav_buttons["experiment"].cget("text") == "実験"
        assert app.global_stop_button.cget("text") == "全停止（Esc）"
        app.set_language_preference("en")
        assert app.perfusion_mode_var.get() == "fixed_duration"
        assert app.perfusion_mode_display_var.get() == "Fixed duration"
        assert writes == [{"language": "ja"}, {"language": "en"}]
    finally:
        app.destroy()


def test_japanese_text_wraps_without_forcing_horizontal_overflow(monkeypatch) -> None:
    app = make_app()
    try:
        monkeypatch.setattr("syringe_perfusion.gui.persist_ui_preferences", lambda _value: None)
        app.set_language_preference("ja")
        app.dashboard_safety_var.set("非常に長い安全情報です。" * 30)
        settle_geometry(app, 900, 600, scaling=1.5)
        app.experiment_scroll._update_wraplengths()
        assert app.experiment_layout_mode == "narrow"
        assert app.experiment_scroll.canvas.xview() == (0.0, 1.0)
        assert app.global_stop_button.winfo_ismapped()
    finally:
        app.destroy()


def test_font_selection_prefers_japanese_capable_windows_fonts() -> None:
    assert select_ui_font({"Segoe UI", "Meiryo"}) == "Meiryo"
    assert select_ui_font({"Segoe UI", "Yu Gothic UI"}) == "Yu Gothic UI"
    assert select_ui_font(set()) == "TkDefaultFont"
