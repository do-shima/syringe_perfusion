from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from .a4 import pump_from_config
from .blocks import ACTION_TO_COMMAND_KEY
from .logger import log_command, write_log
from .profiles import calculate_profile
from .recipe_model import Recipe, validate_recipe


PromptCallback = Callable[[str], bool]


class RecipeEngine:
    def __init__(self, config_data: dict[str, Any]) -> None:
        self.config_data = config_data

    def execute(
        self,
        recipe: Recipe,
        dry_run: bool = False,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        validate_recipe(recipe, self.config_data)
        ctx = context or {}
        started = time.monotonic()
        events: list[dict[str, Any]] = []
        try:
            for index, block in enumerate(recipe.blocks):
                event = self._execute_block(recipe, block, index, started, dry_run, ctx)
                events.append(event)
        except Exception:
            if not dry_run:
                try:
                    self.stop_all(recipe, started, len(events), dry_run=False, context=ctx, note="exception safety stop")
                except Exception:
                    pass
            raise
        return events

    def stop_all(
        self,
        recipe: Recipe | None = None,
        started_monotonic: float | None = None,
        block_index: int = 0,
        dry_run: bool = False,
        context: dict[str, Any] | None = None,
        note: str = "Safety stop",
        source_block: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        ctx = context or {}
        start = started_monotonic if started_monotonic is not None else time.monotonic()
        events = []
        for pump_key in self.config_data["pumps"]:
            block = dict(source_block or {"id": "stop_all", "type": "stop_all"})
            block["pump"] = pump_key
            block["note"] = note
            events.append(self._send_pump_command(recipe, block, block_index, start, dry_run, ctx, pump_key, "stop"))
        return events

    def _execute_block(
        self,
        recipe: Recipe,
        block: dict[str, Any],
        index: int,
        started_monotonic: float,
        dry_run: bool,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        block_type = block["type"]
        if block_type == "pump_start":
            return self._send_pump_command(
                recipe, block, index, started_monotonic, dry_run, context, block["pump"], block["action"]
            )
        if block_type == "pump_stop":
            return self._send_pump_command(
                recipe, block, index, started_monotonic, dry_run, context, block["pump"], "stop"
            )
        if block_type == "stop_all":
            start = self._event_start(recipe, block, index, started_monotonic)
            results = self.stop_all(
                recipe,
                started_monotonic,
                index,
                dry_run,
                context,
                block.get("note", "Safety stop"),
                source_block=block,
            )
            end_time = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            event = self._base_event(recipe, block, index, started_monotonic)
            event.update({"started_at": start, "ended_at": end_time, "results": results})
            return event
        if block_type == "wait":
            start = self._event_start(recipe, block, index, started_monotonic)
            duration = float(block.get("duration_s", 0))
            if not dry_run and duration > 0:
                time.sleep(duration)
            return self._log_nonhardware_block(
                recipe,
                block,
                index,
                started_monotonic,
                context,
                start,
                "wait",
                note=f"wait {duration:.3f} s",
            )
        if block_type == "log_marker":
            start = self._event_start(recipe, block, index, started_monotonic)
            return self._log_nonhardware_block(
                recipe, block, index, started_monotonic, context, start, "log_marker", note=block.get("message", "")
            )
        if block_type == "prompt_check":
            start = self._event_start(recipe, block, index, started_monotonic)
            if not dry_run:
                self._confirm_prompt(block.get("message", ""), context)
            return self._log_nonhardware_block(
                recipe, block, index, started_monotonic, context, start, "prompt_check", note=block.get("message", "")
            )
        raise ValueError(f"Unsupported block type: {block_type}")

    def _send_pump_command(
        self,
        recipe: Recipe | None,
        block: dict[str, Any],
        index: int,
        started_monotonic: float,
        dry_run: bool,
        context: dict[str, Any],
        pump_key: str,
        action: str,
    ) -> dict[str, Any]:
        start = self._event_start(recipe, block, index, started_monotonic)
        command_key = ACTION_TO_COMMAND_KEY[action]
        pump = pump_from_config(pump_key, self.config_data["pumps"][pump_key], dry_run=dry_run)
        result = getattr(pump, command_key)()
        ended_at = self._now()
        profile_key = block.get("profile", "")
        calc = self._profile_info(profile_key)
        note = block.get("note", "")
        log_command(
            result=result,
            action=action,
            dish_id=context.get("dish_id", ""),
            condition=context.get("condition", ""),
            trigger_source=context.get("trigger_source", ""),
            profile=profile_key,
            syringe=calc.get("syringe", ""),
            speed_mm_min=calc.get("speed_mm_min"),
            duration_s=calc.get("duration_s"),
            target_volume_ul=calc.get("target_volume_ul"),
            estimated_volume_ul=calc.get("estimated_volume_ul"),
            note=note,
            recipe_id=recipe.recipe_id if recipe is not None else "",
            block_id=block.get("id", ""),
            block_type=block.get("type", ""),
            relative_time_s=self._relative(started_monotonic),
            block_index=index,
            started_at=start,
            ended_at=ended_at,
        )
        event = self._base_event(recipe, block, index, started_monotonic)
        event.update({"started_at": start, "ended_at": ended_at, "result": result})
        return event

    def _log_nonhardware_block(
        self,
        recipe: Recipe,
        block: dict[str, Any],
        index: int,
        started_monotonic: float,
        context: dict[str, Any],
        started_at: str,
        action: str,
        note: str,
    ) -> dict[str, Any]:
        ended_at = self._now()
        event = self._base_event(recipe, block, index, started_monotonic)
        event.update({"started_at": started_at, "ended_at": ended_at, "note": note})
        write_log(
            {
                "timestamp": started_at,
                "started_at": started_at,
                "ended_at": ended_at,
                "dish_id": context.get("dish_id", ""),
                "condition": context.get("condition", ""),
                "trigger_source": context.get("trigger_source", ""),
                "action": action,
                "note": note,
                "recipe_id": recipe.recipe_id,
                "block_id": block.get("id", ""),
                "block_type": block.get("type", ""),
                "relative_time_s": event["relative_time_s"],
                "block_index": index,
            }
        )
        return event

    def _profile_info(self, profile_key: str) -> dict[str, Any]:
        if not profile_key:
            return {}
        profile = self.config_data["profiles"][profile_key]
        syringe_key = profile["syringe"]
        calc = calculate_profile(profile, self.config_data["syringes"][syringe_key], syringe_key)
        return {
            "syringe": syringe_key,
            "speed_mm_min": calc.speed_mm_min,
            "duration_s": calc.duration_s,
            "target_volume_ul": calc.target_volume_ul,
            "estimated_volume_ul": calc.estimated_volume_ul,
        }

    def _confirm_prompt(self, message: str, context: dict[str, Any]) -> None:
        if context.get("assume_yes"):
            return
        callback: PromptCallback | None = context.get("prompt_callback")
        if callback is not None:
            if callback(message):
                return
            raise RuntimeError("prompt_check was cancelled")
        answer = input(f"{message} [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            raise RuntimeError("prompt_check was cancelled")

    def _event_start(
        self,
        recipe: Recipe | None,
        block: dict[str, Any],
        index: int,
        started_monotonic: float,
    ) -> str:
        return self._now()

    def _base_event(
        self,
        recipe: Recipe | None,
        block: dict[str, Any],
        index: int,
        started_monotonic: float,
    ) -> dict[str, Any]:
        return {
            "recipe_id": recipe.recipe_id if recipe is not None else "",
            "block_id": block.get("id", ""),
            "block_type": block.get("type", ""),
            "block_index": index,
            "relative_time_s": self._relative(started_monotonic),
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _relative(started_monotonic: float) -> float:
        return round(time.monotonic() - started_monotonic, 3)
