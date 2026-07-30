from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from syringe_perfusion.cli import main
from syringe_perfusion.config import REQUIRED_CONFIG_FILES, load_config
from syringe_perfusion.perfusion_state import append_protocol_log, config_fingerprint, write_state
from syringe_perfusion.preflight import evaluate_preflight
from syringe_perfusion.run_history import export_runs, recent_runs
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


def assess(root: Path, **updates):
    data = load_config(root)
    arguments = {
        "runtime_state": {"state": "STOPPED"},
        "validation_status": {"status": "missing", "commissioned": False, "stale_reasons": []},
        "current_fingerprint": config_fingerprint(root),
    }
    arguments.update(updates)
    return evaluate_preflight(data, **arguments)


def test_preflight_valid_config_warns_commissioning_but_has_no_block(tmp_path: Path) -> None:
    result = assess(tmp_path_config := active_config(tmp_path))
    assert result["ready"]
    assert result["counts"]["BLOCK"] == 0
    assert any(item["code"] == "COMMISSIONING_INCOMPLETE" for item in result["findings"])


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda data: data["pumps"]["IN"].update(port=""), "IN_PORT_MISSING"),
        (lambda data: data["pumps"]["OUT"].update(port=""), "OUT_PORT_MISSING"),
        (lambda data: data["pumps"]["OUT"].update(port="COM_IN"), "DUPLICATE_PORT"),
    ],
)
def test_preflight_port_blocks(tmp_path: Path, mutation, code: str) -> None:
    root = active_config(tmp_path)
    data = load_config(root)
    mutation(data)
    result = evaluate_preflight(
        data,
        runtime_state={"state": "STOPPED"},
        validation_status={"commissioned": False, "stale_reasons": []},
        current_fingerprint=config_fingerprint(root),
    )
    assert not result["ready"]
    assert any(item["code"] == code and item["level"] == "BLOCK" for item in result["findings"])


def test_preflight_hwid_mismatch_and_fault_block(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    data = load_config(root)
    data["pumps"]["IN"]["hardware_identity"] = {"hwid": "EXPECTED"}
    result = evaluate_preflight(
        data,
        runtime_state={"state": "FAULT"},
        validation_status={"commissioned": True, "stale_reasons": []},
        current_fingerprint=config_fingerprint(root),
        detected_ports=[{"device": "COM_IN", "hwid": "OTHER"}],
    )
    codes = {item["code"] for item in result["findings"] if item["level"] == "BLOCK"}
    assert {"IN_HWID_MISMATCH", "UNRESOLVED_FAULT"} <= codes


def test_live_transition_lock_blocks_but_dead_owner_does_not(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    live = assess(
        root,
        live_lock={"pid": 123, "run_id": "R"},
        live_lock_owner_alive=True,
    )
    assert any(item["code"] == "LIVE_RUN_LOCK" for item in live["findings"])
    stale = assess(
        root,
        live_lock={"pid": 123, "run_id": "R"},
        live_lock_owner_alive=False,
    )
    assert not any(item["code"] == "LIVE_RUN_LOCK" for item in stale["findings"])


def test_strict_commissioning_blocks_and_cannot_override_software(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    strict = assess(root, require_commissioned=True)
    assert any(item["code"] == "COMMISSIONING_REQUIRED" for item in strict["findings"])
    data = load_config(root)
    data["pumps"]["IN"]["port"] = ""
    result = evaluate_preflight(
        data,
        runtime_state={"state": "STOPPED"},
        validation_status={"commissioned": True, "stale_reasons": [], "overrides": [{"reason": "expert"}]},
        current_fingerprint=config_fingerprint(root),
    )
    assert any(item["code"] == "IN_PORT_MISSING" for item in result["findings"])


def test_failed_direction_is_non_overridable_production_block(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    result = evaluate_preflight(
        load_config(root),
        runtime_state={"state": "STOPPED"},
        validation_status={
            "commissioned": False,
            "stale_reasons": [],
            "record": {
                "test_results": [
                    {"test_id": "direction_in", "outcome": "FAILED"}
                ],
                "overrides": [{"reason": "cannot bypass"}],
            },
        },
        current_fingerprint=config_fingerprint(root),
    )
    assert any(
        item["code"] == "PHYSICAL_SAFETY_VALIDATION_FAILED"
        and item["level"] == "BLOCK"
        for item in result["findings"]
    )


def test_cli_preflight_human_json_and_exit_codes(tmp_path: Path, capsys) -> None:
    root = active_config(tmp_path)
    assert main(["--config-dir", str(root), "preflight"]) == 0
    assert "preflight:" in capsys.readouterr().out
    assert main(["--config-dir", str(root), "preflight", "--json"]) == 0
    assert "findings" in json.loads(capsys.readouterr().out)
    assert main(
        ["--config-dir", str(root), "preflight", "--require-commissioned"]
    ) == 2
    capsys.readouterr()
    pumps = json.loads((root / "pumps.json").read_text(encoding="utf-8"))
    pumps["pumps"]["IN"]["port"] = ""
    (root / "pumps.json").write_text(json.dumps(pumps), encoding="utf-8")
    assert main(["--config-dir", str(root), "preflight"]) == 2


def test_cli_validation_status_export_and_read_only(tmp_path: Path, capsys, monkeypatch) -> None:
    root = active_config(tmp_path)
    monkeypatch.setattr(
        "syringe_perfusion.a4.A4Pump.__init__",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("serial pump constructed")),
    )
    assert main(["--config-dir", str(root), "validation-status"]) == 0
    assert "status:" in capsys.readouterr().out
    assert main(["--config-dir", str(root), "validation-status", "--json"]) == 0
    assert "commissioned" in json.loads(capsys.readouterr().out)
    for format, suffix in (("json", "json"), ("csv", "csv"), ("markdown", "md")):
        output = tmp_path / f"report.{suffix}"
        assert main(
            ["--config-dir", str(root), "export-validation", "--format", format, "--output", str(output)]
        ) == 0
        capsys.readouterr()
        assert output.exists()


def write_history(root: Path) -> None:
    logs = root / "logs"
    logs.mkdir()
    path = logs / "a4pump_20260101.csv"
    fields = [
        "timestamp", "run_id", "dish_id", "condition", "trigger_source", "plan_id",
        "pump", "requested_flow_ml_min", "duration_s", "perfusion_state", "action", "note",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "timestamp": "2026-01-02T00:00:00",
                "run_id": "R2",
                "dish_id": "D2",
                "condition": "wash",
                "trigger_source": "NIS",
                "plan_id": "P2",
                "pump": "IN",
                "requested_flow_ml_min": "2",
                "duration_s": "30",
                "perfusion_state": "STARTING",
                "action": "start-forward",
                "note": "",
            }
        )
        writer.writerow(
            {
                "timestamp": "2026-01-01T00:00:00",
                "run_id": "R1",
                "dish_id": "D1",
                "condition": "stim",
                "trigger_source": "Manual",
                "plan_id": "P1",
                "pump": "OUT",
                "requested_flow_ml_min": "1",
                "duration_s": "60",
                "perfusion_state": "STOPPED",
                "action": "stop",
                "note": "operator stop",
            }
        )
    append_protocol_log(root, {"event": "state_transition", "run_id": "R2", "from": "STARTING", "to": "STARTED"})
    with (root / "runtime" / "protocol_runner.log").open("a", encoding="utf-8") as handle:
        handle.write("{malformed\n")


def test_run_history_normalization_order_limit_filter_and_malformed(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    write_history(root)
    runs = recent_runs(root, limit=20)
    assert [item["run_id"] for item in runs] == ["R2", "R1"]
    assert recent_runs(root, limit=1)[0]["run_id"] == "R2"
    assert recent_runs(root, dish_id="D1")[0]["condition"] == "stim"
    assert recent_runs(root, condition="wash")[0]["dish_id"] == "D2"


def test_run_history_exports_and_cli(tmp_path: Path, capsys) -> None:
    root = active_config(tmp_path)
    write_history(root)
    runs = recent_runs(root)
    for format, suffix in (("csv", "csv"), ("json", "json"), ("markdown", "md")):
        path = export_runs(runs, tmp_path / f"runs.{suffix}", format=format)
        assert path.exists()
        assert path.stat().st_size > 10
    assert main(["--config-dir", str(root), "recent-runs", "--limit", "20"]) == 0
    assert "R2" in capsys.readouterr().out
    assert main(["--config-dir", str(root), "recent-runs", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["run_id"] == "R2"


def test_report_separates_evidence_and_never_claims_hardware_complete(tmp_path: Path) -> None:
    root = active_config(tmp_path)
    store = ValidationStore(root, now=lambda: "2026-01-01T00:00:00+00:00")
    record = store.create(
        operator="operator",
        validation_id="VALIDATION-DETERMINISTIC",
        build_id="BUILD",
    )
    record["test_results"].append(
        {
            "test_id": "direction_in",
            "display_name": "Direction",
            "evidence_type": "UART COMMAND COMPLETED",
            "outcome": "UART COMMAND COMPLETED",
            "note": "not observed",
        }
    )
    record["overrides"].append({"timestamp": "t", "operator": "op", "reason": "bench setup"})
    store.save(record)
    report = store.export("markdown", tmp_path / "report.md").read_text(encoding="utf-8")
    assert "software checks, UART completion, manual observations, and measured evidence" in report
    assert "Hardware validated" not in report
    assert "bench setup" in report
    second = store.export("markdown", tmp_path / "report_second.md").read_text(encoding="utf-8")
    assert second == report
