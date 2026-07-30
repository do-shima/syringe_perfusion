from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_all_cmd_wrappers_are_crlf_one_line_commands_and_shared_config() -> None:
    wrappers = sorted((ROOT / "nis_cmd").glob("*.cmd"))
    assert wrappers
    for path in wrappers:
        raw = path.read_bytes()
        text = raw.decode("ascii")
        assert b"\r\n" in raw
        assert raw.replace(b"\r\n", b"").find(b"\n") == -1
        assert "^" not in text
        assert 'set "CFG=%ROOT%\\config"' in text
        assert re.search(r"(?i)\bCOM\d+\b", text) is None
        assert re.search(r"(?i)[A-Z]:\\Users\\|\\Users\\[^%]", text) is None
        assert "%ROOT%" in text
        assert '--config-dir "%CFG%"' in text
        assert " START " in text
        assert " END " in text
        for line in text.splitlines():
            if line.strip().startswith('"%A4%"'):
                assert line.strip().endswith("2>&1")


def test_primary_wrappers_exist() -> None:
    for name in (
        "pump_start_armed.cmd",
        "pump_start_armed_after_300s.cmd",
        "pump_cancel_pending.cmd",
        "pump_write_in_out.cmd",
        "pump_start_pushpull_fast30.cmd",
        "pump_stop_all.cmd",
    ):
        assert (ROOT / "nis_cmd" / name).is_file()


def test_delayed_armed_wrapper_delegates_to_detached_scheduler() -> None:
    text = (ROOT / "nis_cmd" / "pump_start_armed_after_300s.cmd").read_text(encoding="ascii")
    assert "schedule-armed --delay-s 300" in text
    assert "timeout " not in text.casefold()


def test_preferred_armed_and_deprecated_legacy_wrappers_are_explicit() -> None:
    immediate = (ROOT / "nis_cmd" / "pump_start_armed.cmd").read_text(encoding="ascii")
    delayed = (ROOT / "nis_cmd" / "pump_start_armed_after_300s.cmd").read_text(encoding="ascii")
    legacy = (ROOT / "nis_cmd" / "pump_start_pushpull_fast30.cmd").read_text(encoding="ascii")
    assert " start-armed " in immediate
    assert " schedule-armed --delay-s 300 " in delayed
    assert "DEPRECATED" in legacy
    assert "pump_start_armed.cmd" in legacy
