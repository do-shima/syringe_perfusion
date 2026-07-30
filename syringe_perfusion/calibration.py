from __future__ import annotations

import json
import math
import os
import shutil
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .coordinator import OperationCoordinator


DEFAULT_ACCEPTANCE = {
    "minimum_replicates": 3,
    "maximum_cv_percent": 5.0,
    "maximum_abs_mean_flow_error_percent": 5.0,
}
STANDARD_FLOW_POINTS = (0.5, 1.0, 2.0, 3.0)


def direct_volume_ul(value: float, unit: str) -> float:
    amount = float(value)
    if amount <= 0:
        raise ValueError("measured volume must be positive")
    factors = {"ul": 1.0, "µl": 1.0, "μl": 1.0, "ml": 1000.0}
    try:
        return amount * factors[unit.strip().casefold()]
    except KeyError as exc:
        raise ValueError(f"unsupported volume unit: {unit}") from exc


def gravimetric_volume_ul(
    initial_mass: float,
    final_mass: float,
    *,
    mass_unit: str,
    density_g_ml: float,
) -> float:
    density = float(density_g_ml)
    if density <= 0:
        raise ValueError("liquid density must be positive")
    factors = {"g": 1.0, "mg": 0.001, "kg": 1000.0}
    try:
        mass_g = abs(float(final_mass) - float(initial_mass)) * factors[mass_unit.casefold()]
    except KeyError as exc:
        raise ValueError(f"unsupported mass unit: {mass_unit}") from exc
    if mass_g <= 0:
        raise ValueError("mass difference must be positive")
    return mass_g / density * 1000.0


def calculate_replicate(
    *,
    measured_volume_ul: float,
    requested_flow_ml_min: float,
    programmed_speed_mm_min: float,
    programmed_duration_s: float,
    pump_role: str,
    direction: str,
    syringe_key: str,
    operator: str,
    timestamp: str | None = None,
    note: str = "",
    method: str = "direct_volume",
    density_g_ml: float | None = None,
) -> dict[str, Any]:
    volume = float(measured_volume_ul)
    duration = float(programmed_duration_s)
    speed = float(programmed_speed_mm_min)
    requested = float(requested_flow_ml_min)
    travel = speed * duration / 60.0
    if volume <= 0:
        raise ValueError("measured volume must be positive")
    if duration <= 0:
        raise ValueError("programmed duration must be positive")
    if travel <= 0:
        raise ValueError("programmed travel must be positive")
    if requested <= 0:
        raise ValueError("requested flow must be positive")
    measured_flow = volume / (duration / 60.0) / 1000.0
    flow_error = measured_flow - requested
    return {
        "pump_role": pump_role,
        "direction": direction,
        "syringe_key": syringe_key,
        "requested_flow_ml_min": requested,
        "programmed_speed_mm_min": speed,
        "programmed_duration_s": duration,
        "programmed_travel_mm": travel,
        "expected_volume_ul": requested * duration / 60.0 * 1000.0,
        "measured_volume_ul": volume,
        "measured_flow_ml_min": measured_flow,
        "absolute_error_ml_min": abs(flow_error),
        "percent_error": flow_error / requested * 100.0,
        "candidate_ul_per_mm": volume / travel,
        "measurement_method": method,
        "density_g_ml": density_g_ml,
        "timestamp": timestamp or _now_iso(),
        "operator": operator,
        "note": note,
        "excluded": False,
        "exclusion_reason": "",
    }


def exclude_replicate(replicate: dict[str, Any], reason: str) -> dict[str, Any]:
    if not reason.strip():
        raise ValueError("an exclusion reason is required")
    return {**replicate, "excluded": True, "exclusion_reason": reason.strip()}


def calibration_statistics(
    replicates: Iterable[dict[str, Any]],
    *,
    criteria: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = {**DEFAULT_ACCEPTANCE, **(criteria or {})}
    all_replicates = list(replicates)
    accepted = [item for item in all_replicates if not item.get("excluded")]
    candidates = [float(item["candidate_ul_per_mm"]) for item in accepted]
    errors = [float(item["percent_error"]) for item in accepted]
    n = len(candidates)
    mean = statistics.fmean(candidates) if candidates else None
    standard_deviation = statistics.stdev(candidates) if n >= 2 else 0.0 if n == 1 else None
    cv = (
        standard_deviation / mean * 100.0
        if mean not in (None, 0) and standard_deviation is not None
        else None
    )
    mean_error = statistics.fmean(errors) if errors else None
    pass_replicates = n >= int(policy["minimum_replicates"])
    pass_cv = cv is not None and cv <= float(policy["maximum_cv_percent"])
    pass_error = (
        mean_error is not None
        and abs(mean_error) <= float(policy["maximum_abs_mean_flow_error_percent"])
    )
    return {
        "n": n,
        "mean": mean,
        "standard_deviation": standard_deviation,
        "coefficient_of_variation_percent": cv,
        "median": statistics.median(candidates) if candidates else None,
        "min": min(candidates) if candidates else None,
        "max": max(candidates) if candidates else None,
        "mean_percent_error": mean_error,
        "candidate_calibrated_ul_per_mm": mean,
        "criteria": policy,
        "accepted": pass_replicates and pass_cv and pass_error,
        "acceptance_checks": {
            "minimum_replicates": pass_replicates,
            "maximum_cv_percent": pass_cv,
            "maximum_abs_mean_flow_error_percent": pass_error,
        },
        "excluded_count": sum(1 for item in all_replicates if item.get("excluded")),
    }


def balance_result(
    *,
    requested_in_flow_ml_min: float,
    requested_out_flow_ml_min: float,
    duration_s: float,
    measured_in_volume_ml: float,
    measured_out_volume_ml: float,
    starting_dish_volume_ml: float | None = None,
    ending_dish_volume_ml: float | None = None,
) -> dict[str, Any]:
    duration_min = float(duration_s) / 60.0
    if duration_min <= 0:
        raise ValueError("duration must be positive")
    expected_in = float(requested_in_flow_ml_min) * duration_min
    expected_out = float(requested_out_flow_ml_min) * duration_min
    measured_in = float(measured_in_volume_ml)
    measured_out = float(measured_out_volume_ml)
    measured_net = measured_in - measured_out
    expected_net = expected_in - expected_out
    return {
        "expected_in_volume_ml": expected_in,
        "expected_out_volume_ml": expected_out,
        "measured_in_volume_ml": measured_in,
        "measured_out_volume_ml": measured_out,
        "measured_net_balance_ml": measured_net,
        "expected_net_balance_ml": expected_net,
        "balance_error_ml": measured_net - expected_net,
        "estimated_dish_volume_change_ml": (
            float(ending_dish_volume_ml) - float(starting_dish_volume_ml)
            if starting_dish_volume_ml is not None and ending_dish_volume_ml is not None
            else measured_net
        ),
        "dish_change_is_measured": (
            starting_dish_volume_ml is not None and ending_dish_volume_ml is not None
        ),
    }


def flow_point_status(replicates: Iterable[dict[str, Any]]) -> dict[str, str]:
    accepted = [item for item in replicates if not item.get("excluded")]
    result: dict[str, str] = {}
    for role, direction in (("IN", "forward"), ("OUT", "reverse")):
        for point in STANDARD_FLOW_POINTS:
            key = f"{role}_{direction}_{point:.1f}"
            matching = [
                item for item in accepted
                if item.get("pump_role") == role
                and item.get("direction") == direction
                and abs(float(item.get("requested_flow_ml_min", -1)) - point) < 1e-9
            ]
            result[key] = "MEASURED RESULT" if matching else "NOT VALIDATED"
    return result


def apply_syringe_calibration(
    config_dir: str | Path,
    *,
    syringe_key: str,
    candidate_ul_per_mm: float,
    validation_id: str,
    method: str,
    statistics_result: dict[str, Any],
    confirmed: bool,
    now: str | None = None,
) -> Path:
    if not confirmed:
        raise ValueError("explicit calibration confirmation is required")
    candidate = float(candidate_ul_per_mm)
    if not math.isfinite(candidate) or candidate <= 0:
        raise ValueError("candidate calibrated_ul_per_mm must be positive")
    root = Path(config_dir).resolve()
    path = root / "syringes.json"
    coordinator = OperationCoordinator(root)
    with coordinator.config_change_guard(
        f"syringe calibration updated: {syringe_key}"
    ):
        with path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        syringes = document.get("syringes")
        if not isinstance(syringes, dict) or not isinstance(syringes.get(syringe_key), dict):
            raise ValueError(f"unknown syringe preset: {syringe_key}")
        backup = path.with_name(path.name + ".bak")
        shutil.copy2(path, backup)
        preset = syringes[syringe_key]
        preset["calibrated_ul_per_mm"] = candidate
        preset["calibration_date"] = now or _now_iso()
        preset["calibration_method"] = method
        preset["calibration_validation_id"] = validation_id
        preset["calibration_statistics"] = statistics_result
        _atomic_json(path, document)
    return path


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
