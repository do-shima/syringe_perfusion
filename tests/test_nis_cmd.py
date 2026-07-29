from __future__ import annotations

from pathlib import Path


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
        assert "COM4" not in text and "COM5" not in text
        for line in text.splitlines():
            if line.strip().startswith('"%A4%"'):
                assert line.strip().endswith("2>&1")


def test_primary_wrappers_exist() -> None:
    for name in (
        "pump_write_in_out.cmd",
        "pump_start_pushpull_fast30.cmd",
        "pump_stop_all.cmd",
    ):
        assert (ROOT / "nis_cmd" / name).is_file()
