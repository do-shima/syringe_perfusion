from __future__ import annotations

from pathlib import Path
from tkinter import messagebox, ttk

import pytest

from gui_app_helper import make_app
from syringe_perfusion.i18n import Localizer
from syringe_perfusion.ui_theme import COLORS, ScrollableFrame


def settle(app, width: int, height: int, *, scaling: float = 1.0) -> None:
    app.tk.call("tk", "scaling", scaling)
    app.geometry(f"{width}x{height}")
    app.deiconify()
    for _ in range(4):
        app.update()
    app.recipe_tab._apply_responsive_layout()
    app._apply_advanced_responsive_layout()
    app.update_idletasks()


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def test_recipe_wide_and_narrow_layouts_have_usable_panes() -> None:
    app = make_app()
    try:
        app.select_page("recipes")
        settle(app, 1400, 850)
        recipe = app.recipe_tab
        assert recipe.recipe_layout_mode == "wide"
        assert recipe.workspace.grid_columnconfigure(1)["weight"] == 5
        assert recipe.workspace.grid_columnconfigure(1)["minsize"] >= recipe.MIN_STEPS_WIDTH
        assert recipe.workspace.grid_columnconfigure(2)["minsize"] >= recipe.MIN_INSPECTOR_WIDTH
        assert recipe.steps_frame.grid_info()["column"] == 1
        assert recipe.inspector_frame.grid_info()["column"] == 2
        settle(app, 900, 600)
        assert recipe.recipe_layout_mode == "narrow"
        recipe.show_narrow_view("inspector")
        assert recipe.inspector_frame.grid_info()["row"] == 1
        assert recipe.inspector_frame.grid_info()["columnspan"] == 2
        assert len({(button.grid_info()["row"], button.grid_info()["column"]) for button in recipe.action_buttons.values()}) == 8
    finally:
        app.destroy()


@pytest.mark.parametrize("scaling", [1.0, 1.25, 1.5])
def test_recipe_inspector_and_library_remain_scrollable_at_900(scaling: float) -> None:
    app = make_app()
    try:
        settle(app, 900, 600, scaling=scaling)
        recipe = app.recipe_tab
        recipe.show_narrow_view("inspector")
        assert isinstance(recipe.inspector_scroll, ScrollableFrame)
        assert isinstance(recipe.library_scroll, ScrollableFrame)
        recipe.inspector_scroll.scroll_end()
        recipe.library_scroll.scroll_end()
        app.update_idletasks()
        assert recipe.inspector_scroll.canvas.yview()[1] == pytest.approx(1.0)
        assert recipe.library_scroll.canvas.yview()[1] == pytest.approx(1.0)
        assert recipe.apply_button.winfo_manager() == "grid"
        assert recipe.prop_pump_combo.winfo_manager() == "grid"
    finally:
        app.destroy()


def test_recipe_tree_is_compact_and_has_one_move_control_location() -> None:
    app = make_app()
    try:
        recipe = app.recipe_tab
        for block_type in ("wait", "log_marker", "prompt_check"):
            recipe.add_block(block_type)
        assert len(recipe.steps_tree.get_children()) == 4
        assert not hasattr(recipe, "step_cards")
        assert len(recipe.move_buttons) == 4
        assert str(recipe.steps_tree.cget("selectmode")) == "browse"
        assert recipe.steps_tree.cget("yscrollcommand")
        assert recipe.steps_tree.cget("xscrollcommand")
    finally:
        app.destroy()


def test_recipe_selection_persists_after_movement_and_duplicate() -> None:
    app = make_app()
    try:
        recipe = app.recipe_tab
        recipe.add_block("wait")
        selected_id = recipe.blocks[1]["id"]
        recipe.move_up()
        assert recipe.blocks[0]["id"] == selected_id
        assert recipe.selected_index() == 0
        assert recipe.steps_tree.selection() == ("0",)
        recipe.duplicate_selected()
        assert recipe.selected_index() == 1
        assert recipe.blocks[1]["id"] != selected_id
    finally:
        app.destroy()


def test_recipe_unsaved_state_and_prompt_protect_data(monkeypatch) -> None:
    app = make_app()
    try:
        recipe = app.recipe_tab
        recipe.add_block("wait")
        assert recipe.modified
        monkeypatch.setattr(messagebox, "askyesno", lambda *_a, **_k: False)
        recipe.new_recipe()
        assert len(recipe.blocks) == 2
        assert recipe.modified
    finally:
        app.destroy()


def test_inspector_hides_irrelevant_fields_and_marks_unapplied_changes() -> None:
    app = make_app()
    try:
        recipe = app.recipe_tab
        recipe.add_block("wait")
        assert recipe.inspector_fields["duration_s"].winfo_manager() == "grid"
        assert recipe.inspector_fields["pump"].winfo_manager() == ""
        assert recipe.inspector_fields["profile"].winfo_manager() == ""
        recipe.prop_duration_var.set("2.5")
        assert recipe.inspector_dirty
        assert recipe.apply_button.cget("style") == "Warning.TButton"
    finally:
        app.destroy()


def test_recipe_language_switch_preserves_canonical_block_values(monkeypatch) -> None:
    app = make_app()
    try:
        monkeypatch.setattr("syringe_perfusion.gui.persist_ui_preferences", lambda _value: None)
        recipe = app.recipe_tab
        before = [dict(block) for block in recipe.blocks]
        app.set_language_preference("ja")
        assert recipe.prop_type_display_var.get() == "ポンプ開始"
        assert recipe.blocks == before
        assert recipe.prop_type_var.get() == "pump_start"
        app.set_language_preference("en")
        assert recipe.prop_type_display_var.get() == "Pump start"
        assert recipe.blocks == before
    finally:
        app.destroy()


def test_recipe_source_uses_explicit_localization_not_literal_tree() -> None:
    source = (Path(__file__).parents[1] / "syringe_perfusion" / "gui_recipe.py").read_text(encoding="utf-8")
    assert "bind_literal_tree" not in source
    for obsolete in ('text="Recipe Builder"', 'text="Dry-run"', 'text="Run"', 'text="Apply changes"'):
        assert obsolete not in source


def test_button_styles_are_distinct_visible_and_focusable() -> None:
    app = make_app()
    try:
        style = app.style
        assert style.lookup("Neutral.TButton", "background") == "#EEF2F7"
        assert style.lookup("Neutral.TButton", "bordercolor") == "#CBD5E1"
        assert style.lookup("Neutral.TButton", "background") != COLORS["card"]
        assert style.lookup("Primary.TButton", "background") != style.lookup("Success.TButton", "background")
        assert style.lookup("Warning.TButton", "background") != style.lookup("Danger.TButton", "background")
        neutral_map = dict(style.map("Neutral.TButton"))
        assert "bordercolor" in neutral_map
        assert any("focus" in str(value) for value in neutral_map["bordercolor"])
        assert any("disabled" in str(value) for value in neutral_map["background"])
        assert app.experiment_write_button.cget("takefocus") != "0"
        assert app.global_stop_button.cget("takefocus") != "0"
        tab_map = dict(style.map("TNotebook.Tab"))
        assert "background" in tab_map and any("selected" in str(item) for item in tab_map["background"])
    finally:
        app.destroy()


def test_profile_and_calculator_are_responsive_and_localized(monkeypatch) -> None:
    app = make_app()
    try:
        monkeypatch.setattr("syringe_perfusion.gui.persist_ui_preferences", lambda _value: None)
        settle(app, 900, 600)
        assert app.profile_layout_mode == "narrow"
        assert app.calc_layout_mode == "narrow"
        assert "[fast30_1ml]" in app.profile_display_var.get()
        app.update_profile_info()
        assert "Programmed speed" in app.profile_result_var.get()
        assert "q1h" in app.profile_commands_var.get()
        assert "q1h" not in app.profile_result_var.get()
        assert app.calc_result_var.get() == "Enter conditions and press Calculate."
        canonical = app.calc_mode_var.get()
        app.set_language_preference("ja")
        assert app.calc_mode_var.get() == canonical
        assert app.calc_mode_display_var.get() == "体積＋時間"
        assert "設定速度" in app.profile_result_var.get()
        assert "recommended fill" not in app.profile_result_var.get()
    finally:
        app.destroy()


def test_history_has_both_scrollbars_and_localizes_state() -> None:
    app = make_app()
    try:
        history = app.history_tab
        assert history.vscroll.winfo_manager() == "grid"
        assert history.hscroll.winfo_manager() == "grid"
        history._apply_runs([{"timestamp": "T", "run_id": "R", "terminal_state": "STOP_FAILED"}], None)
        assert "STOP_FAILED" in history.tree.item("0", "values")[-1]
        assert history.tree.column("terminal_state", "minwidth") > 0
    finally:
        app.destroy()


def test_about_dialog_is_structured_copyable_and_does_not_select_text() -> None:
    app = make_app()
    try:
        app.show_about_dialog()
        app.update_idletasks()
        widgets = list(descendants(app._about_dialog))
        texts = [widget for widget in widgets if widget.winfo_class() == "Text"]
        readonly_entries = [widget for widget in widgets if isinstance(widget, ttk.Entry) and str(widget.cget("state")) == "readonly"]
        assert texts and readonly_entries
        assert not texts[0].tag_ranges("sel")
        assert any(str(app.config_resolution.active_config_dir) == entry.get() for entry in readonly_entries)
        assert any(isinstance(widget, ttk.Scrollbar) for widget in widgets)
    finally:
        app.destroy()


def test_out_disabled_presentation_and_arm_label_are_unambiguous() -> None:
    app = make_app()
    try:
        app.set_language_preference("en")
        app.set_out_enabled(False)
        app.update_experiment_dashboard({"state": "DIRTY", "plan": {"pumps": {"IN": {"requested_flow_ml_min": 1}}}})
        assert app.experiment_write_button.cget("text") == "PROGRAM / ARM PUMP"
        assert "OUT is disabled" in app.dashboard_plan_var.get()
        assert "OUT flow" not in app.dashboard_plan_var.get()
        assert str(app.out_ratio_entry.cget("state")) == "disabled"
        app.set_out_enabled(True)
        assert app.experiment_write_button.cget("text") == "PROGRAM / ARM BOTH"
    finally:
        app.destroy()


def test_fault_display_distinguishes_current_previous_and_acknowledged() -> None:
    app = make_app()
    try:
        app.set_language_preference("en")
        fault = {"error": "one or more STOP commands failed", "at": "2026-01-01T00:00:00Z"}
        app.update_experiment_dashboard({"state": "STOPPED", "fault": fault, "plan": {}})
        assert "Previous fault" in app.dashboard_safety_var.get()
        assert app.dashboard_fault_raw_var.get() == "one or more STOP commands failed"
        app.acknowledge_historical_fault()
        assert "Acknowledged" in app.dashboard_safety_var.get()
        app.update_experiment_dashboard({"state": "FAULT", "fault": fault, "plan": {}})
        assert "Current fault" in app.dashboard_safety_var.get()
        assert "Acknowledged" not in app.dashboard_safety_var.get()
    finally:
        app.destroy()


def test_known_fault_and_calculator_mappings_are_bilingual_and_reversible() -> None:
    en = Localizer("en")
    ja = Localizer("ja")
    assert ja.fault_summary("one or more STOP commands failed") == "1台以上のSTOPコマンドが失敗しました"
    assert en.fault_summary("unrecognized raw message") == "unrecognized raw message"
    candidates = ("volume_duration", "volume_flow", "speed_duration")
    for localizer in (en, ja):
        for value in candidates:
            assert localizer.canonical_value(localizer.display_value(value), candidates) == value


def test_recipe_keyboard_bindings_and_global_escape_are_present() -> None:
    app = make_app()
    try:
        for sequence in ("<Control-s>", "<Control-Shift-s>", "<Control-o>", "<Control-n>"):
            assert app.bind(sequence)
        assert app.bind_all("<Escape>")
        assert app.recipe_tab.steps_tree.bind("<Delete>")
        assert app.recipe_tab.steps_tree.bind("<Control-d>")
        assert app.recipe_tab.steps_tree.cget("takefocus") != "0"
    finally:
        app.destroy()
