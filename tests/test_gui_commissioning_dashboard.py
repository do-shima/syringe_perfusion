from __future__ import annotations

from datetime import datetime

import pytest

from gui_app_helper import make_app


def test_commissioning_is_setup_subpage_and_dashboard_fields_render() -> None:
    app = make_app()
    try:
        app.geometry("900x600")
        app.update_idletasks()
        assert app.setup_notebook.index("end") == 2
        assert app.setup_notebook.tab(1, "text") == "Commissioning"
        app.setup_notebook.select(1)
        app.update()
        assert app.commissioning_tab.winfo_exists()
        assert app.commissioning_tab._acceptance_criteria() == {
            "minimum_replicates": 3,
            "maximum_cv_percent": 5.0,
            "maximum_abs_mean_flow_error_percent": 5.0,
        }
        assert app.commissioning_tab.exclude_replicate_button.winfo_manager() == "grid"
        app.commissioning_tab.balance_dish_method_var.set("volume")
        app.commissioning_tab.balance_dish_unit_var.set("mL")
        assert app.commissioning_tab._optional_dish_volume_ml("2") == 2.0
        app.commissioning_tab.balance_dish_method_var.set("mass")
        app.commissioning_tab.balance_dish_unit_var.set("g")
        app.commissioning_tab.balance_dish_density_var.set("1")
        assert app.commissioning_tab._optional_dish_volume_ml("2") == 2.0
        for variable in (
            app.dashboard_identity_var,
            app.dashboard_plan_var,
            app.dashboard_timing_var,
            app.dashboard_safety_var,
        ):
            assert variable is not None
        for widget in (
            app.experiment_write_button,
            app.experiment_start_button,
            app.global_stop_button,
            app.perfusion_state_label,
        ):
            assert widget.winfo_manager() == "grid"
    finally:
        app.destroy()


def test_dashboard_countdown_is_informational_and_sends_no_uart(monkeypatch) -> None:
    app = make_app()
    calls: list[str] = []
    try:
        monkeypatch.setattr(
            "syringe_perfusion.gui.send_action",
            lambda *_a, **_k: calls.append("UART"),
        )
        app.update_experiment_dashboard(
            {
                "state": "STARTED",
                "run_id": "RUN",
                "plan_id": "PLAN",
                "expected_end_epoch": datetime.now().astimezone().timestamp() + 10,
                "plan": {
                    "programmed_duration_s": 30,
                    "pumps": {
                        "IN": {"requested_flow_ml_min": 1, "expected_volume_ml": 0.5},
                        "OUT": {"requested_flow_ml_min": 1, "expected_volume_ml": 0.5},
                    },
                },
            }
        )
        assert "estimated remaining" in app.dashboard_timing_var.get()
        assert "Plan PLAN" in app.dashboard_plan_var.get()
        assert calls == []
    finally:
        app.destroy()


def test_stop_remains_available_while_commissioning_operation_active() -> None:
    app = make_app()
    try:
        assert app.begin_gui_operation("commissioning")
        app.update_runtime_controls("RECIPE_RUNNING")
        assert str(app.global_stop_button.cget("state")) != "disabled"
        assert str(app.experiment_start_button.cget("state")) == "disabled"
    finally:
        app.destroy()


def test_about_dialog_shows_build_identity_without_constructing_pump(monkeypatch) -> None:
    app = make_app()
    constructed: list[bool] = []
    try:
        monkeypatch.setattr(
            "syringe_perfusion.a4.A4Pump.__init__",
            lambda *_args, **_kwargs: constructed.append(True),
        )
        app.show_about_dialog()
        app.update_idletasks()
        assert app._about_dialog.winfo_exists()
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        text_widgets = [widget for widget in descendants(app._about_dialog) if widget.winfo_class() == "Text"]
        assert text_widgets
        contents = text_widgets[0].get("1.0", "end")
        assert "Release version: 0.2.0-beta.4" in contents
        assert "Control compatibility: 1" in contents
        assert constructed == []
    finally:
        app.destroy()


def test_close_during_commissioning_requests_cancellation_and_stop(monkeypatch) -> None:
    app = make_app()
    cancelled: list[bool] = []
    try:
        app.ensure_commissioning_workspace()
        monkeypatch.setattr(
            app.commissioning_tab,
            "cancel_execution",
            lambda: cancelled.append(True),
        )
        monkeypatch.setattr(
            "syringe_perfusion.gui.stop_all_safe",
            lambda *_a, **_k: {"state": "STOPPED", "stop_results": []},
        )
        app._active_operation = "commissioning"
        app.on_close()
        for _ in range(20):
            if getattr(app, "_destroyed", False):
                break
            app.update()
        assert cancelled == [True]
        assert getattr(app, "_destroyed", False)
    finally:
        if not getattr(app, "_destroyed", False):
            app.destroy()


@pytest.mark.parametrize("scaling", [1.25, 1.5])
def test_primary_dashboard_controls_remain_managed_at_scaling(scaling: float) -> None:
    app = make_app()
    try:
        app.tk.call("tk", "scaling", scaling)
        app.geometry("900x600")
        app.update_idletasks()
        assert app.experiment_write_button.winfo_manager() == "grid"
        assert app.experiment_start_button.winfo_manager() == "grid"
        assert app.global_stop_button.winfo_manager() == "grid"
        assert app.perfusion_state_label.winfo_manager() == "grid"
    finally:
        app.destroy()
