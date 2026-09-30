"""The `computer` tool, bound to the game instead of a Linux sandbox.

The tool name and the parameter names match Inspect's built-in `computer()`
exactly. Providers check only those two things (`is_computer_tool_info`), so
models with native computer use get their native tool, and the calls come
back to this `execute`. Models without native computer use see the
docstring below instead.
"""

from __future__ import annotations

import base64
from typing import Any

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.tool import Tool, ToolError, ToolResult, tool

from big_walk_eval.episode import Episode
from big_walk_eval.look import pixel_to_angles
from big_walk_eval.protocol import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    Action,
    HoldKeyAction,
    KeyAction,
    KeyParseError,
    LookAction,
    MouseAction,
    ScrollAction,
    WaitAction,
    parse_keys,
)

NOT_AVAILABLE = "`{action}` is not available in this game, use `say` to talk."

UNSUPPORTED_ACTIONS = frozenset(
    {
        "type",
        "zoom",
        "cursor_position",
        "left_click_drag",
        "double_click",
        "triple_click",
        "middle_click",
        "back_click",
        "forward_click",
        "open_web_browser",
        "navigate",
    }
)


def png_content(png: bytes) -> ContentImage:
    return ContentImage(image="data:image/png;base64," + base64.b64encode(png).decode())


def to_game_actions(
    args: dict[str, Any], hfov_deg: float, blocked_keys: frozenset[str]
) -> list[Action]:
    """Map one computer-use call onto game actions. `screenshot` maps to no action."""
    action = args.get("action")
    text = args.get("text")
    coordinate = args.get("coordinate")

    def keys() -> list[str]:
        if not text:
            raise ToolError(f"`{action}` needs `text` with the key to press, for example 'w'.")
        try:
            parsed = parse_keys(str(text))
        except KeyParseError as e:
            raise ToolError(str(e)) from e
        bad = [k for k in parsed if k in blocked_keys]
        if bad:
            raise ToolError(f"The key {bad[0]!r} is not allowed in this game.")
        return parsed

    def duration_ms() -> int:
        duration = args.get("duration")
        if duration is None:
            raise ToolError(f"`{action}` needs `duration` in seconds.")
        try:
            seconds = float(duration)
        except (TypeError, ValueError) as e:
            raise ToolError(f"`duration` must be a number of seconds, got {duration!r}.") from e
        if seconds < 0:
            raise ToolError("`duration` must not be negative.")
        return round(seconds * 1000)

    def look_at(required: bool) -> list[Action]:
        if coordinate is None:
            if required:
                raise ToolError(f"`{action}` needs `coordinate` [x, y].")
            return []
        try:
            x, y = (float(c) for c in coordinate)
        except (TypeError, ValueError) as e:
            raise ToolError(f"`coordinate` must be [x, y], got {coordinate!r}.") from e
        if not (0 <= x < SCREEN_WIDTH and 0 <= y < SCREEN_HEIGHT):
            raise ToolError(
                f"`coordinate` {coordinate!r} is outside the {SCREEN_WIDTH}x{SCREEN_HEIGHT} screen."
            )
        dyaw, dpitch = pixel_to_angles(x, y, hfov_deg)
        return [LookAction(dyaw_deg=dyaw, dpitch_deg=dpitch)]

    def button_from_text(default: str) -> str:
        if text in ("left", "right"):
            return str(text)
        return default

    match action:
        case "screenshot":
            return []
        case "key":
            repeat = args.get("repeat") or 1
            try:
                repeat = int(repeat)
            except (TypeError, ValueError) as e:
                raise ToolError(f"`repeat` must be an integer, got {repeat!r}.") from e
            if not 1 <= repeat <= 100:
                raise ToolError("`repeat` must be between 1 and 100.")
            return [KeyAction(keys=keys(), repeat=repeat)]
        case "hold_key":
            return [HoldKeyAction(keys=keys(), duration_ms=duration_ms())]
        case "mouse_move":
            return look_at(required=True)
        case "left_mouse_down" | "left_mouse_up":
            event = "down" if action.endswith("down") else "up"
            return [MouseAction(button=button_from_text("left"), event=event)]
        case "right_mouse_down" | "right_mouse_up":
            event = "down" if action.endswith("down") else "up"
            return [MouseAction(button="right", event=event)]
        case "left_click" | "right_click":
            button = "left" if action == "left_click" else "right"
            return [*look_at(required=False), MouseAction(button=button, event="click")]
        case "wait":
            return [WaitAction(duration_ms=duration_ms())]
        case "scroll":
            direction = args.get("scroll_direction")
            if direction not in ("up", "down", "left", "right"):
                raise ToolError("`scroll` needs `scroll_direction`: up, down, left, or right.")
            amount = int(args.get("scroll_amount") or 1)
            return [ScrollAction(direction=direction, amount=max(1, min(amount, 50)))]
    if action in UNSUPPORTED_ACTIONS:
        raise ToolError(NOT_AVAILABLE.format(action=action))
    raise ToolError(f"Unknown action {action!r}.")


@tool(name="computer", parallel=False)
def computer_tool(episode: Episode, slot: int) -> Tool:
    async def execute(
        action: str | None = None,
        coordinate: list[int] | None = None,
        duration: float | None = None,
        region: list[int] | None = None,
        scroll_amount: int | None = None,
        scroll_direction: str | None = None,
        start_coordinate: list[int] | None = None,
        text: str | None = None,
        repeat: int | None = None,
        press_enter: bool | None = None,
        actions: list[dict[str, Any]] | None = None,
    ) -> ToolResult:
        """Control your body in the game with the keyboard and mouse.

        You see the game in first person. Game time passes only while an action runs.
        Each action returns a new screenshot of your view.

        Args:
          action: The action to perform.
              - `key`: Tap a key or key combination, for example "w" or "shift+w". Use `repeat` to tap several times.
              - `hold_key`: Hold a key or combination for `duration` seconds. Use this to walk, for example text="w", duration=1.
              - `mouse_move`: Turn your head so that the point at `coordinate` moves to the center of the screen.
              - `left_click`, `right_click`: Click a mouse button. With `coordinate`, first turn to look at that point.
              - `left_mouse_down`, `left_mouse_up`: Press or release the left mouse button. A pressed button stays pressed until you release it, also across turns. Set text="right" to use the right button.
              - `right_mouse_down`, `right_mouse_up`: Press or release the right mouse button.
              - `wait`: Let `duration` seconds of game time pass.
              - `scroll`: Turn the mouse wheel.
              - `screenshot`: See your current view. No game time passes.
          coordinate: The [x, y] pixel on the screen, for `mouse_move` and clicks.
          duration: Seconds of game time, for `hold_key` and `wait`.
          region: Not used in this game.
          scroll_amount: Number of wheel steps, for `scroll`.
          scroll_direction: "up", "down", "left", or "right", for `scroll`.
          start_coordinate: Not used in this game.
          text: The key or key combination for `key` and `hold_key`.
          repeat: Number of taps for `key`, 1 to 100.
          press_enter: Not used in this game.
          actions: A list of action objects with the same fields, run in order.
        """
        turn = episode.begin_tool_call(slot)
        calls: list[dict[str, Any]]
        if actions is not None:
            calls = [dict(a) for a in actions]
        elif action is not None:
            calls = [
                {
                    "action": action,
                    "coordinate": coordinate,
                    "duration": duration,
                    "scroll_amount": scroll_amount,
                    "scroll_direction": scroll_direction,
                    "text": text,
                    "repeat": repeat,
                }
            ]
        else:
            raise ToolError("Give an `action`.")

        game_actions: list[Action] = []
        for call in calls:
            game_actions += to_game_actions(call, episode.hfov_deg, episode.config.blocked_keys)

        if not game_actions:
            png = await episode.game.screenshot()
            return [ContentText(text="Your current view."), png_content(png)]

        if turn.remaining_ms == 0:
            raise ToolError("You have no game time left this turn. The action did not run.")

        result = await episode.game.act(slot, game_actions, turn.remaining_ms)
        episode.add_game_time(result.game_ms, result.truncated)
        episode.record_events(result.events)
        summary = f"Done. {result.game_ms} ms of game time passed. "
        if result.truncated:
            summary += "The time limit for this turn cut the action short. "
        summary += f"{turn.remaining_ms} ms left this turn."
        return [ContentText(text=summary), png_content(result.screenshot_png)]

    return execute
