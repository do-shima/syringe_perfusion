from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import shutil
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

from .perfusion_state import invalidate_armed, read_state
from .profiles import ul_per_mm_from_inner_diameter


SYRINGE_SCHEMA_VERSION = 2
MAX_NOMINAL_VOLUME_ML = 150.0
CSV_FIELDS = (
    "key",
    "display_name",
    "manufacturer",
    "model",
    "physical_label",
    "nominal_volume_ml",
    "nominal_inner_diameter_mm",
    "nominal_ul_per_mm",
    "calibrated_ul_per_mm",
    "calibration_date",
    "calibration_method",
    "calibration_validation_id",
    "replicate_count",
    "coefficient_of_variation_percent",
    "mean_error_percent",
    "maximum_usable_stroke_mm",
    "notes",
    "active",
)
NUMERIC_FIELDS = {
    "nominal_volume_ml",
    "nominal_inner_diameter_mm",
    "nominal_ul_per_mm",
    "calibrated_ul_per_mm",
    "coefficient_of_variation_percent",
    "mean_error_percent",
    "maximum_usable_stroke_mm",
}
KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,79}$")
ConflictChoice = Literal["create_new", "update", "skip"]


@dataclass(frozen=True)
class ImportRecord:
    source_key: str
    key: str
    record: dict[str, Any]
    default_action: ConflictChoice
    calibration_changed: bool
    affects_selected: bool


@dataclass(frozen=True)
class ImportPreview:
    records: tuple[ImportRecord, ...]
    errors: tuple[str, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "create": sum(item.default_action == "create_new" for item in self.records),
            "update": sum(item.default_action == "update" for item in self.records),
            "skip": sum(item.default_action == "skip" for item in self.records),
            "errors": len(self.errors),
        }


def load_syringe_document(config_dir: str | Path) -> dict[str, Any]:
    path = Path(config_dir).resolve() / "syringes.json"
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict) or not isinstance(document.get("syringes"), dict):
        raise ValueError("syringes.json must contain a syringes object")
    return document


def calibration_basis(record: Mapping[str, Any]) -> dict[str, Any]:
    calibrated = _optional_positive(record.get("calibrated_ul_per_mm"))
    if calibrated is not None:
        stale = bool(record.get("calibration_stale", False))
        return {
            "kind": "calibration_stale" if stale else "calibrated",
            "ul_per_mm": calibrated,
            "measured": True,
        }
    nominal = _optional_positive(record.get("nominal_ul_per_mm"))
    if nominal is None:
        diameter = _optional_positive(record.get("nominal_inner_diameter_mm"))
        if diameter is not None:
            nominal = ul_per_mm_from_inner_diameter(diameter)
    if nominal is not None:
        return {"kind": "nominal_only", "ul_per_mm": nominal, "measured": False}
    return {"kind": "missing", "ul_per_mm": None, "measured": False}


def syringe_display_name(key: str, record: Mapping[str, Any]) -> str:
    manufacturer = str(record.get("manufacturer", "")).strip()
    nominal = _optional_positive(record.get("nominal_volume_ml"))
    label = str(record.get("physical_label", "")).strip()
    if manufacturer and nominal is not None:
        base = f"{manufacturer} {nominal:g} mL"
    else:
        base = str(record.get("display_name") or key)
    if label:
        base += f" — {label}"
    return base


def validate_syringe_record(
    key: str,
    record: Mapping[str, Any],
    *,
    require_nominal_volume: bool = True,
) -> dict[str, Any]:
    clean_key = str(key).strip()
    if not KEY_PATTERN.fullmatch(clean_key):
        raise ValueError(f"invalid syringe key: {clean_key!r}")
    normalized = deepcopy(dict(record))
    normalized["key"] = clean_key
    volume = _optional_positive(normalized.get("nominal_volume_ml"))
    if volume is None:
        if require_nominal_volume:
            raise ValueError(f"{clean_key}: nominal_volume_ml must be positive")
    elif volume > MAX_NOMINAL_VOLUME_ML:
        raise ValueError(
            f"{clean_key}: nominal_volume_ml must not exceed {MAX_NOMINAL_VOLUME_ML:g}"
        )
    else:
        normalized["nominal_volume_ml"] = volume
    diameter = _optional_positive(normalized.get("nominal_inner_diameter_mm"))
    nominal_conversion = _optional_positive(normalized.get("nominal_ul_per_mm"))
    if diameter is not None:
        normalized["nominal_inner_diameter_mm"] = diameter
        if nominal_conversion is None:
            normalized["nominal_ul_per_mm"] = ul_per_mm_from_inner_diameter(diameter)
    elif nominal_conversion is not None:
        normalized["nominal_ul_per_mm"] = nominal_conversion
    calibrated = _optional_positive(normalized.get("calibrated_ul_per_mm"))
    if normalized.get("calibrated_ul_per_mm") not in (None, "") and calibrated is None:
        raise ValueError(f"{clean_key}: calibrated_ul_per_mm must be positive")
    normalized["calibrated_ul_per_mm"] = calibrated
    stroke = _optional_positive(normalized.get("maximum_usable_stroke_mm"))
    if normalized.get("maximum_usable_stroke_mm") not in (None, "") and stroke is None:
        raise ValueError(f"{clean_key}: maximum_usable_stroke_mm must be positive")
    normalized["maximum_usable_stroke_mm"] = stroke
    replicate_count = normalized.get("replicate_count")
    if replicate_count not in (None, ""):
        count = int(replicate_count)
        if count < 0:
            raise ValueError(f"{clean_key}: replicate_count must not be negative")
        normalized["replicate_count"] = count
    normalized.setdefault("display_name", clean_key)
    normalized.setdefault("manufacturer", "")
    normalized.setdefault("model", "")
    normalized.setdefault("physical_label", "")
    normalized.setdefault("calibration_date", "")
    normalized.setdefault("calibration_method", "")
    normalized.setdefault("calibration_validation_id", "")
    normalized.setdefault("notes", normalized.get("calibration_note", ""))
    normalized["active"] = _parse_bool(normalized.get("active", True))
    return normalized


def validate_library_document(document: Mapping[str, Any]) -> dict[str, Any]:
    raw = document.get("syringes")
    if not isinstance(raw, Mapping):
        raise ValueError("syringe document must contain a syringes object")
    result = deepcopy(dict(document))
    result["schema_version"] = max(int(result.get("schema_version", 1)), SYRINGE_SCHEMA_VERSION)
    validated: dict[str, Any] = {}
    for key, record in raw.items():
        if not isinstance(record, Mapping):
            raise ValueError(f"{key}: syringe record must be an object")
        normalized = validate_syringe_record(str(key), record, require_nominal_volume=False)
        normalized.pop("key", None)
        validated[str(key)] = normalized
    result["syringes"] = validated
    return result


def parse_import_json(text: str) -> list[dict[str, Any]]:
    value = json.loads(text)
    if isinstance(value, Mapping) and isinstance(value.get("syringes"), Mapping):
        rows = [{"key": key, **dict(record)} for key, record in value["syringes"].items()]
    elif isinstance(value, list):
        rows = [dict(item) for item in value if isinstance(item, Mapping)]
        if len(rows) != len(value):
            raise ValueError("every JSON list item must be an object")
    elif isinstance(value, Mapping):
        rows = [dict(value)]
    else:
        raise ValueError("JSON import must be a syringe object, list, or syringes document")
    return rows


def parse_import_csv(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "key" not in reader.fieldnames:
        raise ValueError("CSV import requires a key column")
    rows: list[dict[str, Any]] = []
    for raw in reader:
        row: dict[str, Any] = {}
        for key, value in raw.items():
            clean = (value or "").strip()
            if not clean:
                row[key] = None if key in NUMERIC_FIELDS else ""
            elif key in NUMERIC_FIELDS:
                row[key] = float(clean)
            elif key == "replicate_count":
                row[key] = int(clean)
            elif key == "active":
                row[key] = _parse_bool(clean)
            else:
                row[key] = clean
        rows.append(row)
    return rows


def preview_import(
    current_document: Mapping[str, Any],
    imported: Iterable[Mapping[str, Any]],
    *,
    selected_keys: Iterable[str] = (),
) -> ImportPreview:
    current = current_document.get("syringes")
    if not isinstance(current, Mapping):
        raise ValueError("current syringe document is malformed")
    selected = {str(key) for key in selected_keys}
    records: list[ImportRecord] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(imported, start=1):
        source_key = str(raw.get("key", "")).strip()
        try:
            normalized = validate_syringe_record(source_key, raw, require_nominal_volume=True)
            key = normalized.pop("key")
            if key in seen:
                raise ValueError(f"duplicate imported key: {key}")
            seen.add(key)
            existing = current.get(key)
            action: ConflictChoice = "update" if isinstance(existing, Mapping) else "create_new"
            calibration_changed = bool(
                isinstance(existing, Mapping)
                and existing.get("calibrated_ul_per_mm") != normalized.get("calibrated_ul_per_mm")
            )
            records.append(
                ImportRecord(
                    source_key=source_key,
                    key=key,
                    record=normalized,
                    default_action=action,
                    calibration_changed=calibration_changed,
                    affects_selected=key in selected,
                )
            )
        except (TypeError, ValueError) as exc:
            errors.append(f"row {index}: {exc}")
    return ImportPreview(tuple(records), tuple(errors))


def apply_import(
    config_dir: str | Path,
    preview: ImportPreview,
    *,
    choices: Mapping[str, ConflictChoice] | None = None,
    selected_keys: Iterable[str] = (),
    source_name: str = "",
    imported_at: str | None = None,
) -> dict[str, Any]:
    if preview.errors:
        raise ValueError("import preview contains validation errors")
    root = Path(config_dir).resolve()
    path = root / "syringes.json"
    document = load_syringe_document(root)
    syringes = document["syringes"]
    selected = {str(key) for key in selected_keys}
    applied: list[str] = []
    skipped: list[str] = []
    affected_selected: list[str] = []
    now = imported_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    for item in preview.records:
        action = (choices or {}).get(item.key, item.default_action)
        if action == "skip":
            skipped.append(item.key)
            continue
        target_key = item.key
        if action == "create_new" and target_key in syringes:
            target_key = _next_available_key(target_key, syringes)
        elif action == "update" and target_key not in syringes:
            raise ValueError(f"cannot update missing syringe: {target_key}")
        elif action not in {"create_new", "update"}:
            raise ValueError(f"unsupported conflict choice for {item.key}: {action}")
        incoming = deepcopy(item.record)
        provenance = incoming.get("import_provenance")
        history = list(provenance) if isinstance(provenance, list) else []
        history.append({"imported_at": now, "source": source_name, "source_key": item.source_key})
        incoming["import_provenance"] = history
        if action == "update":
            existing = syringes[target_key]
            if not isinstance(existing, dict):
                raise ValueError(f"existing syringe is malformed: {target_key}")
            existing.update(incoming)
        else:
            syringes[target_key] = incoming
        applied.append(target_key)
        if target_key in selected:
            affected_selected.append(target_key)
    if not applied:
        return {"path": path, "applied": [], "skipped": skipped, "invalidated": False}
    document["schema_version"] = max(int(document.get("schema_version", 1)), SYRINGE_SCHEMA_VERSION)
    backup = _backup_path(path, now)
    shutil.copy2(path, backup)
    _atomic_json(path, document)
    invalidated = bool(affected_selected)
    if invalidated:
        invalidate_armed(root, "active syringe library record changed")
    return {
        "path": path,
        "backup": backup,
        "applied": applied,
        "skipped": skipped,
        "affected_selected": affected_selected,
        "invalidated": invalidated,
    }


def armed_syringe_keys(config_dir: str | Path) -> set[str]:
    state = read_state(config_dir) or {}
    plan = state.get("plan") if isinstance(state.get("plan"), Mapping) else {}
    pumps = plan.get("pumps") if isinstance(plan.get("pumps"), Mapping) else {}
    return {
        str(pump.get("syringe_key"))
        for pump in pumps.values()
        if isinstance(pump, Mapping) and pump.get("syringe_key")
    }


def export_library_json(config_dir: str | Path, output: str | Path) -> Path:
    document = validate_library_document(load_syringe_document(config_dir))
    path = Path(output).resolve()
    _atomic_json(path, document)
    return path


def export_library_csv(config_dir: str | Path, output: str | Path) -> Path:
    document = validate_library_document(load_syringe_document(config_dir))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for key in sorted(document["syringes"]):
        record = document["syringes"][key]
        writer.writerow({"key": key, **{field: record.get(field, "") for field in CSV_FIELDS if field != "key"}})
    path = Path(output).resolve()
    _atomic_text(path, stream.getvalue())
    return path


def validate_large_syringe_use(
    record: Mapping[str, Any],
    *,
    required_travel_mm: float,
    speed_mm_min: float,
    duration_s: float,
) -> list[str]:
    warnings: list[str] = []
    volume = _optional_positive(record.get("nominal_volume_ml"))
    if volume is not None and volume > MAX_NOMINAL_VOLUME_ML:
        raise ValueError(f"nominal syringe capacity exceeds {MAX_NOMINAL_VOLUME_ML:g} mL")
    if duration_s <= 0:
        raise ValueError("programmed duration must be positive")
    if speed_mm_min <= 0:
        raise ValueError("programmed speed must be positive")
    maximum_stroke = _optional_positive(record.get("maximum_usable_stroke_mm"))
    if maximum_stroke is not None and required_travel_mm > maximum_stroke + 1e-9:
        raise ValueError(
            f"required travel {required_travel_mm:.3f} mm exceeds maximum usable stroke "
            f"{maximum_stroke:.3f} mm"
        )
    if volume is not None and volume >= 20:
        for field, label in (
            ("pump_fit_validated", "pump fit"),
            ("clamp_compatibility_validated", "clamp compatibility"),
            ("force_validated", "required force"),
            ("stroke_validated", "usable stroke"),
        ):
            if not bool(record.get(field, False)):
                warnings.append(f"large-syringe {label} is not commissioned")
    return warnings


def max_expected_volume_ml(record: Mapping[str, Any]) -> float | None:
    stroke = _optional_positive(record.get("maximum_usable_stroke_mm"))
    basis = calibration_basis(record)
    conversion = basis.get("ul_per_mm")
    if stroke is None or conversion is None:
        return None
    return stroke * float(conversion) / 1000.0


def _optional_positive(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or result <= 0:
        return None
    return result


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return True
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _next_available_key(base: str, syringes: Mapping[str, Any]) -> str:
    index = 2
    while f"{base}_{index}" in syringes:
        index += 1
    return f"{base}_{index}"


def _backup_path(path: Path, timestamp: str) -> Path:
    stamp = re.sub(r"[^0-9]", "", timestamp)[:14] or "backup"
    candidate = path.with_name(f"{path.name}.{stamp}.bak")
    index = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{stamp}.{index}.bak")
        index += 1
    return candidate


def _atomic_json(path: Path, data: Mapping[str, Any]) -> None:
    _atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
