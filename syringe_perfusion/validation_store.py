from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from .app_info import (
    APP_VERSION,
    CONTROL_COMPATIBILITY_VERSION,
    get_build_info,
    package_version,
)
from .calibration import flow_point_status
from .commissioning import (
    NOT_VALIDATED,
    dependency_snapshot,
    required_physical_current,
    staleness_reasons,
)
from .config import ConfigResolution, load_config, resolve_config
from .perfusion_state import process_file_lock


SCHEMA_VERSION = 2
ExportFormat = Literal["json", "csv", "markdown"]


@dataclass(frozen=True)
class ValidationPaths:
    root: Path
    state: Path
    measurements: Path
    events: Path
    reports: Path
    history: Path
    lock: Path


def validation_paths(config: str | Path | ConfigResolution) -> ValidationPaths:
    resolution = config if isinstance(config, ConfigResolution) else resolve_config(config)
    root = resolution.active_config_dir / "validation"
    return ValidationPaths(
        root=root,
        state=root / "commissioning_state.json",
        measurements=root / "measurements.csv",
        events=root / "validation_events.jsonl",
        reports=root / "reports",
        history=root / "history",
        lock=root / "validation.lock",
    )


class ValidationStore:
    def __init__(
        self,
        config: str | Path | ConfigResolution,
        *,
        now: Callable[[], str] | None = None,
    ) -> None:
        self.resolution = config if isinstance(config, ConfigResolution) else resolve_config(config)
        self.paths = validation_paths(self.resolution)
        self.now = now or _now_iso

    def load(self) -> dict[str, Any] | None:
        try:
            with self.paths.state.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else None
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, OSError, UnicodeError) as exc:
            return {
                "schema_version": 0,
                "validation_id": "",
                "status": "COMMISSIONING FAILED",
                "operator": "",
                "completed_at": "",
                "dependencies": {},
                "test_results": [],
                "measurement_results": [],
                "manual_confirmations": [],
                "overrides": [],
                "failures": [
                    {
                        "test_id": "validation_storage",
                        "note": f"commissioning_state.json could not be read: {exc}",
                    }
                ],
                "notes": [],
            }

    def create(
        self,
        *,
        operator: str,
        laboratory_note: str = "",
        detected_ports: list[dict[str, Any]] | None = None,
        validation_id: str | None = None,
        build_id: str | None = None,
    ) -> dict[str, Any]:
        data = load_config(self.resolution)
        now = self.now()
        actual_validation_id = validation_id or str(uuid.uuid4())
        port_lookup = {
            str(item.get("device", "")).casefold(): item for item in (detected_ports or [])
        }
        pumps: dict[str, Any] = {}
        for role, cfg in data.get("pumps", {}).items():
            detected = port_lookup.get(str(cfg.get("port", "")).casefold(), {})
            identity = {**dict(cfg.get("hardware_identity") or {}), **detected}
            pumps[role] = {
                "device": cfg.get("port", ""),
                "port": cfg.get("port", ""),
                "hardware_identity": identity,
                "baudrate": cfg.get("baudrate", 9600),
                "terminator": cfg.get("terminator", "\\r\\n"),
                "timeout": cfg.get("timeout", 1.0),
                "enabled": bool(cfg.get("enabled", True)),
                "direction": "forward" if role == "IN" else "reverse",
            }
        dependencies = dependency_snapshot(
            data,
            config_dir=str(self.resolution.active_config_dir),
            application_version=APP_VERSION,
            control_compatibility_version=CONTROL_COMPATIBILITY_VERSION,
        )
        for role, pump in pumps.items():
            if role in dependencies["pumps"]:
                dependencies["pumps"][role]["hardware_identity"] = dict(
                    pump.get("hardware_identity") or {}
                )
        build_identity = dict(get_build_info())
        if build_id is not None:
            build_identity["git_commit"] = build_id
            build_identity["git_commit_short"] = build_id[:7]
        record = {
            "schema_version": SCHEMA_VERSION,
            "validation_id": actual_validation_id,
            "created_at": now,
            "updated_at": now,
            "completed_at": "",
            "status": "SOFTWARE READY — HARDWARE VALIDATION INCOMPLETE",
            "operator": operator,
            "laboratory_or_workstation_note": laboratory_note,
            "application_version": APP_VERSION,
            "human_version": APP_VERSION,
            "package_version": package_version(),
            "build_identifier": build_identity.get("git_commit_short", ""),
            "build_identity": build_identity,
            "build_commit": build_identity.get("git_commit", ""),
            "build_dirty": build_identity.get("git_dirty"),
            "build_timestamp_utc": build_identity.get("build_timestamp_utc", ""),
            "build_identity_fingerprint": build_identity.get(
                "build_identity_fingerprint", ""
            ),
            "control_compatibility_version": CONTROL_COMPATIBILITY_VERSION,
            "active_config_path": str(self.resolution.active_config_dir),
            "config_fingerprint": dependencies["config_fingerprint"],
            "dependencies": dependencies,
            "pumps": pumps,
            "selected_syringes": {},
            "test_results": [],
            "measurement_results": [],
            "manual_confirmations": [],
            "overrides": [],
            "failures": [],
            "notes": [],
            "stale_reasons": [],
        }
        for role, key in (("IN", _default_syringe(data)), ("OUT", _default_syringe(data))):
            syringe = data.get("syringes", {}).get(key, {})
            record["selected_syringes"][role] = {
                "key": key,
                "calibrated_ul_per_mm": syringe.get("calibrated_ul_per_mm"),
            }
        return record

    def save(self, record: dict[str, Any], *, event: str = "record_saved") -> Path:
        document = dict(record)
        document.setdefault("schema_version", SCHEMA_VERSION)
        document["updated_at"] = self.now()
        tests = list(document.get("test_results") or [])
        failures = [
            *[item for item in tests if item.get("outcome") == "FAILED"],
            *list(document.get("failures") or []),
        ]
        try:
            data = load_config(self.resolution)
            complete = required_physical_current(
                tests,
                out_enabled=bool(data.get("pumps", {}).get("OUT", {}).get("enabled", False)),
            )
        except Exception:
            complete = False
        if failures:
            document["status"] = "COMMISSIONING FAILED"
        elif complete:
            document["status"] = "COMMISSIONING CURRENT"
            document["completed_at"] = document.get("completed_at") or self.now()
        elif tests:
            document["status"] = "COMMISSIONING PARTIAL"
        else:
            document["status"] = "SOFTWARE READY — HARDWARE VALIDATION INCOMPLETE"
        self.paths.root.mkdir(parents=True, exist_ok=True)
        with process_file_lock(
            self.paths.lock,
            owner=f"validation:{os.getpid()}",
            operation="validation_save",
        ):
            current = self.load()
            if current and current != document:
                self.paths.history.mkdir(parents=True, exist_ok=True)
                archive = self.paths.history / (
                    f"{current.get('validation_id', 'unknown')}_{_filename_stamp(self.now())}_"
                    f"{uuid.uuid4().hex[:8]}.json"
                )
                _atomic_json(archive, current)
            _atomic_json(self.paths.state, document)
            self._append_event_unlocked(
                {
                    "timestamp": self.now(),
                    "event": event,
                    "validation_id": document.get("validation_id", ""),
                    "status": document.get("status", ""),
                }
            )
        return self.paths.state

    def append_measurement(self, measurement: dict[str, Any]) -> Path:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        fields = sorted(measurement)
        with process_file_lock(
            self.paths.lock,
            owner=f"measurement:{os.getpid()}",
            operation="validation_measurement",
        ):
            exists = self.paths.measurements.exists() and self.paths.measurements.stat().st_size > 0
            with self.paths.measurements.open("a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                if not exists:
                    writer.writeheader()
                writer.writerow(measurement)
                handle.flush()
                os.fsync(handle.fileno())
        return self.paths.measurements

    def append_event(self, event: dict[str, Any]) -> Path:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        with process_file_lock(
            self.paths.lock,
            owner=f"validation-event:{os.getpid()}",
            operation="validation_event",
        ):
            self._append_event_unlocked({"timestamp": self.now(), **event})
        return self.paths.events

    def status(
        self,
        *,
        data: dict[str, Any] | None = None,
        detected_ports: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        record = self.load()
        if record is None:
            return {
                "status": "SOFTWARE READY — HARDWARE VALIDATION INCOMPLETE",
                "current": False,
                "commissioned": False,
                "last_completed_at": "",
                "stale_reasons": [],
                "validation_id": "",
                "flow_points": flow_point_status([]),
                "record": None,
            }
        config_data = data or load_config(self.resolution)
        current_dependencies = dependency_snapshot(
            config_data,
            config_dir=str(self.resolution.active_config_dir),
            application_version=APP_VERSION,
            control_compatibility_version=CONTROL_COMPATIBILITY_VERSION,
        )
        detected = {
            str(item.get("device", "")).casefold(): item for item in (detected_ports or [])
        }
        for role, pump in current_dependencies.get("pumps", {}).items():
            identity = detected.get(str(pump.get("port", "")).casefold())
            if identity:
                pump["hardware_identity"] = dict(identity)
        reasons = staleness_reasons(record.get("dependencies"), current_dependencies)
        tests = list(record.get("test_results") or [])
        failures = [
            *[item for item in tests if item.get("outcome") == "FAILED"],
            *list(record.get("failures") or []),
        ]
        commissioned = required_physical_current(
            tests,
            out_enabled=bool(config_data.get("pumps", {}).get("OUT", {}).get("enabled", False)),
        )
        if failures:
            status = "COMMISSIONING FAILED"
        elif reasons:
            status = "COMMISSIONING STALE"
        elif commissioned:
            status = "COMMISSIONING CURRENT"
        elif tests:
            status = "COMMISSIONING PARTIAL"
        else:
            status = "SOFTWARE READY — HARDWARE VALIDATION INCOMPLETE"
        return {
            "status": status,
            "current": not reasons,
            "commissioned": commissioned and not reasons and not failures,
            "last_completed_at": record.get("completed_at", ""),
            "stale_reasons": reasons,
            "validation_id": record.get("validation_id", ""),
            "flow_points": flow_point_status(record.get("measurement_results", [])),
            "record": record,
        }

    def export(
        self,
        format: ExportFormat,
        output: str | Path | None = None,
    ) -> Path:
        status = self.status()
        record = status.get("record") or {
            "schema_version": SCHEMA_VERSION,
            "status": status["status"],
            "test_results": [],
            "measurement_results": [],
        }
        extension = {"json": "json", "csv": "csv", "markdown": "md"}[format]
        path = (
            Path(output).resolve()
            if output is not None
            else self.paths.reports
            / f"commissioning_report_{_filename_stamp(self.now())}.{extension}"
        )
        if format == "json":
            _atomic_json(path, {"summary": _public_status(status), "record": record})
        elif format == "csv":
            _atomic_text(path, _report_csv(record))
        else:
            _atomic_text(path, _report_markdown(record, status))
        return path

    def _append_event_unlocked(self, event: dict[str, Any]) -> None:
        self.paths.events.parent.mkdir(parents=True, exist_ok=True)
        with self.paths.events.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def build_identifier() -> str:
    """Backward-compatible accessor for the current traceable build commit."""
    return str(get_build_info().get("git_commit_short", ""))


def _report_markdown(record: dict[str, Any], status: dict[str, Any]) -> str:
    lines = [
        "# Pump Commissioning Report",
        "",
        f"- Status: **{status['status']}**",
        f"- Validation ID: `{record.get('validation_id', '')}`",
        f"- Operator: {record.get('operator', '')}",
        f"- Application: {record.get('application_version', '')}",
        f"- Package version: {record.get('package_version', '')}",
        f"- Build: {record.get('build_identifier', '')}",
        f"- Build timestamp: {record.get('build_timestamp_utc', '')}",
        f"- Build clean: {record.get('build_dirty') is False}",
        f"- Control compatibility: {record.get('control_compatibility_version', '')}",
        f"- Build fingerprint: `{record.get('build_identity_fingerprint', '')}`",
        f"- Active Config: `{record.get('active_config_path', '')}`",
        f"- Config fingerprint: `{record.get('config_fingerprint', '')}`",
        "",
        "This report separates software checks, UART completion, manual observations, and measured evidence.",
        "A UART command completing is not hardware readback or proof of physical motion.",
        "",
        "## Test results",
        "",
        "| Test | Evidence | Outcome | Operator note |",
        "|---|---|---|---|",
    ]
    for item in record.get("test_results", []):
        lines.append(
            f"| {item.get('display_name', item.get('test_id', ''))} | "
            f"{item.get('evidence_type', NOT_VALIDATED)} | {item.get('outcome', NOT_VALIDATED)} | "
            f"{str(item.get('note', '')).replace('|', '/')} |"
        )
    if not record.get("test_results"):
        lines.append("| No checks performed | NOT VALIDATED | NOT VALIDATED | |")
    lines.extend(["", "## Pump identity and communication targets", ""])
    for role, pump in record.get("pumps", {}).items():
        identity = pump.get("hardware_identity") or {}
        lines.append(
            f"- {role}: port `{pump.get('port', '')}`, baud {pump.get('baudrate', '')}, "
            f"terminator `{pump.get('terminator', '')}`, timeout {pump.get('timeout', '')}; "
            f"HWID `{identity.get('hwid', '')}`, serial `{identity.get('serial_number', '')}`"
        )
    lines.extend(["", "## Syringe calibration snapshot", ""])
    for role, syringe in record.get("selected_syringes", {}).items():
        lines.append(
            f"- {role}: `{syringe.get('key', '')}`, "
            f"calibrated_ul_per_mm={syringe.get('calibrated_ul_per_mm', '')}"
        )
    lines.extend(["", "## Measured results", ""])
    if record.get("measurement_results"):
        for index, measurement in enumerate(record["measurement_results"], start=1):
            lines.append(
                f"{index}. {measurement.get('pump_role', '')} {measurement.get('direction', '')}: "
                f"{measurement.get('measured_volume_ul', '')} µL, "
                f"{measurement.get('measured_flow_ml_min', '')} mL/min, "
                f"candidate {measurement.get('candidate_ul_per_mm', '')} µL/mm "
                f"({measurement.get('measurement_method', '')})"
            )
    else:
        lines.append("- No measured results entered.")
    lines.extend(["", "## Stale and failed items", ""])
    for reason in status.get("stale_reasons", []):
        lines.append(f"- STALE: {reason}")
    for failure in record.get("failures", []):
        lines.append(f"- FAILED: {failure}")
    if not status.get("stale_reasons") and not record.get("failures"):
        lines.append("- None recorded.")
    lines.extend(["", "## Overrides", ""])
    if record.get("overrides"):
        for override in record["overrides"]:
            lines.append(
                f"- {override.get('timestamp', '')}: {override.get('operator', '')} — "
                f"{override.get('reason', '')}"
            )
    else:
        lines.append("- None.")
    lines.extend(["", "## Session acknowledgements and manual confirmations", ""])
    if record.get("manual_confirmations"):
        for confirmation in record["manual_confirmations"]:
            lines.append(
                f"- {confirmation.get('timestamp', '')}: {confirmation.get('operator', '')} — "
                f"{confirmation.get('event', 'confirmation')}: {confirmation.get('reason', '')}"
            )
    else:
        lines.append("- None.")
    lines.extend(["", "## Remaining required checks", ""])
    if status.get("commissioned"):
        lines.append("- Required basic physical commissioning checks are current.")
    else:
        lines.append("- Physical direction and emergency STOP confirmation remain required.")
        lines.append("- Flow, reverse-flow, balance, and workstation validation remain evidence-specific.")
    return "\n".join(lines) + "\n"


def _report_csv(record: dict[str, Any]) -> str:
    output = io.StringIO(newline="")
    fields = [
        "record_type",
        "validation_id",
        "test_id",
        "display_name",
        "evidence_type",
        "outcome",
        "pump_role",
        "direction",
        "completed_at",
        "operator",
        "note",
        "data_json",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for item in record.get("test_results", []):
        writer.writerow(
            {
                "validation_id": record.get("validation_id", ""),
                "record_type": "test",
                "test_id": item.get("test_id", ""),
                "display_name": item.get("display_name", ""),
                "evidence_type": item.get("evidence_type", ""),
                "outcome": item.get("outcome", ""),
                "pump_role": item.get("pump_role", ""),
                "direction": item.get("direction", ""),
                "completed_at": item.get("completed_at", ""),
                "operator": record.get("operator", ""),
                "note": item.get("note", ""),
                "data_json": json.dumps(item, ensure_ascii=False, sort_keys=True),
            }
        )
    for item in record.get("measurement_results", []):
        writer.writerow(
            {
                "record_type": "measurement",
                "validation_id": record.get("validation_id", ""),
                "test_id": "",
                "display_name": f"{item.get('pump_role', '')} flow measurement",
                "evidence_type": "MEASURED RESULT",
                "outcome": "RECORDED",
                "pump_role": item.get("pump_role", ""),
                "direction": item.get("direction", ""),
                "completed_at": item.get("timestamp", ""),
                "operator": item.get("operator", record.get("operator", "")),
                "note": item.get("note", ""),
                "data_json": json.dumps(item, ensure_ascii=False, sort_keys=True),
            }
        )
    return output.getvalue()


def _public_status(status: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in status.items() if key != "record"}


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    _atomic_text(path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _default_syringe(data: dict[str, Any]) -> str:
    profiles = data.get("profiles", {})
    if profiles:
        return str(next(iter(profiles.values())).get("syringe", ""))
    syringes = data.get("syringes", {})
    return str(next(iter(syringes), ""))


def _filename_stamp(value: str) -> str:
    return "".join(character for character in value if character.isdigit())[:14] or "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
