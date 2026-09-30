from __future__ import annotations

import math

import pytest
from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.tool import ToolDef, ToolError, ToolInfo
from inspect_ai.tool._tools._computer._computer import is_computer_tool_info

from big_walk_eval.episode import Episode, EpisodeConfig
from big_walk_eval.game.fake_game import FakeGame
from big_walk_eval.look import angles_to_pixel, pixel_to_angles, vfov_to_hfov
from big_walk_eval.protocol import LookAction, MouseAction
from big_walk_eval.tools import agent_tools
from big_walk_eval.tools.computer import UNSUPPORTED_ACTIONS, computer_tool, to_game_actions
from big_walk_eval.tools.end_episode import end_episode
from big_walk_eval.tools.say import say
from tests.conftest import ASH_TO_PLATE_YAW, reset_request


@pytest.fixture
async def episode(game: FakeGame) -> Episode:
    ep = Episode(game, EpisodeConfig(), {1: "Ash", 2: "Birch"})
    ep.start_turn(0, 1)
    return ep


def test_computer_tool_gets_native_binding(episode: Episode):
    td = ToolDef(computer_tool(episode, 1))
    info = ToolInfo(name=td.name, description=td.description, parameters=td.parameters)
    assert is_computer_tool_info(info)
    assert td.parallel is False


def test_other_tools_are_not_computer(episode: Episode):
    for t in agent_tools(episode, 1)[1:]:
        td = ToolDef(t)
        info = ToolInfo(name=td.name, description=td.description, parameters=td.parameters)
        assert not is_computer_tool_info(info)


@pytest.mark.parametrize("action", sorted(UNSUPPORTED_ACTIONS))
async def test_unsupported_actions_return_error_text(episode: Episode, action: str):
    tool = computer_tool(episode, 1)
    with pytest.raises(ToolError, match="not available in this game, use `say` to talk"):
        await tool(action=action, text="hi", coordinate=[1, 1])


def test_mouse_move_angle_math():
    assert pixel_to_angles(683, 384, 90) == (0.0, 0.0)
    dyaw, dpitch = pixel_to_angles(0, 384, 90)
    assert dyaw == pytest.approx(-45.0)
    assert dpitch == 0.0
    dyaw, dpitch = pixel_to_angles(1366, 768, 90)
    assert dyaw == pytest.approx(45.0)
    assert dpitch == pytest.approx(math.degrees(math.atan(384 / 683)))
    x, y = angles_to_pixel(ASH_TO_PLATE_YAW, 10, 90)
    back = pixel_to_angles(x, y, 90)
    assert back[0] == pytest.approx(ASH_TO_PLATE_YAW, abs=0.1)
    assert back[1] == pytest.approx(10, abs=0.1)
    assert vfov_to_hfov(60) == pytest.approx(91.52, abs=0.01)
    with pytest.raises(ValueError):
        angles_to_pixel(60, 0, 90)


def test_mapping_of_supported_actions():
    blocked = frozenset({"r"})
    [look] = to_game_actions({"action": "mouse_move", "coordinate": [0, 384]}, 90, blocked)
    assert isinstance(look, LookAction) and look.dyaw_deg == pytest.approx(-45)
    look, click = to_game_actions({"action": "left_click", "coordinate": [683, 0]}, 90, blocked)
    assert isinstance(look, LookAction) and look.dpitch_deg < 0
    assert click == MouseAction(button="left", event="click")
    assert to_game_actions({"action": "left_mouse_down", "text": "right"}, 90, blocked) == [
        MouseAction(button="right", event="down")
    ]
    assert to_game_actions({"action": "screenshot"}, 90, blocked) == []


@pytest.mark.parametrize("key", ["r", "1", "+", "shift+R", "F5", "g"])
async def test_practice_mod_keys_are_blocked(episode: Episode, key: str):
    tool = computer_tool(episode, 1)
    with pytest.raises(ToolError, match="not allowed"):
        await tool(action="key", text=key)


async def test_hold_key_moves_and_returns_screenshot(episode: Episode):
    tool = computer_tool(episode, 1)
    result = await tool(action="hold_key", text="w", duration=1)
    assert isinstance(result, list)
    assert isinstance(result[0], ContentText) and "1000 ms" in result[0].text
    assert isinstance(result[1], ContentImage)
    state = await episode.game.state()
    assert state.body(1).position[2] == pytest.approx(2.0)
    assert episode.turn is not None and episode.turn.game_ms == 1000


async def test_turn_time_budget(episode: Episode):
    tool = computer_tool(episode, 1)
    result = await tool(action="hold_key", text="w", duration=10)
    assert "cut the action short" in result[0].text
    with pytest.raises(ToolError, match="no game time left"):
        await tool(action="wait", duration=1)
    shot = await tool(action="screenshot")
    assert isinstance(shot[1], ContentImage)


async def test_tool_call_limit(game: FakeGame):
    ep = Episode(game, EpisodeConfig(max_tool_calls_per_turn=2), {1: "Ash", 2: "Birch"})
    ep.start_turn(0, 1)
    tool = computer_tool(ep, 1)
    await tool(action="screenshot")
    await say(ep, 1)(message="hi")
    with pytest.raises(ToolError, match="all 2 actions"):
        await tool(action="screenshot")


async def test_not_your_turn(episode: Episode):
    with pytest.raises(ToolError, match="not your turn"):
        await say(episode, 2)(message="hi")


async def test_actions_list(episode: Episode):
    tool = computer_tool(episode, 1)
    await tool(
        actions=[
            {"action": "mouse_move", "coordinate": list(angles_to_pixel(ASH_TO_PLATE_YAW, 0, 90))},
            {"action": "hold_key", "text": "w", "duration": 2.5},
        ]
    )
    state = await episode.game.state()
    assert state.info["gate_open"] is True


async def test_say_routes_by_range():
    game = FakeGame()
    await game.reset(reset_request())
    ep = Episode(game, EpisodeConfig(chat_range_m=4.0), {1: "Ash", 2: "Birch"})
    ep.start_turn(0, 1)
    assert await say(ep, 1)(message="  too far?  ") == "sent"
    assert ep.chat.deliver(2) == []
    assert ep.chat.log[0].text == "too far?"

    ep = Episode(game, EpisodeConfig(chat_range_m=6.0, echo_chat=True), {1: "Ash", 2: "Birch"})
    ep.start_turn(0, 1)
    await say(ep, 1)(message="hello")
    [msg] = ep.chat.deliver(2)
    assert (msg.sender_name, msg.text, msg.recipients) == ("Ash", "hello", [2])
    assert game.chat_echoes == [(1, "hello")]


async def test_end_episode_votes(episode: Episode):
    vote = end_episode(episode, 1)
    assert await vote() == "vote recorded"
    assert episode.votes == {1: True, 2: False}
    await vote(withdraw=True)
    assert episode.votes[1] is False
