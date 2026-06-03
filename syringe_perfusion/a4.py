from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .config import decode_terminator


DEFAULT_COMMANDS = {
    "start_forward": "q6h2d",
    "start_reverse": "q6h3d",
    "manual_forward": "q6h4d",
    "manual_reverse": "q6h5d",
    "stop": "q6h6d",
    "save": "q6h1d",
}


def _validate_jog_duration(duration_ms: int) -> None:
    if duration_ms < 50 or duration_ms > 10000:
        raise ValueError("duration_ms must be between 50 and 10000")


def format_speed_commands(speed_mm_min: float) -> list[str]:
    raw_speed = Decimal(str(speed_mm_min))
    if raw_speed < Decimal("0.01"):
        raise ValueError("speed_mm_min must be between 0.01 and 150.00")
    speed = raw_speed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if speed < Decimal("0.01") or speed > Decimal("150.00"):
        raise ValueError("speed_mm_min must be between 0.01 and 150.00")
    integer = int(speed)
    fraction = int((speed - Decimal(integer)) * 100)
    return [f"q1h{integer:02d}d", f"q2h{fraction:02d}d"]


def format_time_commands(duration_s: float) -> list[str]:
    rounded_seconds = int(Decimal(str(duration_s)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if rounded_seconds <= 0:
        raise ValueError("duration_s must be positive")
    max_seconds = (99 * 3600) + (59 * 60) + 59
    if rounded_seconds > max_seconds:
        raise ValueError("duration_s must not exceed 99:59:59")
    hours = rounded_seconds // 3600
    remainder = rounded_seconds % 3600
    minutes = remainder // 60
    seconds = remainder % 60
    return [f"q3h{hours:02d}d", f"q4h{minutes:02d}d", f"q5h{seconds:02d}d"]


def format_settings_commands(speed_mm_min: float, duration_s: float, *, save: bool = True) -> list[str]:
    commands = format_speed_commands(speed_mm_min) + format_time_commands(duration_s)
    if save:
        commands.append(DEFAULT_COMMANDS["save"])
    return commands


@dataclass
class A4Pump:
    name: str
    port: str
    baudrate: int = 9600
    terminator: str = "\\r\\n"
    timeout: float = 1.0
    dry_run: bool = False
    commands: dict[str, str] = field(default_factory=lambda: DEFAULT_COMMANDS.copy())

    def start_forward(self) -> dict[str, Any]:
        return self.send_raw(self.commands.get("start_forward", DEFAULT_COMMANDS["start_forward"]))

    def start_reverse(self) -> dict[str, Any]:
        return self.send_raw(self.commands.get("start_reverse", DEFAULT_COMMANDS["start_reverse"]))

    def manual_forward(self) -> dict[str, Any]:
        return self.send_raw(self.commands.get("manual_forward", DEFAULT_COMMANDS["manual_forward"]))

    def manual_reverse(self) -> dict[str, Any]:
        return self.send_raw(self.commands.get("manual_reverse", DEFAULT_COMMANDS["manual_reverse"]))

    def stop(self) -> dict[str, Any]:
        return self.send_raw(self.commands.get("stop", DEFAULT_COMMANDS["stop"]))

    def save(self) -> dict[str, Any]:
        return self.send_raw(self.commands.get("save", DEFAULT_COMMANDS["save"]))

    def set_speed(self, speed_mm_min: float) -> list[dict[str, Any]]:
        return self.send_sequence(format_speed_commands(speed_mm_min))

    def set_time(self, duration_s: float) -> list[dict[str, Any]]:
        return self.send_sequence(format_time_commands(duration_s))

    def write_settings(self, speed_mm_min: float, duration_s: float, *, save: bool = True) -> list[dict[str, Any]]:
        return self.send_sequence(format_settings_commands(speed_mm_min, duration_s, save=save))

    def write_profile_settings(self, speed_mm_min: float, duration_s: float, *, save: bool = True) -> list[dict[str, Any]]:
        return self.write_settings(speed_mm_min, duration_s, save=save)

    def jog_forward(self, duration_ms: int = 1000) -> list[dict[str, Any]]:
        return self._jog("manual_forward", duration_ms)

    def jog_reverse(self, duration_ms: int = 1000) -> list[dict[str, Any]]:
        return self._jog("manual_reverse", duration_ms)

    def send_sequence(self, commands: list[str], delay_s: float = 0.2) -> list[dict[str, Any]]:
        if delay_s < 0:
            raise ValueError("delay_s must be zero or positive")
        results = []
        for index, command in enumerate(commands):
            result = self.send_raw(command)
            result["sequence_index"] = index
            results.append(result)
            if index < len(commands) - 1 and delay_s > 0 and not self.dry_run:
                time.sleep(delay_s)
        return results

    def _jog(self, start_method: str, duration_ms: int) -> list[dict[str, Any]]:
        _validate_jog_duration(duration_ms)
        results: list[dict[str, Any]] = []
        try:
            start_result = getattr(self, start_method)()
            start_result["sequence_index"] = 0
            results.append(start_result)
            if not self.dry_run:
                time.sleep(duration_ms / 1000)
        finally:
            stop_result = self.stop()
            stop_result["sequence_index"] = 1
            results.append(stop_result)
        return results

    def send_raw(self, command: str) -> dict[str, Any]:
        timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        terminator = decode_terminator(self.terminator)
        outgoing = f"{command}{terminator}".encode("ascii")

        base_result = {
            "timestamp": timestamp,
            "pump": self.name,
            "port": self.port,
            "baudrate": self.baudrate,
            "command": command,
            "terminator": self.terminator,
            "outgoing_repr": repr(outgoing),
            "outgoing_hex": outgoing.hex(" "),
        }

        if self.dry_run:
            return {
                **base_result,
                "response": "DRY_RUN",
                "response_hex": "",
                "dry_run": True,
            }

        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial is required for serial communication") from exc

        with serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
            write_timeout=self.timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        ) as ser:
            # Some USB-UART devices need a short settling time after opening.
            time.sleep(0.2)

            # Do not rely on any previous buffered bytes.
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            # Keep hardware control lines inactive.
            # Usually irrelevant for 3-wire UART, but useful for reproducibility.
            try:
                ser.dtr = False
                ser.rts = False
            except Exception:
                pass

            ser.write(outgoing)
            ser.flush()

            # Wait for possible echo/response.
            time.sleep(0.3)
            raw_response = ser.read_all()

        response = raw_response.decode("ascii", errors="replace").strip()

        return {
            **base_result,
            "response": response,
            "response_hex": raw_response.hex(" "),
            "dry_run": False,
        }


def pump_from_config(pump_key: str, pump_config: dict[str, Any], *, dry_run: bool = False) -> A4Pump:
    commands = DEFAULT_COMMANDS.copy()
    commands.update(pump_config.get("commands", {}))
    normalized_commands = {key: str(value).lower() for key, value in commands.items()}
    return A4Pump(
        name=pump_key,
        port=pump_config["port"],
        baudrate=int(pump_config.get("baudrate", 9600)),
        terminator=pump_config.get("terminator", "\\r\\n"),
        timeout=float(pump_config.get("timeout", 1.0)),
        dry_run=dry_run,
        commands=normalized_commands,
    )


def list_serial_ports() -> list[dict[str, str]]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []

    ports = []
    for port in list_ports.comports():
        ports.append(
            {
                "device": port.device,
                "description": port.description,
                "hwid": port.hwid,
            }
        )
    return ports
