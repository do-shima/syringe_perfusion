from syringe_perfusion.cli import main
from syringe_perfusion.config import load_config
from syringe_perfusion.recipe_engine import RecipeEngine
from syringe_perfusion.recipe_store import load_recipe


def test_recipe_engine_dry_run_returns_all_block_events() -> None:
    data = load_config()
    data["pumps"]["OUT"]["enabled"] = True
    data["pumps"]["OUT"]["port"] = "COM6"
    recipe = load_recipe("recipes/pushpull_fast30.json")
    events = RecipeEngine(data).execute(recipe, dry_run=True, context={"trigger_source": "pytest"})
    assert len(events) == len(recipe.blocks)
    assert [event["block_id"] for event in events] == ["b001", "b002", "b003", "b004", "b005"]


def test_run_recipe_dry_run_cli_exits() -> None:
    code = main(["run-recipe", "--recipe", "recipes/in_fast30.json", "--dry-run", "--assume-yes"])
    assert code == 0
