from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from syringe_perfusion.calibration import (
    apply_syringe_calibration,
    balance_result,
    calculate_replicate,
    calibration_statistics,
    direct_volume_ul,
    exclude_replicate,
    gravimetric_volume_ul,
)
from syringe_perfusion.commissioning import (
    MANUAL_CONFIRMATION,
    UART_COMPLETED,
    CommissioningService,
    dependency_snapshot,
    evaluate_test_result,
    make_test_result,
    staleness_reasons,
)
from syringe_perfusion.config import REQUIRED_CONFIG_FILES, load_config, validate_config_directory
from syringe_perfusion.coordinator import OperationCoordinator, RunToken
from syringe_perfusion.operations import start_armed_pair
from syringe_perfusion.perfusion_state import read_state, write_state
from syringe_perfusion.validation_store import ValidationStore


ROOT_CONFIG = Path(__file__).resolve().parents[1] / "config"


def active_config(tmp_path: Path) -> Path:
    root = tmp_path / "config"
    root.mkdir()
    for filename in REQUIRED_CONFIG_FILES:
        (root / filename).write_bytes((ROOT_CONFIG / filename).read_bytes())
    pumps = json.loads((root / "pumps.json").read_text(encoding="utf-8"))
    pumps["pumps"]["IN"]["port"] = "COM_IN"
    pumps["pumps"]["OUT"]["enabled"] = True
    pumps["pumps"]["OUT"]["port"] = "COM_OUT"
    (root / "pumps.json").write_text(json.dumps(pumps), encoding="utf-8")
    return root


def test_validation_schema_round_trip_atomic_history_and_unknown_fields(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    store = ValidationStore(validate_config_directory(root), now=lambda: "2026-01-02T03:04:05+00:00")
    record = store.create(operator="operator")
    record["future_field"] = {"preserved": True}
    store.save(record)
    loaded = store.load()
    assert loaded is not None
    assert loaded["schema_version"] == 2
    assert loaded["future_field"] == {"preserved": True}
    loaded["notes"].append("second save")
    store.save(loaded)
    assert list(store.paths.history.glob("*.json"))
    assert not list(store.paths.root.glob("*.tmp"))
    assert store.paths.state.read_bytes().endswith(b"\n")


def test_uart_completion_alone_never_passes_physical_validation() -> None:
    result = evaluate_test_result(
        {
            "evidence_type": MANUAL_CONFIRMATION,
            "uart_completed": True,
            "operator_confirmation": {},
        }
    )
    assert result["outcome"] == "AWAITING MANUAL CONFIRMATION"
    uart = evaluate_test_result({"evidence_type": UART_COMPLETED, "uart_completed": True})
    assert uart["outcome"] == UART_COMPLETED
    assert uart["outcome"] != "PASS"


def test_manual_confirmation_is_required_and_audited() -> None:
    waiting = make_test_result("direction_in", uart_completed=True)
    assert waiting["outcome"] == "AWAITING MANUAL CONFIRMATION"
    passed = make_test_result(
        "direction_in",
        operator_confirmation={
            "observation": "correct",
            "operator": "op",
            "timestamp": "2026-01-01T00:00:00Z",
        },
    )
    assert passed["outcome"] == "PASS"
    assert passed["operator_confirmation"]["operator"] == "op"


def test_dependency_staleness_port_hwid_and_calibration(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    data = load_config(root)
    data["pumps"]["IN"]["hardware_identity"] = {"hwid": "OLD"}
    old = dependency_snapshot(data, config_dir=str(root), application_version="V")
    changed = json.loads(json.dumps(old))
    changed["pumps"]["IN"]["port"] = "COM_NEW"
    changed["pumps"]["IN"]["hardware_identity"]["hwid"] = "NEW"
    key = next(iter(changed["syringes"]))
    changed["syringes"][key]["calibrated_ul_per_mm"] = 999
    reasons = staleness_reasons(old, changed)
    assert any("COM port" in reason for reason in reasons)
    assert any("hardware identity" in reason for reason in reasons)
    assert any("syringe calibration" in reason for reason in reasons)


def test_unrelated_preference_does_not_make_validation_stale(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    data = load_config(root)
    old = dependency_snapshot(data, config_dir=str(root), application_version="V")
    current = json.loads(json.dumps(old))
    current["unrelated_display_preference"] = "changed"
    assert staleness_reasons(old, current) == []


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [(1000, "µL", 1000), (1, "mL", 1000), (500, "ul", 500)],
)
def test_direct_volume_units(value: float, unit: str, expected: float) -> None:
    assert direct_volume_ul(value, unit) == pytest.approx(expected)


def test_gravimetric_volume_and_density_validation() -> None:
    assert gravimetric_volume_ul(10, 10.998, mass_unit="g", density_g_ml=0.998) == pytest.approx(1000)
    assert gravimetric_volume_ul(10000, 10998, mass_unit="mg", density_g_ml=0.998) == pytest.approx(1000)
    with pytest.raises(ValueError, match="density"):
        gravimetric_volume_ul(1, 2, mass_unit="g", density_g_ml=0)


def test_replicate_calculations_and_statistics() -> None:
    values = [
        calculate_replicate(
            measured_volume_ul=volume,
            requested_flow_ml_min=1.0,
            programmed_speed_mm_min=10.0,
            programmed_duration_s=60,
            pump_role="IN",
            direction="forward",
            syringe_key="s",
            operator="op",
        )
        for volume in (995, 1000, 1005)
    ]
    assert values[1]["programmed_travel_mm"] == 10
    assert values[1]["candidate_ul_per_mm"] == 100
    assert values[1]["measured_flow_ml_min"] == 1
    assert values[0]["percent_error"] == pytest.approx(-0.5)
    stats = calibration_statistics(values)
    assert stats["n"] == 3
    assert stats["mean"] == pytest.approx(100)
    assert stats["median"] == pytest.approx(100)
    assert stats["standard_deviation"] == pytest.approx(0.5)
    assert stats["coefficient_of_variation_percent"] == pytest.approx(0.5)
    assert stats["accepted"]


def test_replicate_exclusion_requires_reason_and_criteria_are_configurable() -> None:
    replicate = calculate_replicate(
        measured_volume_ul=1000,
        requested_flow_ml_min=1,
        programmed_speed_mm_min=10,
        programmed_duration_s=60,
        pump_role="IN",
        direction="forward",
        syringe_key="s",
        operator="op",
    )
    with pytest.raises(ValueError, match="reason"):
        exclude_replicate(replicate, "")
    excluded = exclude_replicate(replicate, "visible leak")
    stats = calibration_statistics(
        [excluded, replicate],
        criteria={
            "minimum_replicates": 1,
            "maximum_cv_percent": 1,
            "maximum_abs_mean_flow_error_percent": 1,
        },
    )
    assert stats["excluded_count"] == 1
    assert stats["accepted"]


def test_zero_travel_is_invalid() -> None:
    with pytest.raises(ValueError, match="travel"):
        calculate_replicate(
            measured_volume_ul=1,
            requested_flow_ml_min=1,
            programmed_speed_mm_min=0,
            programmed_duration_s=1,
            pump_role="IN",
            direction="forward",
            syringe_key="s",
            operator="op",
        )


def test_atomic_syringe_update_backup_unknown_keys_and_armed_invalidation(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    path = root / "syringes.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    key = next(iter(document["syringes"]))
    document["syringes"][key]["unknown_future_key"] = "keep"
    path.write_text(json.dumps(document), encoding="utf-8")
    write_state(root, {"state": "ARMED", "plan_id": "P"})
    apply_syringe_calibration(
        root,
        syringe_key=key,
        candidate_ul_per_mm=131.25,
        validation_id="V",
        method="replicates",
        statistics_result={"n": 3},
        confirmed=True,
        now="2026-01-01",
    )
    updated = json.loads(path.read_text(encoding="utf-8"))
    assert updated["syringes"][key]["calibrated_ul_per_mm"] == 131.25
    assert updated["syringes"][key]["unknown_future_key"] == "keep"
    assert path.with_name("syringes.json.bak").exists()
    assert read_state(root)["state"] == "DIRTY"


def test_calibration_update_is_rejected_before_write_during_active_run(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    path = root / "syringes.json"
    before = path.read_bytes()
    key = next(iter(json.loads(before)["syringes"]))
    write_state(root, {"state": "STARTED", "run_id": "RUN"})
    with pytest.raises(RuntimeError, match="STARTED"):
        apply_syringe_calibration(
            root,
            syringe_key=key,
            candidate_ul_per_mm=222,
            validation_id="V",
            method="test",
            statistics_result={"n": 3},
            confirmed=True,
        )
    assert path.read_bytes() == before


def test_balance_calculations_do_not_claim_measured_dish_change() -> None:
    result = balance_result(
        requested_in_flow_ml_min=1,
        requested_out_flow_ml_min=0.9,
        duration_s=60,
        measured_in_volume_ml=1.01,
        measured_out_volume_ml=0.89,
    )
    assert result["expected_net_balance_ml"] == pytest.approx(0.1)
    assert result["measured_net_balance_ml"] == pytest.approx(0.12)
    assert not result["dish_change_is_measured"]


class FakePump:
    def __init__(self, role: str, events: list[str], fail_start: bool = False) -> None:
        self.role = role
        self.events = events
        self.fail_start = fail_start

    def manual_forward_guarded(self, guard):
        with guard():
            if self.fail_start:
                raise RuntimeError("start failed")
            self.events.append(f"{self.role}:start")
            return {"pump": self.role, "command": "start"}

    manual_reverse_guarded = manual_forward_guarded
    start_forward_guarded = manual_forward_guarded
    start_reverse_guarded = manual_forward_guarded

    def write_settings(self, speed, duration, save=False):
        self.events.append(f"{self.role}:program:{speed}:{duration}:{save}")
        return [{"pump": self.role, "command": "program"}]

    def stop(self):
        self.events.append(f"{self.role}:stop")
        return {"pump": self.role, "command": "stop"}


def test_commissioning_is_bounded_reserves_run_and_attempts_all_stops(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    data = load_config(root)
    events: list[str] = []
    coordinator = OperationCoordinator(
        root,
        pump_factory=lambda role, _target: FakePump(role, events),
        registry_path=tmp_path / "registry.json",
    )
    result = CommissioningService(coordinator, data).bounded_pair_stop_check(duration_ms=100)
    assert result["run_id"]
    assert events.count("IN:stop") == 1
    assert events.count("OUT:stop") == 1
    assert result["state"] == "AWAITING MANUAL CONFIRMATION"
    assert read_state(root)["state"] == "STOPPED"


def test_commissioning_start_failure_still_attempts_stop_on_both(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    data = load_config(root)
    events: list[str] = []
    coordinator = OperationCoordinator(
        root,
        pump_factory=lambda role, _target: FakePump(
            role, events, fail_start=role == "OUT"
        ),
        registry_path=tmp_path / "registry.json",
    )
    with pytest.raises(RuntimeError, match="start failed"):
        CommissioningService(coordinator, data).bounded_pair_stop_check(duration_ms=100)
    assert "IN:stop" in events
    assert "OUT:stop" in events


def test_stop_cancels_commissioning_wait_and_no_later_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = active_config(tmp_path)
    data = load_config(root)
    events: list[str] = []
    coordinator = OperationCoordinator(
        root,
        pump_factory=lambda role, _target: FakePump(role, events),
        registry_path=tmp_path / "registry.json",
    )
    from syringe_perfusion import coordinator as coordinator_module

    original_factory = coordinator_module.pump_from_config

    def dry_only_factory(role, target, *, dry_run=False):
        assert dry_run, "DRY-RUN rehearsal constructed a LIVE pump"
        return original_factory(role, target, dry_run=dry_run)

    monkeypatch.setattr(coordinator_module, "pump_from_config", dry_only_factory)
    cancel = threading.Event()
    cancel.set()
    result = CommissioningService(coordinator, data).cancellation_rehearsal(
        delay_s=10,
        cancel_event=cancel,
    )
    assert result["software_pass"]
    assert not result["in_start_authorized"]
    assert not result["out_start_authorized"]
    assert read_state(root)["state"] == "STOPPED"


def test_commissioning_rejected_during_production_state(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    data = load_config(root)
    write_state(root, {"state": "STARTED", "run_id": "production"})
    coordinator = OperationCoordinator(root, registry_path=tmp_path / "registry.json")
    with pytest.raises(RuntimeError, match="STARTED"):
        coordinator.begin_recipe(data, operation_type="commissioning")


def test_normal_start_rejected_during_commissioning_and_flow_run_is_bounded(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    data = load_config(root)
    events: list[str] = []
    coordinator = OperationCoordinator(
        root,
        pump_factory=lambda role, _target: FakePump(role, events),
        registry_path=tmp_path / "registry.json",
    )
    token = coordinator.begin_recipe(data, operation_type="commissioning")
    with pytest.raises(ValueError, match="not startable"):
        coordinator.reserve_start()
    coordinator.emergency_stop(fallback_data=data)
    cancelled = threading.Event()
    cancelled.set()
    result = CommissioningService(coordinator, data).bounded_flow_run(
        role="IN",
        direction="forward",
        speed_mm_min=10,
        duration_s=1,
        cancel_event=cancelled,
    )
    assert result["state"] == "AWAITING MEASURED RESULT"
    assert "IN:start" in events
    assert "IN:stop" in events and "OUT:stop" in events
    with pytest.raises(ValueError, match="bounded"):
        CommissioningService(coordinator, data).bounded_flow_run(
            role="IN",
            direction="forward",
            speed_mm_min=10,
            duration_s=601,
        )


def test_strict_policy_failure_does_not_leave_immediate_or_scheduled_start_active(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = active_config(tmp_path)
    monkeypatch.setattr(
        "syringe_perfusion.operations.load_user_settings",
        lambda: {"ui_preferences": {"require_current_commissioning": True}},
    )
    write_state(root, {"state": "ARMED", "plan_id": "P", "plan": {"plan_id": "P"}})
    with pytest.raises(ValueError, match="requires current commissioning"):
        start_armed_pair(root)
    assert read_state(root)["state"] == "ARMED"

    events: list[str] = []
    state = {
        "state": "STARTING",
        "state_revision": 5,
        "run_id": "R",
        "operation_id": "O",
        "cancellation_generation": 0,
        "plan_id": "P",
        "active_targets": [
            {
                "role": role,
                "port": f"COM_{role}",
                "baudrate": 9600,
                "terminator": "\\r\\n",
                "timeout": 1,
                "commands": {},
            }
            for role in ("IN", "OUT")
        ],
    }
    write_state(root, state)
    persisted = read_state(root)
    token = RunToken(
        run_id="R",
        operation_id="O",
        cancellation_generation=0,
        state_revision=int(persisted["state_revision"]),
        operation_type="scheduled_start",
        plan_id="P",
    )
    with pytest.raises(ValueError, match="requires current commissioning"):
        start_armed_pair(
            root,
            reserved_token=token,
            pump_factory=lambda role, _target: FakePump(role, events),
        )
    assert read_state(root)["state"] == "FAULT"
    assert "IN:stop" in events and "OUT:stop" in events
