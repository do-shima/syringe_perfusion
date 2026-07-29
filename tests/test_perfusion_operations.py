from __future__ import annotations

import json
from pathlib import Path
from threading import Event
from threading import Thread
from typing import Any

import pytest

from syringe_perfusion.config import REQUIRED_CONFIG_FILES, resolve_config
from syringe_perfusion.flow_control import build_perfusion_setpoint
from syringe_perfusion.operations import (
    cancel_pending,
    get_arm_status,
    program_pair,
    start_armed_pair,
    stop_all_safe,
)
from syringe_perfusion.perfusion_state import (
    config_fingerprint,
    invalidate_armed,
    read_pending,
    read_state,
    runtime_paths,
)
from syringe_perfusion.protocol_runner import build_worker_command, run_scheduled, schedule_armed


ROOT_CONFIG = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture
def active(tmp_path: Path) -> Path:
    target = tmp_path / "config"
    target.mkdir()
    for filename in REQUIRED_CONFIG_FILES:
        (target / filename).write_bytes((ROOT_CONFIG / filename).read_bytes())
    pumps_path = target / "pumps.json"
    document = json.loads(pumps_path.read_text(encoding="utf-8"))
    document["pumps"]["IN"]["port"] = "COM_A"
    document["pumps"]["OUT"]["port"] = "COM_B"
    document["pumps"]["OUT"]["enabled"] = True
    pumps_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return target


def scanner() -> list[dict[str, Any]]:
    return [
        {"device": "COM_A", "description": "IN", "hwid": "HW-IN"},
        {"device": "COM_B", "description": "OUT", "hwid": "HW-OUT"},
    ]


class FakePump:
    def __init__(self, key: str, calls: list[tuple], failures: set[tuple[str, str]]) -> None:
        self.key = key
        self.calls = calls
        self.failures = failures

    def _call(self, action: str, *values: Any) -> dict[str, Any]:
        self.calls.append((self.key, action, *values))
        if (self.key, action) in self.failures:
            raise RuntimeError(f"{self.key} {action} failed")
        return {"pump": self.key, "port": f"COM_{self.key}", "command": action, "response": "OK"}

    def stop(self) -> dict[str, Any]:
        return self._call("stop")

    def write_settings(self, speed: float, duration: float, *, save: bool = True) -> list[dict[str, Any]]:
        self._call("program", speed, duration, save)
        return [{"pump": self.key, "port": f"COM_{self.key}", "command": "q6h1d", "response": "OK"}]

    def start_forward(self) -> dict[str, Any]:
        return self._call("start_forward")

    def start_reverse(self) -> dict[str, Any]:
        return self._call("start_reverse")


def factory(calls: list[tuple], failures: set[tuple[str, str]] | None = None):
    failures = failures or set()
    return lambda key, _cfg: FakePump(key, calls, failures)


def setpoint(active: Path):
    data = __import__("syringe_perfusion.config", fromlist=["load_config"]).load_config(active)
    return build_perfusion_setpoint(
        data,
        mode="fixed_volume",
        in_flow_ml_min=2.0,
        target_volume_ml=1.0,
        in_syringe_key="terumo_ss05lz_5ml",
        out_syringe_key="terumo_ss05lz_5ml",
        in_to_out_delay_s=0,
    )


def arm(active: Path, calls: list[tuple]) -> dict[str, Any]:
    return program_pair(
        active,
        setpoint(active),
        scanner=scanner,
        pump_factory=factory(calls),
    )


def test_runtime_absent_then_armed_only_after_out_and_in_program(active: Path) -> None:
    assert not runtime_paths(active).root.exists()
    calls: list[tuple] = []
    state = arm(active, calls)
    assert state["state"] == "ARMED"
    assert [call[:2] for call in calls] == [
        ("IN", "stop"), ("OUT", "stop"), ("OUT", "program"), ("IN", "program")
    ]
    persisted = read_state(active)
    assert persisted and persisted["state"] == "ARMED"
    assert persisted["plan"]["not_read_back"] is True
    assert persisted["plan"]["config_fingerprint"] == config_fingerprint(active)
    assert persisted["plan"]["pumps"]["IN"]["hardware_identity"]["hwid"] == "HW-IN"


@pytest.mark.parametrize("failure", [("OUT", "program"), ("IN", "program")])
def test_program_failure_fails_closed_and_leaves_no_armed_state(active: Path, failure: tuple[str, str]) -> None:
    calls: list[tuple] = []
    with pytest.raises(RuntimeError):
        program_pair(
            active,
            setpoint(active),
            scanner=scanner,
            pump_factory=factory(calls, {failure}),
        )
    state = read_state(active)
    assert state and state["state"] == "FAULT"
    assert ("IN", "stop") in [call[:2] for call in calls]
    assert ("OUT", "stop") in [call[:2] for call in calls]


def test_dry_run_preview_is_not_startable(active: Path) -> None:
    calls: list[tuple] = []
    result = program_pair(
        active,
        setpoint(active),
        dry_run=True,
        scanner=lambda: [],
        pump_factory=factory(calls),
    )
    assert result["state"] == "DRY_RUN_PREVIEW"
    with pytest.raises(ValueError, match="not startable"):
        start_armed_pair(active, scanner=scanner, pump_factory=factory(calls))


def test_start_armed_does_not_reprogram(active: Path) -> None:
    calls: list[tuple] = []
    arm(active, calls)
    calls.clear()
    state = start_armed_pair(active, scanner=scanner, pump_factory=factory(calls))
    assert state["state"] == "STARTED"
    assert [call[:2] for call in calls] == [("IN", "start_forward"), ("OUT", "start_reverse")]
    assert all(call[1] != "program" for call in calls)


def test_cancellation_during_in_to_out_delay_stops_in_and_never_starts_out(active: Path) -> None:
    calls: list[tuple] = []
    state = arm(active, calls)
    state["plan"]["requested"]["in_to_out_delay_s"] = 5
    from syringe_perfusion.perfusion_state import write_state

    write_state(active, state)
    calls.clear()
    event = Event()
    event.set()
    stopped = start_armed_pair(
        active,
        scanner=scanner,
        pump_factory=factory(calls),
        wait_event=event,
    )
    assert stopped["state"] == "STOPPED"
    assert ("IN", "start_forward") in [call[:2] for call in calls]
    assert ("OUT", "start_reverse") not in [call[:2] for call in calls]
    assert ("IN", "stop") in [call[:2] for call in calls]


def test_out_start_failure_stops_both_and_marks_fault(active: Path) -> None:
    calls: list[tuple] = []
    arm(active, calls)
    calls.clear()
    with pytest.raises(RuntimeError):
        start_armed_pair(
            active,
            scanner=scanner,
            pump_factory=factory(calls, {("OUT", "start_reverse")}),
        )
    assert read_state(active)["state"] == "FAULT"
    assert ("IN", "stop") in [call[:2] for call in calls]
    assert ("OUT", "stop") in [call[:2] for call in calls]


def test_invalidation_fingerprint_and_port_changes_refuse_start(active: Path) -> None:
    calls: list[tuple] = []
    arm(active, calls)
    invalidate_armed(active, "flow changed")
    with pytest.raises(ValueError, match="DIRTY"):
        start_armed_pair(active, scanner=scanner, pump_factory=factory(calls))

    arm(active, calls)
    pumps = active / "pumps.json"
    document = json.loads(pumps.read_text(encoding="utf-8"))
    document["pumps"]["IN"]["timeout"] = 2
    pumps.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprint"):
        start_armed_pair(active, scanner=scanner, pump_factory=factory(calls))


def test_schedule_duplicate_cancel_and_stop_cancel_pending(active: Path) -> None:
    calls: list[tuple] = []
    arm(active, calls)
    pending = schedule_armed(active, delay_s=300, scanner=scanner, spawn=False)
    assert pending["state"] == "PENDING"
    assert read_pending(active)["run_id"] == pending["run_id"]
    with pytest.raises((RuntimeError, ValueError)):
        schedule_armed(active, delay_s=300, scanner=scanner, spawn=False)
    assert cancel_pending(active)["state"] == "CANCELLED"
    assert cancel_pending(active)["state"] == "CANCELLED"

    arm(active, calls)
    schedule_armed(active, delay_s=300, scanner=scanner, spawn=False)
    stopped = stop_all_safe(active, pump_factory=factory(calls))
    assert stopped["state"] == "STOPPED"
    assert read_pending(active)["state"] == "CANCELLED"


def test_worker_command_preserves_explicit_config(active: Path) -> None:
    command = build_worker_command(active, "RUN-ID")
    assert "--config-dir" in command
    assert str(active.resolve()) in command
    assert command[-3:] == ["run-scheduled", "--run-id", "RUN-ID"]


def test_cancel_during_scheduled_delay_prevents_all_start_commands(active: Path) -> None:
    calls: list[tuple] = []
    arm(active, calls)
    calls.clear()
    pending = schedule_armed(active, delay_s=1.0, scanner=scanner, spawn=False)
    results: list[dict[str, Any]] = []

    def worker() -> None:
        results.append(
            run_scheduled(
                active,
                pending["run_id"],
                scanner=scanner,
                pump_factory=factory(calls),
            )
        )

    thread = Thread(target=worker)
    thread.start()
    import time

    time.sleep(0.05)
    cancel_pending(active)
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert results[0]["state"] == "CANCELLED"
    assert not [call for call in calls if call[1].startswith("start")]


def test_arm_status_shared_runtime(active: Path) -> None:
    calls: list[tuple] = []
    arm(active, calls)
    status = get_arm_status(resolve_config(active))
    assert status["state"] == "ARMED"
    assert status["plan"]["pumps"]["IN"]["port"] == "COM_A"
