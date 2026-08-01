from __future__ import annotations

import json
from pathlib import Path

import pytest

from syringe_perfusion.config import REQUIRED_CONFIG_FILES, load_config
from syringe_perfusion.cli import main
from syringe_perfusion.flow_control import calibrated_ul_per_mm
from syringe_perfusion.operations import control_config_fingerprint
from syringe_perfusion.perfusion_state import read_state, write_state
from syringe_perfusion.syringe_library import (
    apply_import,
    calibration_basis,
    export_library_csv,
    export_library_json,
    load_syringe_document,
    max_expected_volume_ml,
    parse_import_csv,
    parse_import_json,
    preview_import,
    validate_large_syringe_use,
    validate_library_document,
    validate_syringe_record,
)


ROOT = Path(__file__).resolve().parents[1]


def active_config(tmp_path: Path) -> Path:
    root = tmp_path / "config"
    root.mkdir()
    for filename in REQUIRED_CONFIG_FILES:
        (root / filename).write_bytes((ROOT / "config" / filename).read_bytes())
    return root


def imported_record(key: str = "generic_50ml") -> dict:
    return {
        "key": key,
        "display_name": "Generic 50 mL",
        "manufacturer": "Generic",
        "model": "G50",
        "physical_label": "IN-A",
        "nominal_volume_ml": 50,
        "nominal_inner_diameter_mm": 28.0,
        "calibrated_ul_per_mm": None,
        "maximum_usable_stroke_mm": 55,
        "notes": "Fit and force not commissioned",
        "future_key": {"keep": True},
    }


def test_existing_schema_is_readable_and_nominal_is_distinct_from_calibration(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    document = validate_library_document(load_syringe_document(root))
    assert set(document["syringes"]) >= {"terumo_ss05lz_5ml", "generic_2_5ml", "generic_1ml"}
    nominal = calibration_basis(document["syringes"]["generic_2_5ml"])
    measured = calibration_basis(document["syringes"]["terumo_ss05lz_5ml"])
    assert nominal == pytest.approx({"kind": "nominal_only", "ul_per_mm": 78.53981633974483, "measured": False})
    assert measured["kind"] == "calibrated"
    assert measured["measured"] is True


def test_json_csv_import_and_preview_do_not_write(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    path = root / "syringes.json"
    before = path.read_bytes()
    json_rows = parse_import_json(json.dumps({"syringes": {"generic_50ml": imported_record()}}))
    preview = preview_import(load_syringe_document(root), json_rows)
    assert preview.counts == {"create": 1, "update": 0, "skip": 0, "errors": 0}
    assert path.read_bytes() == before

    csv_text = (
        "key,display_name,manufacturer,model,physical_label,nominal_volume_ml,"
        "nominal_inner_diameter_mm,calibrated_ul_per_mm\n"
        "generic_60ml,Generic 60 mL,Generic,G60,OUT-B,60,29.0,\n"
    )
    csv_rows = parse_import_csv(csv_text)
    assert csv_rows[0]["nominal_volume_ml"] == 60.0
    assert preview_import(load_syringe_document(root), csv_rows).counts["create"] == 1
    assert path.read_bytes() == before


def test_conflict_resolution_atomic_backup_unknown_keys_and_selective_invalidation(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    document = load_syringe_document(root)
    selected_key = "terumo_ss05lz_5ml"
    state = {"state": "ARMED", "plan": {"pumps": {"IN": {"syringe_key": selected_key}}}}
    write_state(root, state)
    update = {"key": selected_key, **document["syringes"][selected_key], "notes": "updated", "future": 7}
    preview = preview_import(document, [update], selected_keys={selected_key})
    result = apply_import(root, preview, selected_keys={selected_key}, source_name="test.json")
    assert result["invalidated"]
    assert result["backup"].is_file()
    assert read_state(root)["state"] == "DIRTY"
    saved = load_syringe_document(root)["syringes"][selected_key]
    assert saved["future"] == 7
    assert saved["import_provenance"][-1]["source"] == "test.json"

    write_state(root, state)
    unrelated = imported_record("unrelated_50ml")
    preview2 = preview_import(load_syringe_document(root), [unrelated], selected_keys={selected_key})
    result2 = apply_import(root, preview2, selected_keys={selected_key}, source_name="other.csv")
    assert not result2["invalidated"]
    assert read_state(root)["state"] == "ARMED"


def test_create_as_new_and_skip_conflict_choices(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    document = load_syringe_document(root)
    key = "generic_2_5ml"
    row = {"key": key, **document["syringes"][key], "nominal_volume_ml": 2.5}
    preview = preview_import(document, [row])
    created = apply_import(root, preview, choices={key: "create_new"})
    assert created["applied"] == [f"{key}_2"]
    skipped = apply_import(root, preview, choices={key: "skip"})
    assert skipped["applied"] == []


def test_capacity_limit_nominal_derivation_and_large_syringe_limits() -> None:
    valid = validate_syringe_record("large_150", {**imported_record(), "nominal_volume_ml": 150})
    assert valid["nominal_ul_per_mm"] > 0
    with pytest.raises(ValueError, match="150"):
        validate_syringe_record("too_large", {**imported_record(), "nominal_volume_ml": 150.1})
    warnings = validate_large_syringe_use(
        valid,
        required_travel_mm=50,
        speed_mm_min=10,
        duration_s=300,
    )
    assert {"pump fit", "clamp compatibility", "required force", "usable stroke"} <= {
        item.removeprefix("large-syringe ").removesuffix(" is not commissioned") for item in warnings
    }
    with pytest.raises(ValueError, match="exceeds maximum usable stroke"):
        validate_large_syringe_use(valid, required_travel_mm=56, speed_mm_min=10, duration_s=300)
    assert max_expected_volume_ml(valid) == pytest.approx(
        valid["maximum_usable_stroke_mm"] * valid["nominal_ul_per_mm"] / 1000
    )


def test_nominal_conversion_is_supported_but_never_replaces_calibration() -> None:
    nominal = {"nominal_volume_ml": 50, "nominal_ul_per_mm": 999.0}
    assert calibrated_ul_per_mm(nominal) == pytest.approx(999.0)
    measured = {**nominal, "calibrated_ul_per_mm": 1001.5}
    assert calibrated_ul_per_mm(measured) == pytest.approx(1001.5)


def test_exports_round_trip_and_preserve_provenance(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    row = imported_record()
    preview = preview_import(load_syringe_document(root), [row])
    apply_import(root, preview, source_name="source.json")
    json_path = export_library_json(root, tmp_path / "library.json")
    csv_path = export_library_csv(root, tmp_path / "library.csv")
    exported = json.loads(json_path.read_text(encoding="utf-8"))
    assert exported["syringes"]["generic_50ml"]["future_key"] == {"keep": True}
    assert exported["syringes"]["generic_50ml"]["import_provenance"]
    rows = parse_import_csv(csv_path.read_text(encoding="utf-8"))
    assert any(item["key"] == "generic_50ml" for item in rows)


def test_armed_control_fingerprint_ignores_unrelated_syringe_but_not_selected_change(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    data = load_config(root)
    key = "terumo_ss05lz_5ml"
    plan = {"pumps": {"IN": {"syringe_key": key}, "OUT": {"syringe_key": key}}}
    original = control_config_fingerprint(data, plan)
    data["syringes"]["unrelated"] = imported_record("unrelated")
    assert control_config_fingerprint(data, plan) == original
    data["syringes"][key]["calibrated_ul_per_mm"] = 999
    assert control_config_fingerprint(data, plan) != original


@pytest.mark.parametrize(
    "arguments",
    (
        ["syringe-list", "--json"],
        ["syringe-show", "terumo_ss05lz_5ml", "--json"],
        ["syringe-library-status", "--json"],
    ),
)
def test_read_only_syringe_cli_never_constructs_a_pump(
    tmp_path: Path,
    monkeypatch,
    arguments: list[str],
) -> None:
    root = active_config(tmp_path)
    constructed: list[bool] = []
    monkeypatch.setattr(
        "syringe_perfusion.a4.A4Pump.__init__",
        lambda *_args, **_kwargs: constructed.append(True),
    )
    assert main(["--config-dir", str(root), *arguments]) == 0
    assert constructed == []
