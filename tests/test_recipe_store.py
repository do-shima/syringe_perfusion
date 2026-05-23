from syringe_perfusion.recipe_model import Recipe
from syringe_perfusion.recipe_store import list_recipes, load_recipe, save_recipe


def test_load_sample_recipes() -> None:
    recipes = list_recipes("recipes")
    names = {path.name for path in recipes}
    assert {"in_fast30.json", "pushpull_fast30.json"} <= names
    recipe = load_recipe("recipes/in_fast30.json")
    assert recipe.recipe_id == "in_fast30_v1"


def test_save_recipe_adds_updated_at(tmp_path) -> None:
    recipe = Recipe(
        schema_version=2,
        recipe_id="tmp_recipe",
        display_name="Temporary recipe",
        blocks=[{"id": "b001", "type": "log_marker", "message": "hello"}],
    )
    path = tmp_path / "tmp_recipe.json"
    save_recipe(recipe, path)
    loaded = load_recipe(path)
    assert loaded.updated_at
