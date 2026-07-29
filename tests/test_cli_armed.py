from __future__ import annotations

import json
from pathlib import Path

from syringe_perfusion.cli import main
from syringe_perfusion.perfusion_state import write_state


def test_arm_status_human_and_json(tmp_path: Path, capsys) -> None:
    active = tmp_path / "config"
    active.mkdir()
    write_state(
        active,
        {
            "state": "ARMED",
            "plan_id": "PLAN-1",
            "armed_at": "2026-01-01T00:00:00+00:00",
            "plan": {
                "programmed_duration_s": 30,
                "pumps": {"IN": {"port": "COM_A"}, "OUT": {"port": "COM_B"}},
            },
        },
    )
    assert main(["--config-dir", str(active), "arm-status"]) == 0
    assert "state: ARMED" in capsys.readouterr().out
    assert main(["--config-dir", str(active), "arm-status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["plan_id"] == "PLAN-1"


def test_start_armed_dispatch_and_dirty_refusal(tmp_path: Path, monkeypatch, capsys) -> None:
    active = tmp_path / "config"
    active.mkdir()
    called = []
    monkeypatch.setattr(
        "syringe_perfusion.cli.start_armed_pair",
        lambda resolution, **kwargs: called.append((resolution.active_config_dir, kwargs)) or {"state": "STARTED"},
    )
    assert main(["--config-dir", str(active), "start-armed", "--trigger-source", "NIS"]) == 0
    assert called[0][0] == active.resolve()
    assert json.loads(capsys.readouterr().out)["state"] == "STARTED"


def test_schedule_returns_run_id_and_preserves_explicit_config(tmp_path: Path, monkeypatch, capsys) -> None:
    active = tmp_path / "config"
    active.mkdir()
    captured = {}

    def fake_schedule(resolution, **kwargs):
        captured.update(kwargs)
        captured["config"] = resolution.active_config_dir
        return {"run_id": "RUN-1"}

    monkeypatch.setattr("syringe_perfusion.cli.schedule_armed", fake_schedule)
    assert main(["--config-dir", str(active), "schedule-armed", "--delay-s", "300"]) == 0
    assert capsys.readouterr().out.strip() == "RUN-1"
    assert captured["config"] == active.resolve()
    assert captured["delay_s"] == 300
