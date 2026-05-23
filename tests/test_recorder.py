from syringe_perfusion.recorder import RecipeRecorder


def test_recorder_inserts_wait_blocks() -> None:
    recipe = RecipeRecorder.recipe_from_timed_events(
        [
            (0.0, {"type": "pump_start", "pump": "IN", "action": "start_forward", "profile": "fast30_1ml"}),
            (0.5, {"type": "pump_start", "pump": "OUT", "action": "start_reverse", "profile": "drain30_1ml"}),
            (35.0, {"type": "stop_all", "note": "Safety stop"}),
        ],
        recipe_id="recorded_pushpull",
        display_name="Recorded push-pull",
    )
    assert [block["type"] for block in recipe.blocks] == [
        "pump_start",
        "wait",
        "pump_start",
        "wait",
        "stop_all",
    ]
    assert recipe.blocks[1]["duration_s"] == 0.5
    assert recipe.blocks[3]["duration_s"] == 34.5
