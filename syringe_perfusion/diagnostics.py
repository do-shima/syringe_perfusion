from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .app_info import format_build_identity, get_build_info
from .config import (
    CONFIG_FILES,
    ConfigResolution,
    app_base_dir,
    load_json,
    resolve_config,
)
from .perfusion_state import read_pending, read_state, runtime_paths
from .port_scan import scan_serial_ports
from .preflight import assess_preflight
from .run_history import recent_runs
from .validation_store import ValidationStore


DIAGNOSTICS_SCHEMA_VERSION = 1
SECRET_KEYS = {"password", "passwd", "secret", "token", "api_key", "access_key"}
PERSONAL_PATH_PATTERNS = (
    re.compile(r"(?i)[A-Z]:\\Users\\[^\\\r\n]+"),
    re.compile(r"(?i)/home/[^/\r\n]+"),
    re.compile(r"(?i)/Users/[^/\r\n]+"),
)


def sanitize_text(value: str) -> str:
    result = value
    home = str(Path.home())
    source = str(Path(__file__).resolve().parents[1])
    for raw, replacement in ((source, "<SOURCE_ROOT>"), (home, "<USER_HOME>")):
        if raw:
            result = result.replace(raw, replacement)
            result = result.replace(raw.replace("\\", "/"), replacement)
    for pattern in PERSONAL_PATH_PATTERNS:
        result = pattern.sub("<USER_HOME>", result)
    return result


def sanitize(value: Any, *, key: str = "") -> Any:
    if key.casefold() in SECRET_KEYS or any(word in key.casefold() for word in ("password", "secret", "token")):
        return "<REDACTED>"
    if isinstance(value, dict):
        return {str(item_key): sanitize(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [sanitize(item, key=key) for item in value]
    if isinstance(value, Path):
        return sanitize_text(str(value))
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def wrapper_checks(root: str | Path | None = None) -> dict[str, Any]:
    base = Path(root).resolve() if root is not None else app_base_dir()
    wrapper_root = base / "nis_cmd"
    results: list[dict[str, Any]] = []
    for path in sorted(wrapper_root.glob("*.cmd"), key=lambda item: item.name.casefold()):
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        results.append(
            {
                "name": path.name,
                "crlf": b"\n" not in raw.replace(b"\r\n", b""),
                "one_command_per_line": "^" not in text,
                "uses_root": "%ROOT%" in text,
                "uses_config_dir": "--config-dir" in text,
                "hard_coded_numeric_com": bool(re.search(r"(?i)\bCOM\d+\b", text)),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return {
        "wrapper_root": sanitize_text(str(wrapper_root)),
        "count": len(results),
        "checks": results,
        "passed": bool(results)
        and all(
            item["crlf"]
            and item["one_command_per_line"]
            and not item["hard_coded_numeric_com"]
            for item in results
        ),
    }


def diagnostics_summary(
    config: str | Path | ConfigResolution | None = None,
    *,
    port_provider: Callable[[], Iterable[Any]] | None = None,
) -> dict[str, Any]:
    resolution = config if isinstance(config, ConfigResolution) else resolve_config(config)
    try:
        ports = scan_serial_ports(port_provider)
        port_error = ""
    except Exception as exc:
        ports = []
        port_error = str(exc)
    preflight = assess_preflight(resolution, detected_ports=ports)
    try:
        validation = ValidationStore(resolution).status(detected_ports=ports)
    except Exception as exc:
        validation = {
            "status": "UNAVAILABLE",
            "current": False,
            "commissioned": False,
            "stale_reasons": [str(exc)],
            "record": None,
        }
    public_validation = {key: value for key, value in validation.items() if key != "record"}
    result = {
        "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "build": get_build_info(),
        "config_resolution": resolution.to_dict(),
        "preflight": preflight,
        "validation_status": public_validation,
        "runtime_state": read_state(resolution.active_config_dir),
        "pending_state": read_pending(resolution.active_config_dir),
        "recent_runs": recent_runs(resolution, limit=20),
        "detected_ports": ports,
        "port_enumeration_error": port_error,
        "wrappers": wrapper_checks(),
    }
    return sanitize(result)


def format_diagnostics_summary(summary: dict[str, Any]) -> str:
    preflight = summary.get("preflight") or {}
    validation = summary.get("validation_status") or {}
    runtime = summary.get("runtime_state") or {}
    ports = summary.get("detected_ports") or []
    wrappers = summary.get("wrappers") or {}
    return "\n".join(
        (
            format_build_identity(summary.get("build") or {}),
            "",
            f"Active Config: {(summary.get('config_resolution') or {}).get('active_config_dir', '')}",
            f"Preflight: {preflight.get('summary', 'UNKNOWN')} "
            f"({(preflight.get('counts') or {}).get('BLOCK', 0)} BLOCK, "
            f"{(preflight.get('counts') or {}).get('WARN', 0)} WARN)",
            f"Commissioning: {validation.get('status', 'UNKNOWN')}",
            f"Runtime state: {runtime.get('state', 'NONE')}",
            f"Detected ports: {len(ports)} (enumeration only; ports were not opened)",
            f"NIS wrapper checks: {'PASS' if wrappers.get('passed') else 'CHECK REQUIRED'}",
        )
    )


def export_diagnostics(
    config: str | Path | ConfigResolution | None,
    output: str | Path,
    *,
    port_provider: Callable[[], Iterable[Any]] | None = None,
) -> Path:
    resolution = config if isinstance(config, ConfigResolution) else resolve_config(config)
    destination = Path(output).expanduser().resolve()
    if destination.suffix.casefold() != ".zip":
        destination = destination.with_suffix(".zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    summary = diagnostics_summary(resolution, port_provider=port_provider)
    with tempfile.TemporaryDirectory(prefix="a4-diagnostics-") as temporary_name:
        root = Path(temporary_name)
        _write_json(root / "diagnostics-summary.json", summary)
        _write_text(root / "diagnostics-summary.txt", format_diagnostics_summary(summary) + "\n")
        _write_json(root / "build_info.json", summary["build"])
        _write_json(root / "config-resolution.json", summary["config_resolution"])
        _write_json(root / "preflight.json", summary["preflight"])
        _write_json(root / "validation-status.json", summary["validation_status"])
        _write_json(root / "runtime-state.json", summary["runtime_state"] or {})
        _write_json(root / "pending-state.json", summary["pending_state"] or {})
        _write_json(root / "recent-runs.json", summary["recent_runs"])
        _write_json(root / "detected-ports.json", summary["detected_ports"])
        _write_json(root / "wrapper-checks.json", summary["wrappers"])
        config_root = root / "config"
        for filename in CONFIG_FILES.values():
            source = resolution.active_config_dir / filename
            if source.exists():
                try:
                    _write_json(config_root / filename, sanitize(load_json(source)))
                except Exception:
                    _write_text(
                        config_root / filename,
                        sanitize_text(source.read_text(encoding="utf-8", errors="replace")),
                    )
        try:
            ValidationStore(resolution).export("markdown", root / "validation-report.md")
        except Exception as exc:
            _write_text(
                root / "validation-report.md",
                "# Validation report unavailable\n\n"
                f"Sanitized error: {sanitize_text(str(exc))}\n",
            )
        report = root / "validation-report.md"
        _write_text(report, sanitize_text(report.read_text(encoding="utf-8")))
        _copy_recent_logs(resolution, root / "logs")
        manifest = _find_build_manifest()
        if manifest:
            _write_text(root / "build-manifest.json", sanitize_text(manifest.read_text(encoding="utf-8")))
        fd, temporary_zip_name = tempfile.mkstemp(
            prefix=destination.name + ".",
            suffix=".tmp",
            dir=destination.parent,
        )
        os.close(fd)
        temporary_zip = Path(temporary_zip_name)
        try:
            with zipfile.ZipFile(temporary_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
                    if path.is_file():
                        archive.write(path, path.relative_to(root).as_posix())
            os.replace(temporary_zip, destination)
        finally:
            temporary_zip.unlink(missing_ok=True)
    return destination


def _copy_recent_logs(resolution: ConfigResolution, output: Path) -> None:
    candidates = [
        runtime_paths(resolution.active_config_dir).log,
        *sorted((resolution.active_config_dir / "logs").glob("*.csv")),
        *sorted((resolution.active_config_dir.parent / "logs").glob("*.csv")),
    ]
    seen: set[Path] = set()
    for source in candidates[-10:]:
        resolved = source.resolve()
        if resolved in seen or not source.is_file():
            continue
        seen.add(resolved)
        try:
            lines = source.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]
            _write_text(output / source.name, sanitize_text("\n".join(lines) + "\n"))
        except OSError:
            continue


def _find_build_manifest() -> Path | None:
    executable = Path(os.path.abspath(os.path.dirname(os.path.realpath(os.sys.executable))))
    candidates = (
        executable / "build-manifest.json",
        executable.parent / "build-manifest.json",
        app_base_dir() / "build-manifest.json",
        app_base_dir().parent / "build-manifest.json",
    )
    return next((path for path in candidates if path.is_file()), None)


def _write_json(path: Path, value: Any) -> None:
    _write_text(path, json.dumps(sanitize(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(value)
