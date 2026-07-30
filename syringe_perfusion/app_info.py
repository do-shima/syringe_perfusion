from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


APP_NAME = "A4 Syringe Pump Control"
APP_SHORT_NAME = "A4 Pump"
APPLICATION_ID = "A4PumpControl"
PACKAGE_NAME = "syringe-perfusion"
SOURCE_REPOSITORY = "do-shima/syringe_perfusion"
CONTROL_COMPATIBILITY_VERSION = 1
BUILD_INFO_SCHEMA_VERSION = 1
UNSIGNED_STATUS = "unsigned"


def package_version() -> str:
    """Return installed metadata, falling back to the source pyproject version."""
    try:
        return importlib.metadata.version(PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        embedded = load_embedded_build_info()
        return (
            str(embedded.get("package_version"))
            if embedded and embedded.get("package_version")
            else _source_package_version()
        )


def human_version(value: str | None = None) -> str:
    package = value or package_version()
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(?:b(\d+))?", package)
    if match and match.group(2):
        return f"{match.group(1)}-beta.{match.group(2)}"
    return package


def future_tag_name() -> str:
    return f"v{human_version()}"


def _source_package_version() -> str:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
        project = re.search(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", text)
        version = re.search(r'(?m)^version\s*=\s*"([^"]+)"', project.group(1) if project else "")
        if version:
            return version.group(1)
    except OSError:
        pass
    return "0+unknown"


def build_identity_fingerprint(info: dict[str, Any]) -> str:
    excluded = {"build_identity_fingerprint", "artifact_sha256"}
    payload = {key: value for key, value in info.items() if key not in excluded}
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _embedded_candidates() -> Iterable[Path]:
    explicit = os.environ.get("A4PUMP_BUILD_INFO", "").strip()
    if explicit:
        yield Path(explicit)
    bundle = getattr(sys, "_MEIPASS", "")
    if bundle:
        yield Path(bundle) / "build_info.json"
    executable = Path(sys.executable).resolve()
    yield executable.parent / "_internal" / "build_info.json"
    if executable.parent.name.casefold() == "a4ctl":
        yield executable.parent.parent / "_internal" / "build_info.json"


def load_embedded_build_info(paths: Iterable[str | Path] | None = None) -> dict[str, Any] | None:
    candidates = [Path(item) for item in paths] if paths is not None else list(_embedded_candidates())
    for path in candidates:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or int(value.get("schema_version", 0)) != BUILD_INFO_SCHEMA_VERSION:
                continue
            if not value.get("package_version") or not value.get("human_version"):
                continue
            result = dict(value)
            result.setdefault("build_info_path", str(path))
            result.setdefault("build_identity_fingerprint", build_identity_fingerprint(result))
            return result
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return None


def _git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        encoding="utf-8",
        errors="replace",
        stderr=subprocess.DEVNULL,
        timeout=3,
    ).strip()


def source_build_info(*, build_type: str = "source") -> dict[str, Any]:
    commit = os.environ.get("A4PUMP_BUILD_COMMIT", "").strip()
    dirty_env = os.environ.get("A4PUMP_BUILD_DIRTY", "").strip().casefold()
    dirty: bool | None = dirty_env in {"1", "true", "yes"} if dirty_env else None
    if not getattr(sys, "frozen", False):
        try:
            commit = commit or _git_output("rev-parse", "HEAD")
            if dirty is None:
                dirty = bool(_git_output("status", "--porcelain", "--untracked-files=no"))
        except Exception:
            pass
    try:
        pyinstaller_version = importlib.metadata.version("pyinstaller")
    except importlib.metadata.PackageNotFoundError:
        pyinstaller_version = ""
    package = package_version()
    info: dict[str, Any] = {
        "schema_version": BUILD_INFO_SCHEMA_VERSION,
        "application_name": APPLICATION_ID,
        "human_version": human_version(package),
        "package_version": package,
        "git_commit": commit,
        "git_commit_short": commit[:7],
        "git_dirty": dirty,
        "build_timestamp_utc": os.environ.get("A4PUMP_BUILD_TIMESTAMP_UTC", ""),
        "build_host_platform": platform.system(),
        "python_version": platform.python_version(),
        "pyinstaller_version": pyinstaller_version,
        "architecture": platform.machine(),
        "build_type": build_type,
        "source_repository": SOURCE_REPOSITORY,
        "control_compatibility_version": CONTROL_COMPATIBILITY_VERSION,
        "code_signing": UNSIGNED_STATUS,
        "artifact_sha256": "",
    }
    info["build_identity_fingerprint"] = build_identity_fingerprint(info)
    return info


@lru_cache(maxsize=1)
def get_build_info() -> dict[str, Any]:
    embedded = load_embedded_build_info()
    return embedded or source_build_info()


def create_build_info(*, build_type: str, require_clean: bool) -> dict[str, Any]:
    info = source_build_info(build_type=build_type)
    if not info.get("git_commit"):
        raise RuntimeError("Git commit could not be resolved")
    if require_clean and info.get("git_dirty") is not False:
        raise RuntimeError("release build requires a clean tracked source tree")
    info["build_timestamp_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    info["build_identity_fingerprint"] = build_identity_fingerprint(info)
    return info


def write_build_info(path: str | Path, *, build_type: str, require_clean: bool) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    info = create_build_info(build_type=build_type, require_clean=require_clean)
    temporary = destination.with_name(destination.name + f".{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(info, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def format_build_identity(info: dict[str, Any] | None = None) -> str:
    value = info or get_build_info()
    cleanliness = (
        "dirty development build"
        if value.get("git_dirty") is True
        else "clean release build"
        if value.get("git_dirty") is False and value.get("build_type") == "release-candidate"
        else "clean build"
        if value.get("git_dirty") is False
        else "cleanliness unknown"
    )
    checksum = value.get("artifact_sha256") or value.get("build_identity_fingerprint") or "unavailable"
    checksum_label = "artifact SHA-256" if value.get("artifact_sha256") else "build fingerprint"
    return "\n".join(
        (
            f"{APPLICATION_ID} {value.get('human_version', human_version())}",
            f"commit {value.get('git_commit_short') or 'unknown'}",
            cleanliness,
            f"control compatibility {value.get('control_compatibility_version', CONTROL_COMPATIBILITY_VERSION)}",
            f"{checksum_label} {checksum}",
        )
    )


APP_VERSION = human_version()
