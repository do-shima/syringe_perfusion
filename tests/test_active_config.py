from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import syringe_perfusion.config as config_module
from syringe_perfusion.cli import main
from syringe_perfusion.config import (
    REQUIRED_CONFIG_FILES,
    ConfigResolution,
    load_config,
    persist_active_config_dir,
    resolve_config,
    save_pump_settings,
)


ROOT_CONFIG = Path(__file__).resolve().parents[1] / "config"


def copy_config(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    for filename in REQUIRED_CONFIG_FILES:
        (destination / filename).write_bytes((ROOT_CONFIG / filename).read_bytes())
    return destination


def isolated_env(tmp_path: Path) -> dict[str, str]:
    return {"LOCALAPPDATA": str(tmp_path / "local")}


def test_resolution_precedence_explicit_environment_persisted(tmp_path: Path) -> None:
    explicit = copy_config(tmp_path / "explicit")
    environment = copy_config(tmp_path / "environment")
    persisted = copy_config(tmp_path / "persisted")
    env = isolated_env(tmp_path)
    env["A4PUMP_CONFIG_DIR"] = str(environment)
    settings = tmp_path / "settings.json"
    persist_active_config_dir(persisted, settings_file=settings)

    assert resolve_config(explicit, environ=env, settings_file=settings).source == "explicit"
    assert resolve_config(environ=env, settings_file=settings).active_config_dir == environment.resolve()
    del env["A4PUMP_CONFIG_DIR"]
    result = resolve_config(environ=env, settings_file=settings)
    assert result.source == "persisted_user_choice"
    assert result.active_config_dir == persisted.resolve()


def test_frozen_ignores_cwd_and_uses_exe_adjacent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = tmp_path / "kit"
    expected = copy_config(install / "config")
    copy_config(tmp_path / "launch" / "config")
    monkeypatch.chdir(tmp_path / "launch")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "A4PumpGUI.exe"))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    result = resolve_config(
        environ=isolated_env(tmp_path),
        settings_file=tmp_path / "missing-settings.json",
    )
    assert result.source == "exe_adjacent"
    assert result.active_config_dir == expected.resolve()


def test_frozen_packaged_defaults_only_fill_missing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = tmp_path / "kit"
    active = install / "config"
    active.mkdir(parents=True)
    original = b'{"pumps":{"keep":"existing"}}\n'
    (active / "pumps.json").write_bytes(original)
    bundle = copy_config(tmp_path / "bundle" / "default_config")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "A4PumpGUI.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle.parent), raising=False)

    result = resolve_config(
        environ=isolated_env(tmp_path),
        settings_file=tmp_path / "missing-settings.json",
    )
    assert result.active_config_dir == active.resolve()
    assert result.active_config_dir != bundle.resolve()
    assert result.required_files_present
    assert (active / "pumps.json").read_bytes() == original
    assert all((active / name).exists() for name in REQUIRED_CONFIG_FILES)


def test_cli_nested_executable_uses_kit_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit = tmp_path / "kit"
    expected = copy_config(kit / "config")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(kit / "a4ctl" / "a4ctl.exe"))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    result = resolve_config(
        environ=isolated_env(tmp_path),
        settings_file=tmp_path / "missing-settings.json",
    )
    assert result.active_config_dir == expected.resolve()


def test_frozen_unwritable_exe_adjacent_falls_back_to_localappdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = tmp_path / "protected-kit"
    bundle = copy_config(tmp_path / "bundle" / "config")
    env = isolated_env(tmp_path)
    local = Path(env["LOCALAPPDATA"]) / "A4PumpControl" / "config"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "A4PumpGUI.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle.parent), raising=False)
    monkeypatch.setattr(
        config_module,
        "_is_writable_config_dir",
        lambda path: path.resolve() != (install / "config").resolve(),
    )

    result = resolve_config(
        environ=env,
        settings_file=tmp_path / "missing-settings.json",
    )
    assert result.source == "localappdata"
    assert result.active_config_dir == local.resolve()
    assert result.required_files_present


def test_source_run_uses_repository_after_empty_localappdata(tmp_path: Path) -> None:
    result = resolve_config(
        environ=isolated_env(tmp_path),
        settings_file=tmp_path / "missing-settings.json",
    )
    assert result.source == "source_repository"
    assert result.required_files_present


def test_save_reload_preserves_unknown_keys_commands_and_creates_backup(tmp_path: Path) -> None:
    active = copy_config(tmp_path / "config")
    pumps_path = active / "pumps.json"
    document = json.loads(pumps_path.read_text(encoding="utf-8"))
    document["site_extension"] = {"keep": True}
    document["pumps"]["IN"]["unknown"] = "keep"
    pumps_path.write_text(json.dumps(document), encoding="utf-8")
    commands = document["pumps"]["IN"]["commands"]

    saved = save_pump_settings(
        active,
        in_port=" COM_A ",
        out_enabled=True,
        out_port=" COM_B ",
        baudrate="9600",
        terminator="\\r\\n",
        timeout="1.5",
    )
    reloaded_document = json.loads(saved.read_text(encoding="utf-8"))
    loaded = load_config(active)
    assert loaded["pumps"]["IN"]["port"] == "COM_A"
    assert loaded["pumps"]["OUT"]["port"] == "COM_B"
    assert loaded["pumps"]["OUT"]["enabled"] is True
    assert reloaded_document["site_extension"] == {"keep": True}
    assert reloaded_document["pumps"]["IN"]["unknown"] == "keep"
    assert reloaded_document["pumps"]["IN"]["commands"] == commands
    assert saved.with_name("pumps.json.bak").exists()
    assert saved.read_bytes().endswith(b"\n")
    assert not list(active.glob("*.tmp"))


def test_same_enabled_com_and_read_only_are_rejected(tmp_path: Path) -> None:
    active = copy_config(tmp_path / "config")
    with pytest.raises(ValueError, match="different COM"):
        save_pump_settings(
            active,
            in_port="COM_A",
            out_enabled=True,
            out_port="com_a",
            baudrate=9600,
            terminator="\\r\\n",
            timeout=1,
        )
    read_only = ConfigResolution(
        active_config_dir=active,
        active_pumps_json=active / "pumps.json",
        source="explicit",
        writable=False,
        packaged_default_dir=None,
        required_files_present=True,
        missing_files=[],
    )
    with pytest.raises(PermissionError, match="read-only"):
        save_pump_settings(
            read_only,
            in_port="COM_A",
            out_enabled=True,
            out_port="COM_B",
            baudrate=9600,
            terminator="\\r\\n",
            timeout=1,
        )


def test_cli_config_path_json_reports_explicit_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    active = copy_config(tmp_path / "config")
    assert main(["--config-dir", str(active), "config-path", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert Path(output["active_config_dir"]) == active.resolve()
    assert Path(output["active_pumps_json"]) == (active / "pumps.json").resolve()
    assert output["source"] == "explicit"


def test_cli_omitted_config_dir_reads_persisted_gui_choice(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = copy_config(tmp_path / "chosen")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("A4PUMP_CONFIG_DIR", raising=False)
    persist_active_config_dir(active)
    assert main(["config-path", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert Path(output["active_config_dir"]) == active.resolve()
    assert output["source"] == "persisted_user_choice"
