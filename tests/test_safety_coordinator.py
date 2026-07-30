from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from threading import Barrier, Event, Thread
from typing import Any

import pytest

from syringe_perfusion.config import REQUIRED_CONFIG_FILES, load_config, resolve_config
from syringe_perfusion.coordinator import OperationCoordinator
from syringe_perfusion.flow_control import build_perfusion_setpoint
from syringe_perfusion.operations import (
    program_pair,
    pushpull,
    start_armed_pair,
    stop_all_safe,
)
from syringe_perfusion.perfusion_state import (
    process_file_lock,
    read_pending,
    read_state,
    runtime_paths,
    write_state,
)
from syringe_perfusion.protocol_runner import run_scheduled, schedule_armed
from syringe_perfusion.recipe_engine import RecipeEngine
from syringe_perfusion.recipe_model import Recipe, validate_recipe


ROOT_CONFIG = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture
def active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    target = tmp_path / "config"
    target.mkdir()
    for filename in REQUIRED_CONFIG_FILES:
        (target / filename).write_bytes((ROOT_CONFIG / filename).read_bytes())
    pumps = json.loads((target / "pumps.json").read_text(encoding="utf-8"))
    pumps["pumps"]["IN"]["port"] = "COM_A"
    pumps["pumps"]["OUT"]["port"] = "COM_B"
    pumps["pumps"]["OUT"]["enabled"] = True
    (target / "pumps.json").write_text(
        json.dumps(pumps, indent=2) + "\n", encoding="utf-8"
    )
    return target


class FakePump:
    def __init__(
        self,
        role: str,
        calls: list[tuple[str, str, str]],
        failures: set[tuple[str, str]] | None = None,
    ) -> None:
        self.role = role
        self.calls = calls
        self.failures = failures or set()

    def _call(self, action: str) -> dict[str, Any]:
        self.calls.append((self.role, action, f"COM_{self.role}"))
        if (self.role, action) in self.failures:
            raise RuntimeError(f"{self.role} {action} failed")
        return {
            "pump": self.role,
            "port": f"COM_{self.role}",
            "command": action,
            "response": "OK",
        }

    def stop(self) -> dict[str, Any]:
        return self._call("stop")

    def start_forward(self) -> dict[str, Any]:
        return self._call("start_forward")

    def start_reverse(self) -> dict[str, Any]:
        return self._call("start_reverse")

    def write_settings(
        self, _speed: float, _duration: float, *, save: bool = True
    ) -> list[dict[str, Any]]:
        self._call("program")
        return [
            {
                "pump": self.role,
                "port": f"COM_{self.role}",
                "command": "save" if save else "program",
                "response": "OK",
            }
        ]


def factory(
    calls: list[tuple[str, str, str]],
    failures: set[tuple[str, str]] | None = None,
):
    return lambda role, _cfg: FakePump(role, calls, failures)


def scanner() -> list[dict[str, Any]]:
    return [
        {"device": "COM_A", "description": "IN", "hwid": "HW-IN"},
        {"device": "COM_B", "description": "OUT", "hwid": "HW-OUT"},
    ]


def arm(active: Path, calls: list[tuple[str, str, str]]) -> dict[str, Any]:
    data = load_config(active)
    setpoint = build_perfusion_setpoint(
        data,
        mode="fixed_volume",
        in_flow_ml_min=2.0,
        target_volume_ml=1.0,
        in_syringe_key="terumo_ss05lz_5ml",
        out_syringe_key="terumo_ss05lz_5ml",
        in_to_out_delay_s=0,
    )
    return program_pair(
        active,
        setpoint,
        scanner=scanner,
        pump_factory=factory(calls),
    )


def test_two_concurrent_starts_reserve_exactly_once(active: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    arm(active, calls)
    barrier = Barrier(3)
    successes: list[str] = []
    errors: list[str] = []

    def reserve() -> None:
        coordinator = OperationCoordinator(active, pump_factory=factory(calls))
        barrier.wait()
        try:
            token, _state = coordinator.reserve_start()
            successes.append(token.run_id)
        except Exception as exc:
            errors.append(str(exc))

    threads = [Thread(target=reserve), Thread(target=reserve)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)
    assert len(successes) == 1
    assert len(errors) == 1
    assert not [call for call in calls if call[1].startswith("start")]


def test_stop_after_prior_validation_prevents_start_transition(active: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    arm(active, calls)
    coordinator = OperationCoordinator(active, pump_factory=factory(calls))
    coordinator.emergency_stop()
    with pytest.raises(ValueError, match="not startable"):
        coordinator.reserve_start()
    assert not [call for call in calls if call[1].startswith("start")]


def test_stop_immediately_before_in_start_rejects_command(active: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    arm(active, calls)
    coordinator = OperationCoordinator(active, pump_factory=factory(calls))
    token, state = coordinator.reserve_start()
    coordinator.emergency_stop()
    with pytest.raises(ValueError, match="cancelled|stopped|state"):
        coordinator.emit_start(
            token,
            "IN",
            factory(calls)("IN", state["active_targets"][0]),
            "forward",
        )
    assert not [call for call in calls if call[1] == "start_forward"]


def test_stale_run_id_and_revision_are_rejected(active: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    arm(active, calls)
    coordinator = OperationCoordinator(active, pump_factory=factory(calls))
    token, state = coordinator.reserve_start()
    stale = {**state, "run_id": "OTHER"}
    write_state(active, stale)
    assert coordinator.token_status(token, {"STARTING"}) == "stale"
    stale["run_id"] = token.run_id
    stale["state_revision"] = token.state_revision - 1
    write_state(active, stale)
    assert coordinator.token_status(token, {"STARTING"}) == "stale"


def test_stop_at_out_deadline_wins_final_check(active: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    arm(active, calls)
    coordinator = OperationCoordinator(active, pump_factory=factory(calls))
    token, state = coordinator.reserve_start()
    coordinator.emit_start(
        token, "IN", factory(calls)("IN", state["active_targets"][0]), "forward"
    )
    result = coordinator.wait(
        token,
        0,
        allowed_states={"STARTING"},
        before_final_check=lambda: coordinator.emergency_stop(),
    )
    assert result == "cancelled"
    with pytest.raises(ValueError, match="cancelled|stopped|state"):
        coordinator.emit_start(
            token,
            "OUT",
            factory(calls)("OUT", state["active_targets"][1]),
            "reverse",
        )
    assert ("OUT", "start_reverse", "COM_OUT") not in calls
    assert ("IN", "stop", "COM_IN") in calls
    assert read_state(active)["state"] == "STOPPED"


def test_snapshot_stop_survives_malformed_config_and_changed_ports(active: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    arm(active, calls)
    coordinator = OperationCoordinator(active, pump_factory=factory(calls))
    coordinator.reserve_start()
    (active / "pumps.json").write_text("{malformed", encoding="utf-8")
    stopped = stop_all_safe(active, pump_factory=factory(calls))
    assert stopped["state"] == "STOPPED"
    stopped_ports = {item["port"] for item in stopped["stop_results"]}
    assert stopped_ports == {"COM_A", "COM_B"}


def test_snapshot_stop_survives_missing_current_config(active: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    arm(active, calls)
    OperationCoordinator(active, pump_factory=factory(calls)).reserve_start()
    (active / "pumps.json").unlink()
    stopped = stop_all_safe(active, pump_factory=factory(calls))
    assert stopped["state"] == "STOPPED"
    assert {item["port"] for item in stopped["stop_results"]} == {"COM_A", "COM_B"}


def test_snapshot_stop_ignores_out_disabled_after_start(active: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    arm(active, calls)
    OperationCoordinator(active, pump_factory=factory(calls)).reserve_start()
    pumps_path = active / "pumps.json"
    document = json.loads(pumps_path.read_text(encoding="utf-8"))
    document["pumps"]["OUT"]["enabled"] = False
    document["pumps"]["IN"]["port"] = "COM_CHANGED"
    pumps_path.write_text(json.dumps(document), encoding="utf-8")
    stopped = stop_all_safe(active, pump_factory=factory(calls))
    assert {item["port"] for item in stopped["stop_results"]} == {"COM_A", "COM_B"}


def test_one_stop_failure_does_not_prevent_other(active: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    arm(active, calls)
    coordinator = OperationCoordinator(
        active,
        pump_factory=factory(calls, {("IN", "stop")}),
    )
    state = coordinator.emergency_stop()
    assert state["state"] == "STOP_FAILED"
    assert ("IN", "stop", "COM_IN") in calls
    assert ("OUT", "stop", "COM_OUT") in calls
    assert len(state["stop_results"]) == 2


def test_stop_follows_registered_active_config_when_current_differs(
    active: Path, tmp_path: Path
) -> None:
    calls: list[tuple[str, str, str]] = []
    arm(active, calls)
    OperationCoordinator(active, pump_factory=factory(calls)).reserve_start()
    other = tmp_path / "other-config"
    other.mkdir()
    for filename in REQUIRED_CONFIG_FILES:
        (other / filename).write_bytes((ROOT_CONFIG / filename).read_bytes())
    stopped = stop_all_safe(other, pump_factory=factory(calls))
    assert stopped["state"] == "STOPPED"
    assert read_state(active)["state"] == "STOPPED"
    assert {item["port"] for item in stopped["stop_results"]} == {"COM_A", "COM_B"}


def test_live_legacy_pushpull_is_refused_before_start(active: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    data = load_config(active)
    with pytest.raises(RuntimeError, match="disabled for safety"):
        pushpull(
            data,
            in_pump="IN",
            out_pump="OUT",
            profile_in="fast30_1ml",
            profile_out="drain30_1ml",
            out_delay=1,
            dry_run=False,
        )
    assert calls == []


class SignallingCoordinator(OperationCoordinator):
    def __init__(self, *args: Any, wait_entered: Event, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.wait_entered = wait_entered

    def wait(self, *args: Any, **kwargs: Any):
        self.wait_entered.set()
        return super().wait(*args, **kwargs)


def test_recipe_stop_during_wait_prevents_later_start(active: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    data = load_config(active)
    wait_entered = Event()
    coordinator = SignallingCoordinator(
        active,
        wait_entered=wait_entered,
        pump_factory=factory(calls),
    )
    recipe = Recipe.from_dict(
        {
            "schema_version": 2,
            "recipe_id": "cancel_wait",
            "display_name": "Cancel wait",
            "description": "",
            "blocks": [
                {"id": "b1", "type": "wait", "duration_s": 30},
                {
                    "id": "b2",
                    "type": "pump_start",
                    "pump": "OUT",
                    "action": "start_reverse",
                    "profile": "drain30_1ml",
                },
            ],
        }
    )
    validate_recipe(recipe, data)
    events: list[Any] = []

    def run() -> None:
        events.extend(
            RecipeEngine(
                data,
                active,
                coordinator=coordinator,
                pump_factory=factory(calls),
            ).execute(recipe, dry_run=False)
        )

    thread = Thread(target=run)
    thread.start()
    assert wait_entered.wait(1)
    coordinator.emergency_stop(fallback_data=data)
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert not [call for call in calls if call[1] == "start_reverse"]
    assert read_state(active)["state"] == "STOPPED"
    assert events and events[0].get("note", "").startswith("wait cancelled")


def test_scheduler_spawn_failure_rolls_pending_to_fault(active: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    arm(active, calls)

    def fail_spawn(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("spawn failed")

    with pytest.raises(OSError, match="spawn failed"):
        schedule_armed(
            active,
            delay_s=300,
            scanner=scanner,
            popen=fail_spawn,
        )
    assert read_state(active)["state"] == "FAULT"
    assert read_pending(active)["state"] == "FAULT"


def test_stale_pending_from_previous_boot_never_runs(active: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    arm(active, calls)
    pending = schedule_armed(
        active,
        delay_s=0,
        scanner=scanner,
        spawn=False,
    )
    pending_path = runtime_paths(active).pending
    document = json.loads(pending_path.read_text(encoding="utf-8"))
    document["boot_marker"] = -1
    pending_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="previous boot"):
        run_scheduled(
            active,
            pending["run_id"],
            scanner=scanner,
            pump_factory=factory(calls),
        )
    assert not [call for call in calls if call[1].startswith("start")]
    assert read_state(active)["state"] == "FAULT"


def test_stale_lock_recovered_and_live_lock_not_stolen(active: Path) -> None:
    lock = runtime_paths(active).run_lock
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        json.dumps({"pid": 99999999, "operation": "dead", "run_id": "OLD"}),
        encoding="utf-8",
    )
    with process_file_lock(lock, owner="test", timeout_s=0.05):
        assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == os.getpid()
    lock.write_text(
        json.dumps({"pid": os.getpid(), "operation": "live", "run_id": "LIVE"}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="live process"):
        with process_file_lock(lock, owner="thief", timeout_s=0.01):
            pass
    lock.unlink()


def test_completion_is_persisted_only_from_started(active: Path) -> None:
    write_state(
        active,
        {
            "state": "STARTED",
            "run_id": "RUN",
            "operation_id": "OP",
            "cancellation_generation": 0,
            "expected_end_epoch": 10,
        },
    )
    coordinator = OperationCoordinator(active)
    completed = coordinator.reconcile_completion(now_epoch=11)
    assert completed and completed["state"] == "COMPLETED_ESTIMATED"
    assert read_state(active)["state"] == "COMPLETED_ESTIMATED"

    write_state(active, {"state": "STOPPED", "expected_end_epoch": 10})
    assert coordinator.reconcile_completion(now_epoch=11)["state"] == "STOPPED"
    write_state(active, {"state": "FAULT", "expected_end_epoch": 10})
    assert coordinator.reconcile_completion(now_epoch=11)["state"] == "FAULT"
