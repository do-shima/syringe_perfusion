from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


CONFIG_FILES = {
    "pumps": "pumps.json",
    "syringes": "syringes.json",
    "profiles": "profiles.json",
    "recipes": "recipes.json",
}


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def config_dir(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit).resolve()

    candidates = [
        Path.cwd() / "config",
        app_base_dir() / "config",
    ]
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "config")  # type: ignore[attr-defined]

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return (app_base_dir() / "config").resolve()


def logs_dir(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        path = Path(explicit).resolve()
    else:
        path = app_base_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    root = config_dir(config_path)
    data: dict[str, Any] = {}
    for key, filename in CONFIG_FILES.items():
        path = root / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing config file: {path}")
        data[key] = load_json(path)[key]
    return data


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
