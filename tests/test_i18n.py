from __future__ import annotations

import json
import re
import warnings
from pathlib import Path

from syringe_perfusion.i18n import (
    DISPLAY_VALUE_KEYS,
    Localizer,
    detect_system_language,
    load_catalog,
    locale_resource_directories,
    validate_catalog_pair,
)


def test_english_and_japanese_catalogs_have_matching_keys_and_placeholders() -> None:
    english = load_catalog("en")
    japanese = load_catalog("ja")
    assert validate_catalog_pair(english, japanese) == []
    assert len(english) >= 190
    assert japanese["action.stop_all"] == "全停止"
    assert japanese["label.programmed_not_read"] == "設定送信済み — 読み戻し未確認"
    assert japanese["state.stop_failed"] == "停止失敗"


def test_locale_detection_and_saved_preference_resolution() -> None:
    assert detect_system_language("ja_JP") == "ja"
    assert detect_system_language("Japanese_Japan.932") == "ja"
    assert detect_system_language("en_US") == "en"
    assert Localizer("auto", locale_name="ja-JP").language == "ja"
    assert Localizer("en", locale_name="ja-JP").language == "en"


def test_missing_key_falls_back_safely_and_warns_once() -> None:
    localizer = Localizer("ja")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        assert localizer.t("development.missing") == "development.missing"
        assert localizer.t("development.missing") == "development.missing"
    assert len(captured) == 1


def test_malformed_japanese_catalog_falls_back_to_english(tmp_path: Path) -> None:
    english = load_catalog("en")
    (tmp_path / "en.json").write_text(json.dumps(english), encoding="utf-8")
    (tmp_path / "ja.json").write_text("{broken", encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        localizer = Localizer("ja", resource_directories=[tmp_path])
    assert localizer.t("action.stop_all") == "STOP ALL"


def test_display_mapping_is_reversible_and_preserves_canonical_value() -> None:
    localizer = Localizer("ja")
    for canonical in DISPLAY_VALUE_KEYS:
        display = localizer.display_value(canonical)
        assert localizer.canonical_value(display, DISPLAY_VALUE_KEYS) == canonical


def test_japanese_utf8_and_frozen_resource_candidate(monkeypatch, tmp_path: Path) -> None:
    assert "灌流" in load_catalog("ja")["card.perfusion_setpoint"]
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)
    candidates = locale_resource_directories()
    assert tmp_path / "syringe_perfusion" / "locales" in candidates
    assert tmp_path / "locales" in candidates


def test_all_explicit_gui_translation_keys_resolve_and_specs_bundle_catalogs() -> None:
    root = Path(__file__).resolve().parents[1]
    english = load_catalog("en")
    sources = (
        root / "syringe_perfusion" / "gui.py",
        root / "syringe_perfusion" / "gui_commissioning.py",
        root / "syringe_perfusion" / "gui_history.py",
        root / "syringe_perfusion" / "gui_recipe.py",
    )
    keys: set[str] = set()
    for path in sources:
        keys.update(re.findall(r"(?:self|app)\.t\([\"']([^\"']+)", path.read_text(encoding="utf-8")))
    assert keys
    assert keys <= set(english)
    for spec in (root / "A4PumpGUI.spec", root / "a4ctl.spec"):
        assert "syringe_perfusion/locales" in spec.read_text(encoding="utf-8")
