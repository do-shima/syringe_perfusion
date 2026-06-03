from syringe_perfusion.a4 import A4Pump
from syringe_perfusion.cli import stop_all
from syringe_perfusion.config import load_config


def test_dry_run_send_returns_log_dict() -> None:
    pump = A4Pump(name="IN", port="COM5", dry_run=True)
    result = pump.start_forward()
    assert result["pump"] == "IN"
    assert result["port"] == "COM5"
    assert result["command"] == "q6h2d"
    assert result["response"] == "DRY_RUN"
    assert result["dry_run"] is True


def test_stop_all_skips_disabled_out() -> None:
    data = load_config()
    results = stop_all(data, dry_run=True, trigger_source="pytest")
    assert [result["pump"] for result in results] == ["IN"]
    assert [result["command"] for result in results] == ["q6h6d"]


def test_stop_all_sends_stop_to_in_and_out_when_out_enabled() -> None:
    data = load_config()
    data["pumps"]["OUT"]["enabled"] = True
    data["pumps"]["OUT"]["port"] = "COM6"
    results = stop_all(data, dry_run=True, trigger_source="pytest")
    assert [result["pump"] for result in results] == ["IN", "OUT"]
    assert [result["command"] for result in results] == ["q6h6d", "q6h6d"]
