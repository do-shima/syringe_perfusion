from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import decode_terminator


DEFAULT_COMMANDS = {
    "start_forward": "Q6H2D",
    "start_reverse": "Q6H3D",
    "stop": "Q6H6D",
}


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

    def stop(self) -> dict[str, Any]:
        return self.send_raw(self.commands.get("stop", DEFAULT_COMMANDS["stop"]))

    def send_raw(self, command: str) -> dict[str, Any]:
        timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        terminator = decode_terminator(self.terminator)
        outgoing = f"{command}{terminator}".encode("ascii")

        if self.dry_run:
            return {
                "timestamp": timestamp,
                "pump": self.name,
                "port": self.port,
                "baudrate": self.baudrate,
                "command": command,
                "terminator": self.terminator,
                "response": "DRY_RUN",
                "dry_run": True,
            }

        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial is required for serial communication") from exc

        with serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
            write_timeout=self.timeout,
        ) as ser:
            ser.write(outgoing)
            ser.flush()
            if terminator:
                raw_response = ser.read_until(terminator.encode("ascii"), size=256)
            else:
                raw_response = ser.read(256)

        response = raw_response.decode("ascii", errors="replace").strip()
        return {
            "timestamp": timestamp,
            "pump": self.name,
            "port": self.port,
            "baudrate": self.baudrate,
            "command": command,
            "terminator": self.terminator,
            "response": response,
            "dry_run": False,
        }


def pump_from_config(pump_key: str, pump_config: dict[str, Any], *, dry_run: bool = False) -> A4Pump:
    return A4Pump(
        name=pump_key,
        port=pump_config["port"],
        baudrate=int(pump_config.get("baudrate", 9600)),
        terminator=pump_config.get("terminator", "\\r\\n"),
        timeout=float(pump_config.get("timeout", 1.0)),
        dry_run=dry_run,
        commands=pump_config.get("commands", DEFAULT_COMMANDS).copy(),
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
