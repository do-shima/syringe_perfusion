from pathlib import Path

from syringe_perfusion import app_info
from syringe_perfusion.assets import asset_path, find_asset, set_window_icon
from gui_app_helper import make_app


def test_asset_path_returns_path() -> None:
    assert isinstance(asset_path("icons", "missing.png"), Path)


def test_find_asset_missing_returns_none() -> None:
    assert find_asset("icons/definitely_missing_icon.png") is None


def test_set_window_icon_missing_returns_false() -> None:
    assert set_window_icon(object()) is False  # type: ignore[arg-type]


def test_app_version_is_string() -> None:
    assert isinstance(app_info.APP_VERSION, str)
    assert app_info.APP_VERSION


def test_sidebar_version_matches_app_info() -> None:
    app = make_app()
    try:
        assert app.sidebar_version_label.cget("text") == app_info.APP_VERSION
    finally:
        app.destroy()
