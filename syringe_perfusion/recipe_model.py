from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .blocks import BLOCK_TYPES, PUMP_ACTIONS, SCHEMA_VERSION


@dataclass
class Block:
    id: str
    type: str
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {"id": self.id, "type": self.type}
        data.update(self.fields)
        return data


@dataclass
class Recipe:
    schema_version: int
    recipe_id: str
    display_name: str
    description: str = ""
    blocks: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Recipe":
        return cls(
            schema_version=int(data.get("schema_version", 0)),
            recipe_id=str(data.get("recipe_id", "")),
            display_name=str(data.get("display_name", "")),
            description=str(data.get("description", "")),
            blocks=copy.deepcopy(data.get("blocks", [])),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": self.schema_version,
            "recipe_id": self.recipe_id,
            "display_name": self.display_name,
            "description": self.description,
            "blocks": copy.deepcopy(self.blocks),
        }
        if self.created_at:
            data["created_at"] = self.created_at
        if self.updated_at:
            data["updated_at"] = self.updated_at
        return data


def block_id(existing_blocks: list[dict[str, Any]] | None = None) -> str:
    existing = existing_blocks or []
    used = {str(block.get("id", "")) for block in existing}
    index = 1
    while True:
        candidate = f"b{index:03d}"
        if candidate not in used:
            return candidate
        index += 1


def ensure_block_id(block: dict[str, Any], existing_blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    copied = copy.deepcopy(block)
    if not copied.get("id"):
        copied["id"] = block_id(existing_blocks)
    return copied


def validate_recipe(recipe: Recipe | dict[str, Any], config_data: dict[str, Any] | None = None) -> None:
    model = recipe if isinstance(recipe, Recipe) else Recipe.from_dict(recipe)
    if model.schema_version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version: {model.schema_version}")
    if not model.recipe_id:
        raise ValueError("recipe_id is required")
    if not model.display_name:
        raise ValueError("display_name is required")
    if not isinstance(model.blocks, list):
        raise ValueError("blocks must be a list")

    seen_ids: set[str] = set()
    for index, block in enumerate(model.blocks):
        validate_block(block, index, seen_ids, config_data)


def validate_block(
    block: dict[str, Any],
    index: int,
    seen_ids: set[str],
    config_data: dict[str, Any] | None = None,
) -> None:
    block_id_value = str(block.get("id", ""))
    if not block_id_value:
        raise ValueError(f"block {index}: id is required")
    if block_id_value in seen_ids:
        raise ValueError(f"block {index}: duplicate id {block_id_value}")
    seen_ids.add(block_id_value)

    block_type = block.get("type")
    if block_type not in BLOCK_TYPES:
        raise ValueError(f"block {index}: invalid block type {block_type!r}")

    if block_type in {"pump_start", "pump_stop"}:
        pump = block.get("pump")
        if not pump:
            raise ValueError(f"block {index}: pump is required")
        if config_data is not None and pump not in config_data["pumps"]:
            raise ValueError(f"block {index}: unknown pump {pump}")
        action = block.get("action")
        if action not in PUMP_ACTIONS[block_type]:
            raise ValueError(f"block {index}: invalid action {action!r} for {block_type}")
        profile = block.get("profile", "")
        if block_type == "pump_start" and profile and config_data is not None and profile not in config_data["profiles"]:
            raise ValueError(f"block {index}: unknown profile {profile}")

    if block_type == "wait":
        duration = float(block.get("duration_s", 0))
        if duration < 0:
            raise ValueError(f"block {index}: duration_s must be zero or positive")

    if block_type in {"log_marker", "prompt_check"}:
        if str(block.get("message", "")).strip() == "":
            raise ValueError(f"block {index}: message is required")


def recipe_from_blocks(
    *,
    recipe_id: str,
    display_name: str,
    blocks: list[dict[str, Any]],
    description: str = "",
) -> Recipe:
    with_ids: list[dict[str, Any]] = []
    for block in blocks:
        with_ids.append(ensure_block_id(block, with_ids))
    recipe = Recipe(
        schema_version=SCHEMA_VERSION,
        recipe_id=recipe_id,
        display_name=display_name,
        description=description,
        blocks=with_ids,
    )
    validate_recipe(recipe)
    return recipe
