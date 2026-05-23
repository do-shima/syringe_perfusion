from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import app_base_dir
from .recipe_model import Recipe, validate_recipe


def default_recipe_dir() -> Path:
    candidates = [Path.cwd() / "recipes", app_base_dir() / "recipes"]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return (app_base_dir() / "recipes").resolve()


def load_recipe(path: str | Path) -> Recipe:
    recipe_path = Path(path)
    with recipe_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    recipe = Recipe.from_dict(data)
    validate_recipe(recipe)
    return recipe


def save_recipe(recipe: Recipe, path: str | Path) -> Path:
    validate_recipe(recipe)
    recipe.updated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    recipe_path = Path(path)
    recipe_path.parent.mkdir(parents=True, exist_ok=True)
    with recipe_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(recipe.to_dict(), f, indent=2, ensure_ascii=False)
        f.write("\n")
    return recipe_path


def list_recipes(recipe_dir: str | Path | None = None) -> list[Path]:
    root = Path(recipe_dir).resolve() if recipe_dir is not None else default_recipe_dir()
    if not root.exists():
        return []
    return sorted(path for path in root.glob("*.json") if path.is_file())
