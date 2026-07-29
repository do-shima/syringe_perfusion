from __future__ import annotations

import pytest

from syringe_perfusion.flow_control import (
    MAX_DURATION_S,
    build_perfusion_setpoint,
    flow_for_speed,
    quantize_speed,
    speed_for_flow,
)


@pytest.fixture
def data() -> dict:
    return {
        "syringes": {
            "in": {"calibrated_ul_per_mm": 130.4, "nominal_inner_diameter_mm": 13.0},
            "out": {"calibrated_ul_per_mm": 100.0, "nominal_inner_diameter_mm": 11.0},
        }
    }


def test_fixed_volume_two_ml_min_quantizes_to_about_30_seconds(data: dict) -> None:
    result = build_perfusion_setpoint(
        data,
        mode="fixed_volume",
        in_flow_ml_min=2.0,
        target_volume_ml=1.0,
        in_syringe_key="in",
        out_syringe_key="in",
        out_in_ratio=1.0,
    )
    assert result.programmed_duration_s == 30
    assert result.in_setpoint.programmed_speed_mm_min == 15.34
    assert result.in_setpoint.estimated_actual_flow_ml_min == pytest.approx(2.000336)
    assert result.in_setpoint.expected_volume_ml == pytest.approx(1.000168)
    assert result.out_setpoint.expected_volume_ml == pytest.approx(1.000168)
    assert result.in_setpoint.uart_commands == [
        "q1h15d", "q2h34d", "q3h00d", "q4h00d", "q5h30d", "q6h1d"
    ]


def test_fixed_duration_one_ml_min_for_60_seconds_delivers_one_ml(data: dict) -> None:
    result = build_perfusion_setpoint(
        data,
        mode="fixed_duration",
        in_flow_ml_min=1.0,
        duration_s=60,
        in_syringe_key="in",
        out_syringe_key="in",
    )
    assert result.programmed_duration_s == 60
    assert result.in_setpoint.expected_volume_ml == pytest.approx(1.000168, abs=0.001)


@pytest.mark.parametrize("ratio", [0.9, 1.0, 1.1])
def test_out_ratio_and_separate_calibration(data: dict, ratio: float) -> None:
    result = build_perfusion_setpoint(
        data,
        mode="fixed_duration",
        in_flow_ml_min=1.0,
        duration_s=60,
        in_syringe_key="in",
        out_syringe_key="out",
        out_in_ratio=ratio,
    )
    assert result.requested_out_flow_ml_min == pytest.approx(ratio)
    assert result.out_setpoint.ul_per_mm == 100.0
    assert result.out_setpoint.programmed_speed_mm_min == pytest.approx(ratio * 10)
    assert result.out_setpoint.direction == "reverse"


def test_independent_out_flow_when_ratio_unlocked(data: dict) -> None:
    result = build_perfusion_setpoint(
        data,
        mode="fixed_duration",
        in_flow_ml_min=1.0,
        duration_s=60,
        in_syringe_key="in",
        out_syringe_key="out",
        out_ratio_locked=False,
        independent_out_flow_ml_min=0.75,
    )
    assert result.requested_out_flow_ml_min == 0.75
    assert result.out_in_ratio == 0.75
    assert "change dish volume" in result.warning


def test_bounded_continuous_requires_bound(data: dict) -> None:
    with pytest.raises(ValueError, match="maximum duration"):
        build_perfusion_setpoint(
            data,
            mode="bounded_continuous",
            in_flow_ml_min=1.0,
            in_syringe_key="in",
            out_syringe_key="out",
        )
    result = build_perfusion_setpoint(
        data,
        mode="bounded_continuous",
        in_flow_ml_min=1.0,
        maximum_duration_s=300,
        in_syringe_key="in",
        out_syringe_key="out",
    )
    assert result.programmed_duration_s == 300


def test_quantization_and_device_limits(data: dict) -> None:
    assert quantize_speed(1.005) == 1.01
    assert flow_for_speed(speed_for_flow(2.0, 130.4), 130.4) == pytest.approx(2.0)
    with pytest.raises(ValueError, match="outside"):
        speed_for_flow(0.0001, 130.4)
    with pytest.raises(ValueError, match="outside"):
        speed_for_flow(100.0, 130.4)
    with pytest.raises(ValueError, match="99:59:59"):
        build_perfusion_setpoint(
            data,
            mode="fixed_duration",
            in_flow_ml_min=1.0,
            duration_s=MAX_DURATION_S + 1,
            in_syringe_key="in",
            out_syringe_key="out",
        )
