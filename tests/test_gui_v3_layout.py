from syringe_perfusion.gui import A4PumpApp
from syringe_perfusion.ui_theme import COLORS


def make_app() -> A4PumpApp:
    app = A4PumpApp()
    app.withdraw()
    return app


def test_v3_theme_constants_exist() -> None:
    assert COLORS["background"] == "#F7F8FA"
    assert COLORS["accent"] == "#2563EB"
    assert COLORS["danger"] == "#DC2626"


def test_left_navigation_switches_pages() -> None:
    app = make_app()
    try:
        assert set(app.nav_buttons) >= {"dashboard", "pumps", "run", "profiles", "calculator", "recipes"}
        app.select_page("profiles")
        assert app.page_title_var.get() == "Profiles"
        app.select_page("recipes")
        assert app.page_title_var.get() == "Recipes"
    finally:
        app.destroy()


def test_pump_page_has_pump_cards() -> None:
    app = make_app()
    try:
        assert hasattr(app, "out_card")
        assert hasattr(app, "in_port_combo")
        assert hasattr(app, "out_port_combo")
        assert str(app.out_port_combo.cget("state")) == "disabled"
    finally:
        app.destroy()


def test_recipe_builder_has_three_panes_and_toolbar() -> None:
    app = make_app()
    try:
        recipe_tab = app.recipe_tab
        assert hasattr(recipe_tab, "library_frame")
        assert hasattr(recipe_tab, "timeline")
        assert hasattr(recipe_tab, "prop_pump_combo")
        assert recipe_tab.recipe_status_var.get().startswith("1 blocks")
    finally:
        app.destroy()
