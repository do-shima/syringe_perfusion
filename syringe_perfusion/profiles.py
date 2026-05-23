from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


MIN_SPEED_MM_MIN = 0.01
MAX_SPEED_MM_MIN = 150.0


@dataclass(frozen=True)
class CalculationResult:
    mode: str
    ul_per_mm: float
    required_travel_mm: float | None = None
    speed_mm_min: float | None = None
    duration_s: float | None = None
    target_volume_ul: float | None = None
    estimated_volume_ul: float | None = None
    flow_ml_min: float | None = None
    warning: str = ""


def ul_per_mm_from_inner_diameter(inner_diameter_mm: float) -> float:
    if inner_diameter_mm <= 0:
        raise ValueError("inner_diameter_mm must be positive")
    radius_mm = inner_diameter_mm / 2.0
    return math.pi * radius_mm * radius_mm


def required_travel_mm(volume_ul: float, ul_per_mm: float) -> float:
    _require_positive("volume_ul", volume_ul)
    _require_positive("ul_per_mm", ul_per_mm)
    return volume_ul / ul_per_mm


def speed_mm_min_for_volume_duration(
    volume_ul: float, duration_s: float, ul_per_mm: float
) -> float:
    _require_positive("duration_s", duration_s)
    travel_mm = required_travel_mm(volume_ul, ul_per_mm)
    speed = travel_mm / (duration_s / 60.0)
    validate_speed(speed)
    return speed


def volume_ul_for_speed_duration(
    speed_mm_min: float, duration_s: float, ul_per_mm: float
) -> float:
    validate_speed(speed_mm_min)
    _require_positive("duration_s", duration_s)
    _require_positive("ul_per_mm", ul_per_mm)
    return speed_mm_min * (duration_s / 60.0) * ul_per_mm


def validate_speed(speed_mm_min: float) -> None:
    if not (MIN_SPEED_MM_MIN <= speed_mm_min <= MAX_SPEED_MM_MIN):
        raise ValueError(
            f"speed_mm_min must be between {MIN_SPEED_MM_MIN} and {MAX_SPEED_MM_MIN}"
        )


def calculate(
    mode: str,
    ul_per_mm: float,
    *,
    volume_ul: float | None = None,
    duration_s: float | None = None,
    flow_ml_min: float | None = None,
    speed_mm_min: float | None = None,
    syringe_key: str | None = None,
) -> CalculationResult:
    if mode == "volume_duration":
        _require_present("volume_ul", volume_ul)
        _require_present("duration_s", duration_s)
        speed = speed_mm_min_for_volume_duration(volume_ul, duration_s, ul_per_mm)
        travel = required_travel_mm(volume_ul, ul_per_mm)
        return CalculationResult(
            mode=mode,
            ul_per_mm=ul_per_mm,
            required_travel_mm=travel,
            speed_mm_min=speed,
            duration_s=duration_s,
            target_volume_ul=volume_ul,
            estimated_volume_ul=volume_ul,
            warning=recommended_fill_warning(syringe_key, volume_ul),
        )

    if mode == "volume_flow":
        _require_present("volume_ul", volume_ul)
        _require_present("flow_ml_min", flow_ml_min)
        _require_positive("flow_ml_min", flow_ml_min)
        duration = (volume_ul / 1000.0) / flow_ml_min * 60.0
        speed = speed_mm_min_for_volume_duration(volume_ul, duration, ul_per_mm)
        travel = required_travel_mm(volume_ul, ul_per_mm)
        return CalculationResult(
            mode=mode,
            ul_per_mm=ul_per_mm,
            required_travel_mm=travel,
            speed_mm_min=speed,
            duration_s=duration,
            target_volume_ul=volume_ul,
            estimated_volume_ul=volume_ul,
            flow_ml_min=flow_ml_min,
            warning=recommended_fill_warning(syringe_key, volume_ul),
        )

    if mode == "speed_duration":
        _require_present("speed_mm_min", speed_mm_min)
        _require_present("duration_s", duration_s)
        volume = volume_ul_for_speed_duration(speed_mm_min, duration_s, ul_per_mm)
        travel = speed_mm_min * (duration_s / 60.0)
        return CalculationResult(
            mode=mode,
            ul_per_mm=ul_per_mm,
            required_travel_mm=travel,
            speed_mm_min=speed_mm_min,
            duration_s=duration_s,
            target_volume_ul=volume_ul,
            estimated_volume_ul=volume,
            warning=recommended_fill_warning(syringe_key, volume_ul or volume),
        )

    raise ValueError(f"unsupported mode: {mode}")


def calculate_profile(profile: dict[str, Any], syringe: dict[str, Any], syringe_key: str) -> CalculationResult:
    ul_per_mm = syringe.get("calibrated_ul_per_mm")
    if ul_per_mm is None:
        ul_per_mm = ul_per_mm_from_inner_diameter(syringe["nominal_inner_diameter_mm"])
    return calculate(
        profile["mode"],
        float(ul_per_mm),
        volume_ul=_optional_float(profile.get("target_volume_ul")),
        duration_s=_optional_float(profile.get("duration_s")),
        flow_ml_min=_optional_float(profile.get("flow_ml_min")),
        speed_mm_min=_optional_float(profile.get("speed_mm_min")),
        syringe_key=syringe_key,
    )


def recommended_fill_warning(syringe_key: str | None, target_volume_ul: float | None) -> str:
    if syringe_key != "terumo_ss05lz_5ml" or target_volume_ul is None or target_volume_ul <= 0:
        return ""
    recommended_ul = 1000.0 + target_volume_ul + 200.0
    return (
        "5 mL syringe recommended fill: prime 1000 uL + target "
        f"{target_volume_ul:.0f} uL + margin 200 uL = about {recommended_ul:.0f} uL"
    )


def result_to_dict(result: CalculationResult) -> dict[str, Any]:
    return {
        "mode": result.mode,
        "ul_per_mm": result.ul_per_mm,
        "required_travel_mm": result.required_travel_mm,
        "speed_mm_min": result.speed_mm_min,
        "duration_s": result.duration_s,
        "target_volume_ul": result.target_volume_ul,
        "estimated_volume_ul": result.estimated_volume_ul,
        "flow_ml_min": result.flow_ml_min,
        "warning": result.warning,
    }


def _require_present(name: str, value: float | None) -> None:
    if value is None:
        raise ValueError(f"{name} is required")
    _require_positive(name, value)


def _require_positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
