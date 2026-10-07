from big_walk_eval.prompts import BIG_WALK_CONTROLS, BIG_WALK_GOURD, system_prompt


def _prompt(**kwargs) -> str:
    return system_prompt(
        name="Ash",
        others=["Birch"],
        game_name="Big Walk",
        controls=BIG_WALK_CONTROLS,
        max_game_ms=10_000,
        max_tool_calls=10,
        **kwargs,
    )


def test_reward_description_only_when_given():
    assert BIG_WALK_GOURD in _prompt(reward_description=BIG_WALK_GOURD)
    assert "vice" not in _prompt()


def test_prompt_asks_for_introductions_not_search():
    p = _prompt()
    assert "introduce yourselves" in p
    assert "find the other players" not in p
