import pytest

from syringe_perfusion.recipe_model import Recipe, validate_recipe
from syringe_perfusion.recipe_store import load_recipe


def test_sample_recipe_validates() -> None:
    recipe = load_recipe("recipes/pushpull_fast30.json")
    validate_recipe(recipe)
    assert recipe.schema_version == 2
    assert recipe.blocks[0]["type"] == "pump_start"


def test_invalid_block_type_errors() -> None:
    recipe = Recipe(
        schema_version=2,
        recipe_id="bad",
        display_name="Bad recipe",
        blocks=[{"id": "b001", "type": "not_a_block"}],
    )
    with pytest.raises(ValueError, match="invalid block type"):
        validate_recipe(recipe)
