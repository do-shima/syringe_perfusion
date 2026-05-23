from __future__ import annotations

import copy
import time
from typing import Any

from .recipe_model import Recipe, block_id, recipe_from_blocks


class RecipeRecorder:
    def __init__(self) -> None:
        self._recording = False
        self._started = 0.0
        self._events: list[tuple[float, dict[str, Any]]] = []

    def start_recording(self) -> None:
        self._recording = True
        self._started = time.monotonic()
        self._events = []

    def record_event(self, block: dict[str, Any]) -> None:
        if not self._recording:
            raise RuntimeError("recording has not started")
        elapsed = time.monotonic() - self._started
        self._events.append((elapsed, copy.deepcopy(block)))

    def stop_recording(
        self,
        *,
        recipe_id: str = "recorded_recipe",
        display_name: str = "Recorded recipe",
        description: str = "",
    ) -> Recipe:
        if not self._recording:
            raise RuntimeError("recording has not started")
        self._recording = False
        return self.recipe_from_events(recipe_id=recipe_id, display_name=display_name, description=description)

    def recipe_from_events(
        self,
        *,
        recipe_id: str = "recorded_recipe",
        display_name: str = "Recorded recipe",
        description: str = "",
    ) -> Recipe:
        blocks: list[dict[str, Any]] = []
        previous = 0.0
        for elapsed, block in self._events:
            wait_s = round(max(0.0, elapsed - previous), 3)
            if wait_s > 0 and blocks:
                blocks.append({"id": block_id(blocks), "type": "wait", "duration_s": wait_s})
            copied = copy.deepcopy(block)
            if not copied.get("id"):
                copied["id"] = block_id(blocks)
            blocks.append(copied)
            previous = elapsed
        return recipe_from_blocks(
            recipe_id=recipe_id,
            display_name=display_name,
            description=description,
            blocks=blocks,
        )

    @staticmethod
    def recipe_from_timed_events(
        events: list[tuple[float, dict[str, Any]]],
        *,
        recipe_id: str = "recorded_recipe",
        display_name: str = "Recorded recipe",
        description: str = "",
    ) -> Recipe:
        recorder = RecipeRecorder()
        recorder._events = [(float(t), copy.deepcopy(block)) for t, block in events]
        return recorder.recipe_from_events(
            recipe_id=recipe_id,
            display_name=display_name,
            description=description,
        )
