import pytest

from syringe_perfusion.a4 import format_settings_commands, format_speed_commands, format_time_commands


def test_format_speed_commands() -> None:
    assert format_speed_commands(15.37) == ["q1h15d", "q2h37d"]
    assert format_speed_commands(3.8) == ["q1h03d", "q2h80d"]
    assert format_speed_commands(25.0) == ["q1h25d", "q2h00d"]


def test_format_speed_rounds_carry_to_integer() -> None:
    assert format_speed_commands(15.999) == ["q1h16d", "q2h00d"]


def test_format_time_commands() -> None:
    assert format_time_commands(30) == ["q3h00d", "q4h00d", "q5h30d"]
    assert format_time_commands(60) == ["q3h00d", "q4h01d", "q5h00d"]
    assert format_time_commands(3661) == ["q3h01d", "q4h01d", "q5h01d"]


def test_format_settings_commands_appends_save() -> None:
    assert format_settings_commands(15.37, 30, save=True)[-1] == "q6h1d"


@pytest.mark.parametrize("speed", [0, 0.009, 150.01])
def test_invalid_speed_raises(speed: float) -> None:
    with pytest.raises(ValueError):
        format_speed_commands(speed)


@pytest.mark.parametrize("duration", [0, -1, 360000])
def test_invalid_time_raises(duration: float) -> None:
    with pytest.raises(ValueError):
        format_time_commands(duration)
