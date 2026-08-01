from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path

import pytest

from gui_app_helper import make_app
from syringe_perfusion.gui_workflow import WORKFLOW_STATES, GuidedExperimentFrame


def settle(app, width: int = 900, height: int = 600, *, scaling: float = 1.0) -> None:
    app.tk.call("tk", "scaling", scaling)
    app.geometry(f"{width}x{height}")
    app.deiconify()
    for _ in range(5):
        app.update()


def enter_conditions(app) -> GuidedExperimentFrame:
    workflow = app.guided_workflow
    app.condition_var.set("wash")
    app.dish_id_var.set("D-01")
    app.in_flow_var.set("1.0")
    settle(app)
    assert workflow.conditions_complete()
    return workflow


def arm_for_presentation(app) -> GuidedExperimentFrame:
    workflow = enter_conditions(app)
    workflow.go_to_step(2)
    app.set_operational_state("ARMED")
    workflow.on_programming_succeeded()
    settle(app)
    assert workflow.programmed()
    return workflow


def test_four_step_workflow_is_default_primary_page() -> None:
    app = make_app()
    try:
        workflow = app.guided_workflow
        assert isinstance(workflow, GuidedExperimentFrame)
        assert tuple(workflow.step_frames) == (1, 2, 3, 4)
        assert WORKFLOW_STATES == (
            "UNSET",
            "INPUT_COMPLETE",
            "NEEDS_PROGRAMMING",
            "PROGRAMMED",
            "NEEDS_NIS",
            "READY",
            "RUNNING",
            "STOPPED",
            "REVIEW",
            "FAULT",
        )
        assert app.current_page == "experiment"
        assert workflow.current_step == 1
        assert workflow.step_frames[1].winfo_manager() == "grid"
        assert set(app.nav_buttons) >= {"experiment", "history", "management"}
    finally:
        app.destroy()


def test_progression_requires_conditions_programming_and_nis_checklist() -> None:
    app = make_app()
    try:
        workflow = app.guided_workflow
        assert not workflow.go_to_step(2)
        workflow = enter_conditions(app)
        assert workflow.go_to_step(2)
        assert not workflow.go_to_step(3)
        app.set_operational_state("ARMED")
        workflow.on_programming_succeeded()
        settle(app)
        assert workflow.go_to_step(3)
        assert not workflow.go_to_step(4)
        for variable in workflow.checklist_vars.values():
            variable.set(True)
        workflow.activate_primary_action()
        assert workflow.current_step == 4
        assert workflow.workflow_status_var.get() == app.t("workflow.status.ready")
    finally:
        app.destroy()


def test_condition_and_port_changes_invalidate_later_steps() -> None:
    app = make_app()
    try:
        workflow = arm_for_presentation(app)
        assert workflow.go_to_step(3)
        for variable in workflow.checklist_vars.values():
            variable.set(True)
        workflow.activate_primary_action()
        assert workflow.current_step == 4

        app.in_flow_var.set("2.0")
        settle(app)
        assert app._operational_state == "DIRTY"
        assert workflow.current_step == 1
        assert workflow._nis_ready is False
        assert "again" in workflow.notice_var.get().lower()

        app.set_operational_state("ARMED")
        workflow.go_to_step(3)
        app.port_vars["IN"].set("COM_TEST_CHANGED")
        settle(app)
        assert app._operational_state == "DIRTY"
        assert workflow.highest_accessible_step() == 2
    finally:
        app.destroy()


def test_nis_step_uses_existing_immediate_and_delayed_wrappers() -> None:
    app = make_app()
    try:
        workflow = app.guided_workflow
        workflow.start_mode_var.set("nis")
        workflow.start_timing_var.set("immediate")
        app.requested_start_delay_var.set("0")
        workflow.refresh()
        assert workflow._start_wrapper_name() == "pump_start_armed.cmd"
        assert "pump_start_armed.cmd" in workflow._nis_command(workflow._start_wrapper_name())

        workflow.start_timing_var.set("delayed")
        app.requested_start_delay_var.set("300")
        workflow.refresh()
        assert workflow._start_wrapper_name() == "pump_start_armed_after_300s.cmd"
        assert "pump_stop_all.cmd" in workflow._nis_command("pump_stop_all.cmd")
        assert str(app.config_resolution.active_config_dir) not in workflow.nis_destination_var.get()
        assert workflow.full_config_var.get() == str(app.config_resolution.active_config_dir)
        app.copy_config_path()
        assert app.clipboard_get() == str(app.config_resolution.active_config_dir)

        app.requested_start_delay_var.set("12.5")
        workflow.refresh()
        assert not workflow.nis_timing_supported()
        assert "300" in workflow.nis_config_var.get()
    finally:
        app.destroy()


def test_technical_details_are_collapsed_and_out_disabled_summary_is_explicit() -> None:
    app = make_app()
    try:
        workflow = enter_conditions(app)
        assert workflow.technical_details_visible is False
        assert workflow.technical_card.winfo_manager() == ""
        app.set_out_enabled(False)
        workflow.refresh()
        assert app.t("label.disabled") in workflow.summary_flow_var.get()
        assert app.t("label.disabled") in workflow.summary_ports_var.get()
        assert app.t("label.disabled").casefold() in workflow.compact_summary_var.get().casefold()
        workflow.toggle_technical_details()
        assert workflow.technical_card.winfo_manager() == "grid"
    finally:
        app.destroy()


def test_summary_updates_immediately_without_uart(monkeypatch) -> None:
    app = make_app()
    try:
        unexpected: list[str] = []
        monkeypatch.setattr(app, "gui_send_async", lambda *_a, **_k: unexpected.append("uart"))
        workflow = enter_conditions(app)
        before = workflow.summary_flow_var.get()
        app.in_flow_var.set("0.5")
        app.update_perfusion_preview()
        settle(app)
        assert workflow.summary_flow_var.get() != before
        assert "0.5" in workflow.summary_flow_var.get()
        assert unexpected == []
    finally:
        app.destroy()


def test_language_switch_preserves_scientific_and_workflow_values(monkeypatch) -> None:
    app = make_app()
    try:
        monkeypatch.setattr("syringe_perfusion.gui.persist_ui_preferences", lambda _value: None)
        workflow = arm_for_presentation(app)
        workflow.go_to_step(3)
        workflow.checklist_vars["imaging"].set(True)
        snapshot = (
            app.in_flow_var.get(),
            app.out_ratio_var.get(),
            app.in_syringe_var.get(),
            workflow.current_step,
            workflow.checklist_vars["imaging"].get(),
            app._operational_state,
        )
        app.set_language_preference("ja")
        assert app.t("workflow.step1.short") == "実験条件"
        assert snapshot == (
            app.in_flow_var.get(),
            app.out_ratio_var.get(),
            app.in_syringe_var.get(),
            workflow.current_step,
            workflow.checklist_vars["imaging"].get(),
            app._operational_state,
        )
    finally:
        app.destroy()


@pytest.mark.parametrize("scaling", [1.0, 1.25, 1.5])
def test_guided_workflow_reachable_at_supported_geometry(scaling: float) -> None:
    app = make_app()
    try:
        settle(app, 900, 600, scaling=scaling)
        workflow = app.guided_workflow
        assert workflow.progress_card.winfo_ismapped()
        assert workflow.primary_action_button.winfo_ismapped()
        assert app.global_stop_button.winfo_ismapped()
        first, last = workflow.step_scroll.canvas.yview()
        assert last > first
        workflow.step_scroll.scroll_end()
        app.update_idletasks()
        assert workflow.step_scroll.canvas.yview()[1] == pytest.approx(1.0)
        assert workflow.step_scroll.canvas.xview() == (0.0, 1.0)
    finally:
        app.destroy()


def test_escape_still_routes_to_authoritative_stop(monkeypatch) -> None:
    app = make_app()
    try:
        calls: list[str] = []
        monkeypatch.setattr(app, "gui_stop_all_now", lambda: calls.append("stop"))
        event = tk.Event()
        assert app.on_escape_stop(event) == "break"
        assert calls == ["stop"]
    finally:
        app.destroy()


def test_routine_path_does_not_require_advanced_tools() -> None:
    app = make_app()
    try:
        workflow = arm_for_presentation(app)
        assert workflow.go_to_step(3)
        assert app.notebook.select() == str(app.pages["experiment"])
        assert app.pages["profiles"] is app.pages["management"]
        assert app.pages["calculator"] is app.pages["management"]
        assert app.pages["recipes"] is app.pages["management"]
    finally:
        app.destroy()


def test_guided_workflow_uses_explicit_localization_keys() -> None:
    source = (Path(__file__).resolve().parents[1] / "syringe_perfusion" / "gui_workflow.py").read_text(
        encoding="utf-8"
    )
    direct_operator_literal = re.compile(r"(?:text|title)\s*=\s*['\"][A-Za-z][^'\"]*['\"]")
    assert direct_operator_literal.search(source.replace('text="mL/min"', "")) is None
    assert "bind_literal_tree" not in source
