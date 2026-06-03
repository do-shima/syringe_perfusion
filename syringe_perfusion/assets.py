from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

from .config import app_base_dir


def asset_base_dir() -> Path:
    for candidate in _asset_candidates():
        if candidate.exists():
            return candidate
    return _asset_candidates()[0]


def asset_path(*parts: str) -> Path:
    return asset_base_dir().joinpath(*parts)


def find_asset(*relative_paths: str) -> Path | None:
    for base in _asset_candidates():
        for relative in relative_paths:
            path = base / relative
            if path.exists():
                return path
    return None


def load_tk_image(path: Path) -> tk.PhotoImage | None:
    try:
        if not path.exists():
            return None
        return tk.PhotoImage(file=str(path))
    except Exception:
        return None


def set_window_icon(root: tk.Tk | tk.Toplevel) -> bool:
    icon = find_asset(
        "icons/app_icon_256.png",
        "icons/app_icon_128.png",
        "icons/app_icon.png",
    )
    if icon is None:
        return False
    image = load_tk_image(icon)
    if image is None:
        return False
    try:
        root.iconphoto(True, image)
    except Exception:
        return False
    setattr(root, "_app_icon_image", image)
    return True


def _asset_candidates() -> list[Path]:
    candidates = [
        Path.cwd() / "assets",
        app_base_dir() / "assets",
    ]
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "assets")  # type: ignore[attr-defined]
    return candidates
