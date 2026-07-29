from __future__ import annotations

import json
from pathlib import Path

from gui_app_helper import make_app
from syringe_perfusion.config import REQUIRED_CONFIG_FILES, load_config, validate_config_directory
from syringe_perfusion.gui import merge_port_candidates


ROOT_CONFIG = Path(__file__).resolve().parents[1] / "config"


def make_config(destination: Path) -> Path:
    destination.mkdir(parents=True)
    for filename in REQUIRED_CONFIG_FILES:
        (destination / filename).write_bytes((ROOT_CONFIG / filename).read_bytes())
    return destination


def test_gui_save_and_external_edit_reload_use_same_active_config(
    tmp_path: Path, monkeypatch
) -> None:
    active = make_config(tmp_path / "config")
    app = make_app()
    try:
        monkeypatch.setattr("syringe_perfusion.gui.list_serial_ports", lambda: [])
        monkeypatch.setattr("syringe_perfusion.gui.messagebox.showinfo", lambda *_args, **_kwargs: None)
        monkeypatch.setattr("syringe_perfusion.gui.messagebox.showerror", lambda *_args, **_kwargs: None)
        app.config_resolution = validate_config_directory(active)
        assert app.reload_from_json(confirm=False)

        app.port_vars["IN"].set(" COM_A ")
        app.port_vars["OUT"].set(" COM_B ")
        app.out_enabled_var.set(True)
        saved = app.save_pump_settings_gui()
        assert saved == (active / "pumps.json").resolve()
        cli_data = load_config(active)
        assert cli_data["pumps"]["IN"]["port"] == "COM_A"
        assert cli_data["pumps"]["OUT"]["port"] == "COM_B"
        assert cli_data["pumps"]["OUT"]["enabled"] is True

        document = json.loads(saved.read_text(encoding="utf-8"))
        document["pumps"]["IN"]["port"] = "COM12"
        saved.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        assert app.reload_from_json(confirm=False)
        assert app.port_vars["IN"].get() == "COM12"
        assert "COM12" in app.in_port_combo.cget("values")
        assert app.out_enabled_var.get() is True
        assert app.manual_pump_combo.cget("values") == ("IN", "OUT")
    finally:
        app.destroy()


def test_experiment_primary_actions_and_global_stop_exist_at_small_geometry() -> None:
    app = make_app()
    try:
        app.geometry("900x600")
        app.select_page("experiment")
        app.update_idletasks()
        assert app.minsize() == (860, 560)
        assert app.experiment_start_button.winfo_manager() == "grid"
        assert app.experiment_write_button.winfo_manager() == "grid"
        assert app.global_stop_button.winfo_manager() == "grid"
        assert "disabled" not in app.global_stop_button.state()
    finally:
        app.destroy()


def test_port_candidates_are_union_deduplicated_and_naturally_sorted() -> None:
    assert merge_port_candidates(
        ["COM10", "COM2", "COM2"],
        ["COM7", "COM40"],
        [" COM3 ", "COM7"],
    ) == ["COM2", "COM3", "COM7", "COM10", "COM40"]
