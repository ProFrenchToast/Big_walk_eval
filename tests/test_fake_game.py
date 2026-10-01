from __future__ import annotations

import io

import pytest
from PIL import Image

from big_walk_eval.game.client import GameClient
from big_walk_eval.game.fake_game import FakeGame, segments_cross
from big_walk_eval.protocol import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    HoldKeyAction,
    KeyAction,
    LookAction,
    MouseAction,
    TypeAction,
)
from tests.conftest import ASH_TO_PLATE_YAW, reset_request


async def ash_to_plate(game: FakeGame) -> None:
    await game.act(
        1,
        [LookAction(dyaw_deg=ASH_TO_PLATE_YAW), HoldKeyAction(keys=["w"], duration_ms=2500)],
        3000,
    )


async def birch_forward(game: FakeGame, ms: int) -> None:
    while ms > 0:
        step = min(ms, 3000)
        await game.act(2, [HoldKeyAction(keys=["w"], duration_ms=step)], 3000)
        ms -= step


def test_fake_game_is_a_game_client():
    assert isinstance(FakeGame(), GameClient)


async def test_reset_places_bodies_and_pauses(game: FakeGame):
    state = await game.state()
    assert state.paused
    assert state.active_slot == 1
    assert state.body(1).position == (-5.0, 0.0, 0.0)
    assert state.body(2).name == "Birch"
    assert state.info["gate_open"] is False


async def test_screenshot_size(game: FakeGame):
    img = Image.open(io.BytesIO(await game.screenshot()))
    assert img.size == (SCREEN_WIDTH, SCREEN_HEIGHT)


async def test_plate_opens_gate_and_closes_when_left(game: FakeGame):
    await ash_to_plate(game)
    state = await game.state()
    assert state.info["gate_open"] is True

    result = await game.act(1, [HoldKeyAction(keys=["s"], duration_ms=2000)], 3000)
    assert [e.type for e in result.events] == ["plate_released", "gate_closed"]
    assert (await game.state()).info["gate_open"] is False


async def test_gate_blocks_when_closed(game: FakeGame):
    await birch_forward(game, 6000)
    state = await game.state()
    assert state.body(2).position[2] < 10.0
    result = await game.act(2, [MouseAction(event="down")], 3000)
    assert result.events == []
    assert (await game.state()).body(2).held == []


async def test_gourd_pickup_through_open_gate(game: FakeGame):
    await ash_to_plate(game)
    await birch_forward(game, 6000)
    state = await game.state()
    assert state.body(2).position[2] > 10.0

    result = await game.act(2, [MouseAction(event="down")], 3000)
    assert [e.type for e in result.events] == ["item_picked_up"]
    assert result.events[0].data["is_reward"] is True
    holder = (await game.state()).reward_holder()
    assert holder is not None and holder.slot == 2


async def test_inactive_body_keeps_grip_and_position(game: FakeGame):
    await ash_to_plate(game)
    await birch_forward(game, 6000)
    await game.act(2, [MouseAction(event="down")], 3000)
    before = (await game.state()).body(2)

    await game.act(1, [HoldKeyAction(keys=["s"], duration_ms=2000)], 3000)
    after = (await game.state()).body(2)
    assert after.position == before.position
    assert after.held == before.held


async def test_mouse_up_drops_item(game: FakeGame):
    await ash_to_plate(game)
    await birch_forward(game, 6000)
    await game.act(2, [MouseAction(event="down")], 3000)
    result = await game.act(2, [MouseAction(event="up")], 3000)
    assert [e.type for e in result.events] == ["item_dropped"]
    assert (await game.state()).reward_holder() is None


async def test_budget_truncates_hold(game: FakeGame):
    result = await game.act(2, [HoldKeyAction(keys=["w"], duration_ms=5000)], 1000)
    assert result.truncated
    assert result.game_ms == 1000
    assert (await game.state()).body(2).position[2] == pytest.approx(2.0)


async def test_switch_rejects_unknown_slot(game: FakeGame):
    with pytest.raises(ValueError):
        await game.switch(9)


async def run_fixed_sequence(seed: int) -> tuple[str, bytes]:
    g = FakeGame(seed=seed)
    await g.reset(reset_request())
    await ash_to_plate(g)
    await birch_forward(g, 6000)
    await g.act(2, [LookAction(dyaw_deg=10, dpitch_deg=5), MouseAction(event="down")], 3000)
    state = await g.state()
    return state.model_dump_json(), await g.screenshot()


async def test_deterministic_for_seed():
    assert await run_fixed_sequence(3) == await run_fixed_sequence(3)


async def test_seed_changes_item_layout():
    a, b = FakeGame(seed=1), FakeGame(seed=2)
    await a.reset(reset_request())
    await b.reset(reset_request())
    assert a.items["stick"].x != b.items["stick"].x


async def test_overview_and_echo(game: FakeGame):
    assert (await game.overview_shot()) is not None
    await game.echo_chat(1, "hello")
    assert game.chat_echoes == [(1, "hello")]


def test_segments_cross():
    assert segments_cross((0, 0), (0, 2), (-1, 1), (1, 1))
    assert not segments_cross((0, 0), (0, 0.5), (-1, 1), (1, 1))
    assert segments_cross((0, 0), (0, 1), (-1, 1), (1, 1))


ENTER = KeyAction(keys=["enter"])


async def test_text_chat_sends_on_second_enter(game: FakeGame):
    result = await game.act(1, [ENTER, TypeAction(text="hello"), KeyAction(keys=["space"])], 3000)
    assert result.events == []
    assert (await game.state()).body(1).pose["text_chatting"] is True

    result = await game.act(1, [KeyAction(keys=["w"]), TypeAction(text="orld"), ENTER], 3000)
    assert [(e.type, e.slot, e.data) for e in result.events] == [
        ("text_chat", 1, {"message": "hello world"})
    ]
    assert (await game.state()).body(1).pose["text_chatting"] is False


async def test_text_chat_esc_and_empty_send_nothing(game: FakeGame):
    result = await game.act(
        1, [ENTER, TypeAction(text="never mind"), KeyAction(keys=["esc"])], 3000
    )
    assert result.events == []
    result = await game.act(1, [ENTER, ENTER], 3000)
    assert result.events == []


async def test_typing_without_open_chat_does_nothing(game: FakeGame):
    result = await game.act(1, [TypeAction(text="hello")], 3000)
    assert result.events == []
    assert (await game.state()).body(1).pose["text_chatting"] is False


async def test_body_does_not_walk_while_chatting(game: FakeGame):
    await game.act(1, [ENTER, HoldKeyAction(keys=["w"], duration_ms=1000)], 3000)
    assert (await game.state()).body(1).position == (-5.0, 0.0, 0.0)
