from syringe_perfusion.app_info import APP_VERSION
from syringe_perfusion.ui_theme import COLORS, create_card
from gui_app_helper import make_app


def test_v3_theme_constants_exist() -> None:
    assert COLORS["background"] == "#F7F8FA"
    assert COLORS["accent"] == "#2563EB"
    assert COLORS["danger"] == "#DC2626"


def test_left_navigation_switches_pages() -> None:
    app = make_app()
    try:
        card = create_card(app.pages["dashboard"], "Test card")
        assert card.winfo_class() == "TFrame"
        assert set(app.nav_buttons) >= {"dashboard", "pumps", "run", "profiles", "calculator", "recipes"}
        assert all("[" not in button.cget("text") for button in app.nav_buttons.values())
        assert app.sidebar_version_label.cget("text") == APP_VERSION
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
        assert hasattr(recipe_tab, "steps_tree")
        assert recipe_tab.steps_tree.get_children()
        assert hasattr(recipe_tab, "inspector_scroll")
        assert hasattr(recipe_tab, "prop_pump_combo")
        assert recipe_tab.recipe_status_var.get().startswith("1 step")
    finally:
        app.destroy()


def test_recipe_builder_tree_operations_work() -> None:
    app = make_app()
    try:
        recipe_tab = app.recipe_tab
        recipe_tab.add_block("wait")
        assert len(recipe_tab.blocks) == 2
        assert len(recipe_tab.steps_tree.get_children()) == 2
        recipe_tab.select_step(1)
        recipe_tab.move_up()
        assert recipe_tab.selected_index() == 0
        recipe_tab.duplicate_selected()
        assert len(recipe_tab.blocks) == 3
        recipe_tab.delete_selected()
        assert len(recipe_tab.blocks) == 2
    finally:
        app.destroy()
