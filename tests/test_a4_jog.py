import pytest

from syringe_perfusion.a4 import A4Pump


def test_jog_forward_dry_run_sends_manual_forward_then_stop() -> None:
    results = A4Pump(name="IN", port="COM5", dry_run=True).jog_forward(1000)
    assert [result["command"] for result in results] == ["q6h4d", "q6h6d"]
    assert [result["sequence_index"] for result in results] == [0, 1]


def test_jog_reverse_dry_run_sends_manual_reverse_then_stop() -> None:
    results = A4Pump(name="IN", port="COM5", dry_run=True).jog_reverse(1000)
    assert [result["command"] for result in results] == ["q6h5d", "q6h6d"]
    assert [result["sequence_index"] for result in results] == [0, 1]


@pytest.mark.parametrize("duration_ms", [49, 10001])
def test_jog_duration_out_of_range_errors(duration_ms: int) -> None:
    with pytest.raises(ValueError, match="duration_ms"):
        A4Pump(name="IN", port="COM5", dry_run=True).jog_forward(duration_ms)
