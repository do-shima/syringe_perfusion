import pytest

from syringe_perfusion.config import load_config
from syringe_perfusion.profiles import (
    calculate_profile,
    speed_mm_min_for_volume_duration,
    ul_per_mm_from_inner_diameter,
    volume_ul_for_speed_duration,
)


def test_ul_per_mm_from_inner_diameter_13mm() -> None:
    assert ul_per_mm_from_inner_diameter(13.0) == pytest.approx(132.7, rel=0.002)


def test_fast30_estimated_volume_with_calibrated_syringe() -> None:
    data = load_config()
    profile = data["profiles"]["fast30_1ml"]
    syringe_key = profile["syringe"]
    result = calculate_profile(profile, data["syringes"][syringe_key], syringe_key)
    assert result.estimated_volume_ul == pytest.approx(1002, abs=1.0)


def test_speed_for_1000ul_30sec_with_calibrated_syringe() -> None:
    speed = speed_mm_min_for_volume_duration(1000, 30, 130.4)
    assert speed == pytest.approx(15.34, abs=0.01)


def test_volume_for_fast30_values() -> None:
    volume = volume_ul_for_speed_duration(15.37, 30, 130.4)
    assert volume == pytest.approx(1002.1, abs=0.2)
