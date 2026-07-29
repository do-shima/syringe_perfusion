from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .a4 import format_settings_commands
from .profiles import MAX_SPEED_MM_MIN, MIN_SPEED_MM_MIN, ul_per_mm_from_inner_diameter


MAX_DURATION_S = (99 * 3600) + (59 * 60) + 59
MODES = {"fixed_volume", "fixed_duration", "bounded_continuous"}


@dataclass(frozen=True)
class PumpSetpoint:
    pump: str
    direction: str
    syringe_key: str
    ul_per_mm: float
    requested_flow_ml_min: float
    programmed_speed_mm_min: float
    estimated_actual_flow_ml_min: float
    programmed_duration_s: int
    expected_volume_ml: float
    flow_difference_ml_min: float
    uart_commands: list[str]


@dataclass(frozen=True)
class PerfusionSetpoint:
    mode: str
    requested_in_flow_ml_min: float
    requested_out_flow_ml_min: float
    target_in_volume_ml: float | None
    requested_duration_s: float
    programmed_duration_s: int
    out_ratio_locked: bool
    out_in_ratio: float | None
    in_to_out_delay_s: float
    requested_start_delay_s: float
    in_setpoint: PumpSetpoint
    out_setpoint: PumpSetpoint
    warning: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calibrated_ul_per_mm(syringe: dict[str, Any]) -> float:
    value = syringe.get("calibrated_ul_per_mm")
    if value is None:
        value = ul_per_mm_from_inner_diameter(float(syringe["nominal_inner_diameter_mm"]))
    value = float(value)
    if value <= 0:
        raise ValueError("syringe ul_per_mm must be positive")
    return value


def quantize_speed(speed_mm_min: float) -> float:
    value = float(Decimal(str(speed_mm_min)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    # Reuse the protocol formatter as the authoritative device-range validation.
    format_settings_commands(value, 1, save=True)
    return value


def quantize_duration(duration_s: float) -> int:
    value = int(Decimal(str(duration_s)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if value < 1 or value > MAX_DURATION_S:
        raise ValueError("duration_s must be between 1 and 99:59:59")
    return value


def speed_for_flow(flow_ml_min: float, ul_per_mm: float) -> float:
    if flow_ml_min <= 0:
        raise ValueError("flow_ml_min must be positive")
    speed = flow_ml_min * 1000.0 / ul_per_mm
    if speed < MIN_SPEED_MM_MIN or speed > MAX_SPEED_MM_MIN:
        raise ValueError(
            f"calculated speed {speed:.4f} mm/min is outside "
            f"{MIN_SPEED_MM_MIN:.2f}-{MAX_SPEED_MM_MIN:.2f} mm/min"
        )
    return speed


def flow_for_speed(speed_mm_min: float, ul_per_mm: float) -> float:
    return speed_mm_min * ul_per_mm / 1000.0


def build_perfusion_setpoint(
    config_data: dict[str, Any],
    *,
    mode: str,
    in_flow_ml_min: float,
    in_syringe_key: str,
    out_syringe_key: str,
    target_volume_ml: float | None = None,
    duration_s: float | None = None,
    maximum_duration_s: float | None = None,
    out_ratio_locked: bool = True,
    out_in_ratio: float = 1.0,
    independent_out_flow_ml_min: float | None = None,
    in_to_out_delay_s: float = 0.5,
    requested_start_delay_s: float = 0.0,
) -> PerfusionSetpoint:
    if mode not in MODES:
        raise ValueError(f"unsupported perfusion mode: {mode}")
    if in_flow_ml_min <= 0:
        raise ValueError("IN flow must be positive")
    if in_to_out_delay_s < 0:
        raise ValueError("IN-to-OUT delay must be zero or positive")
    if requested_start_delay_s < 0:
        raise ValueError("start delay must be zero or positive")
    try:
        in_syringe = config_data["syringes"][in_syringe_key]
        out_syringe = config_data["syringes"][out_syringe_key]
    except KeyError as exc:
        raise ValueError(f"unknown syringe: {exc.args[0]}") from exc

    if mode == "fixed_volume":
        if target_volume_ml is None or target_volume_ml <= 0:
            raise ValueError("target volume must be positive in fixed-volume mode")
        requested_duration = target_volume_ml / in_flow_ml_min * 60.0
    elif mode == "fixed_duration":
        if duration_s is None or duration_s <= 0:
            raise ValueError("duration must be positive in fixed-duration mode")
        requested_duration = duration_s
    else:
        if maximum_duration_s is None or maximum_duration_s <= 0:
            raise ValueError("bounded-continuous mode requires a positive maximum duration")
        requested_duration = maximum_duration_s

    programmed_duration = quantize_duration(requested_duration)
    if out_ratio_locked:
        if out_in_ratio <= 0:
            raise ValueError("OUT/IN ratio must be positive")
        out_flow = in_flow_ml_min * out_in_ratio
        ratio: float | None = out_in_ratio
    else:
        if independent_out_flow_ml_min is None or independent_out_flow_ml_min <= 0:
            raise ValueError("independent OUT flow must be positive when ratio lock is disabled")
        out_flow = independent_out_flow_ml_min
        ratio = out_flow / in_flow_ml_min

    in_result = _pump_setpoint(
        "IN",
        "forward",
        in_syringe_key,
        calibrated_ul_per_mm(in_syringe),
        in_flow_ml_min,
        programmed_duration,
    )
    out_result = _pump_setpoint(
        "OUT",
        "reverse",
        out_syringe_key,
        calibrated_ul_per_mm(out_syringe),
        out_flow,
        programmed_duration,
    )
    warning = ""
    if abs(out_flow - in_flow_ml_min) > 1e-12:
        warning = "Unequal IN/OUT flow can change dish volume."
    return PerfusionSetpoint(
        mode=mode,
        requested_in_flow_ml_min=in_flow_ml_min,
        requested_out_flow_ml_min=out_flow,
        target_in_volume_ml=target_volume_ml if mode == "fixed_volume" else None,
        requested_duration_s=requested_duration,
        programmed_duration_s=programmed_duration,
        out_ratio_locked=out_ratio_locked,
        out_in_ratio=ratio,
        in_to_out_delay_s=in_to_out_delay_s,
        requested_start_delay_s=requested_start_delay_s,
        in_setpoint=in_result,
        out_setpoint=out_result,
        warning=warning,
    )


def _pump_setpoint(
    pump: str,
    direction: str,
    syringe_key: str,
    ul_per_mm: float,
    requested_flow: float,
    duration_s: int,
) -> PumpSetpoint:
    speed = quantize_speed(speed_for_flow(requested_flow, ul_per_mm))
    actual_flow = flow_for_speed(speed, ul_per_mm)
    expected_volume = actual_flow * duration_s / 60.0
    return PumpSetpoint(
        pump=pump,
        direction=direction,
        syringe_key=syringe_key,
        ul_per_mm=ul_per_mm,
        requested_flow_ml_min=requested_flow,
        programmed_speed_mm_min=speed,
        estimated_actual_flow_ml_min=actual_flow,
        programmed_duration_s=duration_s,
        expected_volume_ml=expected_volume,
        flow_difference_ml_min=actual_flow - requested_flow,
        uart_commands=format_settings_commands(speed, duration_s, save=True),
    )
