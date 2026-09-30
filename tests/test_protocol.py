from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from big_walk_eval.protocol import (
    PRACTICE_MOD_KEYS,
    VALID_KEYS,
    Action,
    ActRequest,
    ActResult,
    HoldKeyAction,
    KeyParseError,
    LookAction,
    parse_keys,
)


@pytest.mark.parametrize(
    ("text", "keys"),
    [
        ("w", ["w"]),
        ("W", ["w"]),
        ("shift+w", ["shift", "w"]),
        ("Shift_L+W", ["shift", "w"]),
        ("Return", ["enter"]),
        ("ctrl+s", ["ctrl", "s"]),
        ("space", ["space"]),
        ("+", ["plus"]),
        ("F5", ["f5"]),
    ],
)
def test_parse_keys(text: str, keys: list[str]):
    assert parse_keys(text) == keys


@pytest.mark.parametrize("text", ["", "shift+", "banana", "KP_0"])
def test_parse_keys_rejects(text: str):
    with pytest.raises(KeyParseError):
        parse_keys(text)


def test_practice_keys_are_valid_keys():
    assert PRACTICE_MOD_KEYS <= VALID_KEYS


def test_act_result_json_roundtrip_uses_base64():
    png = bytes(range(256))
    result = ActResult(screenshot_png=png, game_ms=10, truncated=False)
    wire = result.model_dump_json()
    assert "\\u0000" not in wire
    assert ActResult.model_validate_json(wire).screenshot_png == png


def test_action_union_parses_from_json():
    req = ActRequest.model_validate_json(
        '{"slot": 2, "budget_ms": 3000, "actions": ['
        '{"type": "hold_key", "keys": ["w"], "duration_ms": 500},'
        '{"type": "look", "dyaw_deg": 12.5}]}'
    )
    assert req.actions == [
        HoldKeyAction(keys=["w"], duration_ms=500),
        LookAction(dyaw_deg=12.5),
    ]
    assert TypeAdapter(Action).validate_python({"type": "wait", "duration_ms": 5}).duration_ms == 5
