from __future__ import annotations

import base64
import io
import math

import pytest
from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.tool import ToolDef, ToolError, ToolInfo
from inspect_ai.tool._tools._computer._computer import is_computer_tool_info
from PIL import Image

from big_walk_eval.episode import Episode, EpisodeConfig
from big_walk_eval.game.fake_game import FakeGame
from big_walk_eval.look import angles_to_pixel, pixel_to_angles, vfov_to_hfov
from big_walk_eval.protocol import TYPE_MAX_CHARS, KeyAction, LookAction, MouseAction, TypeAction
from big_walk_eval.tools import agent_tools, computer_tool_name
from big_walk_eval.tools.computer import UNSUPPORTED_ACTIONS, computer_tool, to_game_actions
from big_walk_eval.tools.end_episode import end_episode
from tests.conftest import ASH_TO_PLATE_YAW


@pytest.fixture
async def episode(game: FakeGame) -> Episode:
    ep = Episode(game, EpisodeConfig(), {1: "Ash", 2: "Birch"})
    ep.start_turn(0, 1)
    return ep


@pytest.fixture
async def shot_episode(game: FakeGame) -> Episode:
    """Each action returns a screenshot."""
    ep = Episode(game, EpisodeConfig(one_response_per_turn=False), {1: "Ash", 2: "Birch"})
    ep.start_turn(0, 1)
    return ep


def test_computer_tool_gets_native_binding(episode: Episode):
    td = ToolDef(computer_tool(episode, 1))
    info = ToolInfo(name=td.name, description=td.description, parameters=td.parameters)
    assert is_computer_tool_info(info)
    assert td.parallel is False


def test_google_models_without_native_computer_use_get_a_renamed_tool(episode: Episode):
    assert computer_tool_name("google/gemini-3.7-flash") == "game"
    assert computer_tool_name("google/gemini-3-flash-preview") == "computer"
    assert computer_tool_name("anthropic/claude-sonnet-5-5") == "computer"
    names = [ToolDef(t).name for t in agent_tools(episode, 1, "game")]
    assert names == ["game", "end_episode"]


def test_other_tools_are_not_computer(episode: Episode):
    for t in agent_tools(episode, 1)[1:]:
        td = ToolDef(t)
        info = ToolInfo(name=td.name, description=td.description, parameters=td.parameters)
        assert not is_computer_tool_info(info)


@pytest.mark.parametrize("action", sorted(UNSUPPORTED_ACTIONS))
async def test_unsupported_actions_return_error_text(episode: Episode, action: str):
    tool = computer_tool(episode, 1)
    with pytest.raises(ToolError, match="not available in this game. To talk, press"):
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


async def test_hold_key_moves_and_returns_screenshot(shot_episode: Episode):
    tool = computer_tool(shot_episode, 1)
    result = await tool(action="hold_key", text="w", duration=1)
    assert isinstance(result, list)
    assert isinstance(result[0], ContentText) and "1000 ms" in result[0].text
    assert isinstance(result[1], ContentImage)
    state = await shot_episode.game.state()
    assert state.body(1).position[2] == pytest.approx(2.0)
    assert shot_episode.turn is not None and shot_episode.turn.game_ms == 1000


async def test_turn_time_budget(shot_episode: Episode):
    tool = computer_tool(shot_episode, 1)
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
    await end_episode(ep, 1)()
    with pytest.raises(ToolError, match="all 2 actions"):
        await tool(action="screenshot")


async def test_not_your_turn(episode: Episode):
    with pytest.raises(ToolError, match="not your turn"):
        await end_episode(episode, 2)()


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


def test_agents_talk_only_through_the_game(episode: Episode):
    assert [ToolDef(t).name for t in agent_tools(episode, 1)] == ["computer", "end_episode"]


async def test_chat_through_the_computer_tool(episode: Episode):
    tool = computer_tool(episode, 1)
    await tool(
        actions=[
            {"action": "key", "text": "Return"},
            {"action": "type", "text": "hello Birch"},
            {"action": "key", "text": "Return"},
        ]
    )
    [event] = [e for r in episode.events if (e := r.event).type == "text_chat"]
    assert (event.slot, event.data) == (1, {"message": "hello Birch"})


async def test_end_episode_votes(episode: Episode):
    vote = end_episode(episode, 1)
    assert await vote() == "vote recorded"
    assert episode.votes == {1: True, 2: False}
    await vote(withdraw=True)
    assert episode.votes[1] is False


def test_type_maps_to_text_not_keys():
    # Typed text may hold practice-mod hotkey letters: they go out as characters, not keys.
    blocked = frozenset({"r", "1"})
    assert to_game_actions({"action": "type", "text": "Are you there? 1"}, 90, blocked) == [
        TypeAction(text="Are you there? 1")
    ]
    assert to_game_actions({"action": "key", "text": "Return"}, 90, blocked) == [
        KeyAction(keys=["enter"])
    ]


@pytest.mark.parametrize(
    ("text", "error"),
    [(None, "needs `text`"), ("hi\nthere", "one line"), ("x" * (TYPE_MAX_CHARS + 1), "at most")],
)
def test_type_rejects_bad_text(text, error):
    with pytest.raises(ToolError, match=error):
        to_game_actions({"action": "type", "text": text}, 90, frozenset())


def image_of(content: ContentImage) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(content.image.split(",", 1)[1]))).convert("RGB")


async def test_zoom_enlarges_a_region_without_game_time(shot_episode: Episode):
    tool = computer_tool(shot_episode, 1)
    view = image_of((await tool(action="screenshot"))[1])
    whole = await tool(action="zoom", region=[0, 0, 1366, 768])
    assert image_of(whole[1]).tobytes() == view.tobytes()

    zoomed = image_of((await tool(action="zoom", region=[600, 300, 766, 384]))[1])
    assert zoomed.size == (1366, 691)
    corner = view.crop((600, 300, 766, 384)).resize(zoomed.size).getpixel((5, 5))
    assert zoomed.getpixel((5, 5)) == corner
    assert shot_episode.total_game_ms == 0


@pytest.mark.parametrize(
    "region", [None, [1, 2, 3], [10, 10, 5, 20], [0, 0, 2000, 10], ["a", 0, 1, 1]]
)
async def test_zoom_needs_a_region_on_screen(episode: Episode, region):
    with pytest.raises(ToolError, match="region"):
        await computer_tool(episode, 1)(action="zoom", region=region)


async def test_zoom_last_in_a_list_shows_the_view_after_the_actions(shot_episode: Episode):
    tool = computer_tool(shot_episode, 1)
    walk = {"action": "hold_key", "text": "w", "duration": 1}
    result = await tool(actions=[walk, {"action": "zoom", "region": [0, 0, 683, 384]}])
    assert "zoomed into [0, 0, 683, 384]" in result[0].text
    assert image_of(result[1]).size == (1366, 768)
    assert shot_episode.total_game_ms == 1000

    with pytest.raises(ToolError, match="last action"):
        await tool(actions=[{"action": "zoom", "region": [0, 0, 10, 10]}, walk])
    with pytest.raises(ToolError, match="region"):
        await tool(actions=[walk, {"action": "zoom", "region": [0, 0, 0, 0]}])
    assert shot_episode.total_game_ms == 1000


async def test_actions_return_text_only(episode: Episode):
    tool = computer_tool(episode, 1)
    result = await tool(action="hold_key", text="w", duration=1)
    assert result == "Done. 1000 ms of game time passed. 2000 ms left this turn."
    assert "next turn" in await tool(action="screenshot")
    assert episode.total_game_ms == 1000


async def test_zoom_waits_for_the_next_turn(episode: Episode):
    tool = computer_tool(episode, 1)
    walk = {"action": "hold_key", "text": "w", "duration": 1}
    result = await tool(actions=[walk, {"action": "zoom", "region": [0, 0, 683, 384]}])
    assert "next turn starts with your view zoomed into [0, 0, 683, 384]" in result
    assert episode.pending_zoom == {1: [0, 0, 683, 384]}
    with pytest.raises(ToolError, match="region"):
        await tool(action="zoom", region=[0, 0, 0, 0])
    assert episode.pending_zoom == {1: [0, 0, 683, 384]}


def test_one_response_tool_description(episode: Episode, shot_episode: Episode):
    [one, _] = agent_tools(episode, 1, "game")
    assert "not a screenshot" in ToolDef(one).description
    assert "next turn" in ToolDef(one).parameters.properties["action"].description
    [shot, _] = agent_tools(shot_episode, 1, "game")
    assert "returns a new screenshot" in ToolDef(shot).description
