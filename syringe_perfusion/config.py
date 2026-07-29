from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping


CONFIG_FILES = {
    "pumps": "pumps.json",
    "syringes": "syringes.json",
    "profiles": "profiles.json",
    "recipes": "recipes.json",
}
REQUIRED_CONFIG_FILES = tuple(CONFIG_FILES.values())
CONFIG_ENV_VAR = "A4PUMP_CONFIG_DIR"
APP_SETTINGS_DIRNAME = "A4PumpControl"

ConfigSource = Literal[
    "explicit",
    "environment",
    "persisted_user_choice",
    "exe_adjacent",
    "localappdata",
    "source_repository",
    "packaged_default",
]


@dataclass(frozen=True)
class ConfigResolution:
    active_config_dir: Path
    active_pumps_json: Path
    source: ConfigSource
    writable: bool
    packaged_default_dir: Path | None
    required_files_present: bool
    missing_files: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["active_config_dir"] = str(self.active_config_dir)
        data["active_pumps_json"] = str(self.active_pumps_json)
        data["packaged_default_dir"] = (
            str(self.packaged_default_dir) if self.packaged_default_dir is not None else None
        )
        return data


def app_base_dir() -> Path:
    """Return the install root, not PyInstaller's private _internal directory."""
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        # The supported kit layout places the CLI in <root>\a4ctl\a4ctl.exe.
        if executable_dir.name.casefold() == "a4ctl" and Path(sys.executable).stem.casefold() == "a4ctl":
            return executable_dir.parent
        return executable_dir
    return source_repository_dir()


def source_repository_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def local_appdata_dir(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    value = env.get("LOCALAPPDATA")
    if value:
        return Path(value).expanduser().resolve()
    if os.name == "nt":
        return (Path.home() / "AppData" / "Local").resolve()
    return (Path.home() / ".local" / "share").resolve()


def user_settings_path(environ: Mapping[str, str] | None = None) -> Path:
    return local_appdata_dir(environ) / APP_SETTINGS_DIRNAME / "settings.json"


def _read_persisted_config_dir(settings_file: Path) -> Path | None:
    try:
        data = load_json(settings_file)
        value = data.get("active_config_dir")
        if not isinstance(value, str) or not value.strip():
            return None
        return Path(value).expanduser().resolve()
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return None


def persist_active_config_dir(
    config_path: str | Path,
    *,
    settings_file: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    target = Path(settings_file) if settings_file is not None else user_settings_path(environ)
    target = target.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(target, {"active_config_dir": str(Path(config_path).expanduser().resolve())}, backup=False)
    return target


def packaged_default_dir() -> Path | None:
    """Find bundled defaults. They are copy sources and are never an Active Config."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is None:
        return None
    base = Path(meipass).resolve()
    for name in ("default_config", "config"):
        candidate = base / name
        if candidate.is_dir():
            return candidate
    return None


def _missing_files(path: Path) -> list[str]:
    return [name for name in REQUIRED_CONFIG_FILES if not (path / name).is_file()]


def _is_writable_config_dir(path: Path) -> bool:
    if path.exists():
        if not path.is_dir() or not os.access(path, os.W_OK):
            return False
        pumps = path / "pumps.json"
        return not pumps.exists() or os.access(pumps, os.W_OK)
    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    return parent.is_dir() and os.access(parent, os.W_OK)


def _copy_missing_defaults(destination: Path, defaults: Path | None) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if defaults is None:
        return
    for filename in REQUIRED_CONFIG_FILES:
        source = defaults / filename
        target = destination / filename
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)


def _resolution(path: Path, source: ConfigSource, defaults: Path | None) -> ConfigResolution:
    path = path.expanduser().resolve()
    missing = _missing_files(path)
    return ConfigResolution(
        active_config_dir=path,
        active_pumps_json=path / "pumps.json",
        source=source,
        writable=_is_writable_config_dir(path),
        packaged_default_dir=defaults,
        required_files_present=not missing,
        missing_files=missing,
    )


def resolve_config(
    explicit: str | Path | None = None,
    *,
    initialize_frozen: bool = True,
    environ: Mapping[str, str] | None = None,
    settings_file: str | Path | None = None,
) -> ConfigResolution:
    """Resolve one directory containing all four active JSON files.

    Order: explicit, A4PUMP_CONFIG_DIR, persisted GUI choice, executable-adjacent
    config, LocalAppData, source repository config. A packaged directory is only
    used to fill missing files in a newly created external Frozen config.
    """
    env = os.environ if environ is None else environ
    defaults = packaged_default_dir()

    if explicit is not None:
        return _resolution(Path(explicit), "explicit", defaults)

    env_value = env.get(CONFIG_ENV_VAR)
    if env_value and env_value.strip():
        return _resolution(Path(env_value), "environment", defaults)

    settings = Path(settings_file).expanduser().resolve() if settings_file else user_settings_path(env)
    persisted = _read_persisted_config_dir(settings)
    if persisted is not None:
        return _resolution(persisted, "persisted_user_choice", defaults)

    frozen = bool(getattr(sys, "frozen", False))
    install_config = app_base_dir() / "config"
    local_config = local_appdata_dir(env) / APP_SETTINGS_DIRNAME / "config"

    if frozen:
        existing = _resolution(install_config, "exe_adjacent", defaults)
        if existing.required_files_present:
            return existing
        if initialize_frozen and existing.writable:
            try:
                _copy_missing_defaults(install_config, defaults)
                initialized = _resolution(install_config, "exe_adjacent", defaults)
                if initialized.required_files_present:
                    return initialized
            except OSError:
                pass

        local = _resolution(local_config, "localappdata", defaults)
        if local.required_files_present:
            return local
        if initialize_frozen:
            _copy_missing_defaults(local_config, defaults)
        return _resolution(local_config, "localappdata", defaults)

    local = _resolution(local_config, "localappdata", defaults)
    if local.required_files_present:
        return local
    return _resolution(source_repository_dir() / "config", "source_repository", defaults)


def config_dir(explicit: str | Path | None = None) -> Path:
    """Backward-compatible path API backed by the shared resolver."""
    return resolve_config(explicit).active_config_dir


def logs_dir(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        path = Path(explicit).resolve()
    else:
        path = app_base_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def load_config(config_path: str | Path | ConfigResolution | None = None) -> dict[str, Any]:
    resolution = config_path if isinstance(config_path, ConfigResolution) else resolve_config(config_path)
    root = resolution.active_config_dir
    if not resolution.required_files_present:
        missing = ", ".join(resolution.missing_files)
        raise FileNotFoundError(f"Missing config file(s) in {root}: {missing}")
    data: dict[str, Any] = {}
    for key, filename in CONFIG_FILES.items():
        path = root / filename
        document = load_json(path)
        if key not in document:
            raise KeyError(f"Missing top-level key {key!r}: {path}")
        data[key] = document[key]
    return data


def validate_config_directory(config_path: str | Path) -> ConfigResolution:
    return _resolution(Path(config_path), "explicit", packaged_default_dir())


def validate_pump_settings(
    *,
    in_port: str,
    out_enabled: bool,
    out_port: str,
    baudrate: int | str,
    terminator: str,
    timeout: float | str,
) -> dict[str, Any]:
    clean_in = str(in_port).strip()
    clean_out = str(out_port).strip()
    if not clean_in:
        raise ValueError("IN port is required")
    if out_enabled and not clean_out:
        raise ValueError("OUT port is required when OUT is enabled")
    if out_enabled and clean_in.casefold() == clean_out.casefold():
        raise ValueError("IN and enabled OUT must use different COM ports")
    try:
        clean_baudrate = int(baudrate)
    except (TypeError, ValueError) as exc:
        raise ValueError("baudrate must be a positive integer") from exc
    if clean_baudrate <= 0:
        raise ValueError("baudrate must be a positive integer")
    try:
        clean_timeout = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout must be a positive number") from exc
    if clean_timeout <= 0:
        raise ValueError("timeout must be a positive number")
    # Validation accepts the JSON spellings; decoding prevents unsupported values.
    decode_terminator(terminator)
    return {
        "in_port": clean_in,
        "out_enabled": bool(out_enabled),
        "out_port": clean_out,
        "baudrate": clean_baudrate,
        "terminator": encode_terminator(decode_terminator(terminator)),
        "timeout": clean_timeout,
    }


def save_pump_settings(
    config_path: str | Path | ConfigResolution,
    *,
    in_port: str,
    out_enabled: bool,
    out_port: str,
    baudrate: int | str,
    terminator: str,
    timeout: float | str,
) -> Path:
    resolution = config_path if isinstance(config_path, ConfigResolution) else validate_config_directory(config_path)
    path = resolution.active_pumps_json
    if not resolution.writable:
        raise PermissionError(f"Active Config is read-only: {resolution.active_config_dir}")
    values = validate_pump_settings(
        in_port=in_port,
        out_enabled=out_enabled,
        out_port=out_port,
        baudrate=baudrate,
        terminator=terminator,
        timeout=timeout,
    )
    document = load_json(path)
    pumps = document.get("pumps")
    if not isinstance(pumps, dict) or not isinstance(pumps.get("IN"), dict):
        raise ValueError(f"pumps.json must contain a pumps.IN object: {path}")
    if not isinstance(pumps.get("OUT"), dict):
        raise ValueError(f"pumps.json must contain a pumps.OUT object: {path}")

    pumps["IN"].update(
        {
            "enabled": True,
            "port": values["in_port"],
            "baudrate": values["baudrate"],
            "terminator": values["terminator"],
            "timeout": values["timeout"],
        }
    )
    pumps["OUT"].update(
        {
            "enabled": values["out_enabled"],
            "port": values["out_port"],
            "baudrate": values["baudrate"],
            "terminator": values["terminator"],
            "timeout": values["timeout"],
        }
    )
    _atomic_write_json(path, document, backup=True)

    reloaded = load_json(path)
    saved = reloaded["pumps"]
    expected = {
        "IN": values["in_port"],
        "OUT": values["out_port"],
        "OUT enabled": values["out_enabled"],
    }
    actual = {
        "IN": saved["IN"]["port"],
        "OUT": saved["OUT"]["port"],
        "OUT enabled": saved["OUT"]["enabled"],
    }
    if actual != expected:
        raise OSError(f"pumps.json verification failed: expected {expected!r}, got {actual!r}")
    return path


def _atomic_write_json(path: Path, data: dict[str, Any], *, backup: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            raise


def get_pump_config(pump_key: str, config_data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = config_data or load_config()
    try:
        return data["pumps"][pump_key]
    except KeyError as exc:
        raise KeyError(f"Unknown pump: {pump_key}") from exc


def decode_terminator(value: str) -> str:
    allowed = {
        "": "",
        "\\r": "\r",
        "\\n": "\n",
        "\\r\\n": "\r\n",
        "\r": "\r",
        "\n": "\n",
        "\r\n": "\r\n",
    }
    if value not in allowed:
        raise ValueError(f"Unsupported terminator: {value!r}")
    return allowed[value]


def encode_terminator(value: str) -> str:
    reverse = {
        "": "",
        "\r": "\\r",
        "\n": "\\n",
        "\r\n": "\\r\\n",
    }
    if value not in reverse:
        raise ValueError(f"Unsupported terminator: {value!r}")
    return reverse[value]
