"""The `computer` tool, bound to the game instead of a Linux sandbox.

The tool name and the parameter names match Inspect's built-in `computer()`
exactly. Providers check only those two things (`is_computer_tool_info`), so
models with native computer use get their native tool, and the calls come
back to this `execute`. Models without native computer use see the
docstring below instead.
"""

from __future__ import annotations

import base64
import io
from typing import Any

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.tool import Tool, ToolError, ToolResult, tool
from PIL import Image

from big_walk_eval.episode import Episode
from big_walk_eval.look import pixel_to_angles
from big_walk_eval.protocol import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TYPE_MAX_CHARS,
    Action,
    HoldKeyAction,
    KeyAction,
    KeyParseError,
    LookAction,
    MouseAction,
    ScrollAction,
    TypeAction,
    WaitAction,
    parse_keys,
)

NOT_AVAILABLE = (
    '`{action}` is not available in this game. To talk, press `key` "Return", '
    '`type` your message, and press "Return" again.'
)

UNSUPPORTED_ACTIONS = frozenset(
    {
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


def zoom_box(
    region: Any, width: int = SCREEN_WIDTH, height: int = SCREEN_HEIGHT
) -> tuple[int, int, int, int]:
    try:
        x0, y0, x1, y1 = (round(float(v)) for v in region)
    except (TypeError, ValueError) as e:
        raise ToolError(f"`zoom` needs `region` [x0, y0, x1, y1], got {region!r}.") from e
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ToolError(
            f"`region` {region!r} must be [x0, y0, x1, y1] with x0 < x1 and y0 < y1, "
            f"inside the {width}x{height} screen."
        )
    return x0, y0, x1, y1


def zoom_png(png: bytes, region: Any) -> bytes:
    """The `region` [x0, y0, x1, y1] of a screenshot, enlarged to fit the screen size."""
    with Image.open(io.BytesIO(png)) as img:
        x0, y0, x1, y1 = zoom_box(region, *img.size)
        crop = img.crop((x0, y0, x1, y1))
    scale = min(SCREEN_WIDTH / (x1 - x0), SCREEN_HEIGHT / (y1 - y0))
    size = (round((x1 - x0) * scale), round((y1 - y0) * scale))
    buf = io.BytesIO()
    crop.resize(size, Image.Resampling.LANCZOS).save(buf, format="PNG")
    return buf.getvalue()


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
        case "type":
            if not text:
                raise ToolError("`type` needs `text`.")
            if any(not c.isprintable() for c in str(text)):
                raise ToolError(
                    "`text` must be one line. Press Enter with `key` to send a message."
                )
            if len(str(text)) > TYPE_MAX_CHARS:
                raise ToolError(f"`text` can have at most {TYPE_MAX_CHARS} characters.")
            return [TypeAction(text=str(text))]
    if action in UNSUPPORTED_ACTIONS:
        raise ToolError(NOT_AVAILABLE.format(action=action))
    raise ToolError(f"Unknown action {action!r}.")


ONE_RESPONSE_DESCRIPTION = """\
Control your body in the game with the keyboard and mouse.

You see the game in first person. Game time passes only while an action runs.
Actions return a short text result, not a screenshot. You see your view again
at the start of your next turn."""

ONE_RESPONSE_ACTION = """\
The action to perform.
- `key`: Tap a key or key combination, for example "w" or "shift+w". Use `repeat` to tap several times.
- `hold_key`: Hold a key or combination for `duration` seconds. Use this to walk, for example text="w", duration=1.
- `mouse_move`: Turn your head so that the point at `coordinate` moves to the center of the screen.
- `left_click`, `right_click`: Click a mouse button. With `coordinate`, first turn to look at that point.
- `left_mouse_down`, `left_mouse_up`: Press or release the left mouse button. A pressed button stays pressed until you release it, also across turns. Set text="right" to use the right button.
- `right_mouse_down`, `right_mouse_up`: Press or release the right mouse button.
- `wait`: Let `duration` seconds of game time pass.
- `scroll`: Turn the mouse wheel.
- `type`: Type `text` into the in-game text chat. Open the chat with `key` "Return" first, then press "Return" again to send.
- `zoom`: Your next turn also shows the `region` of your view enlarged, for example to read small text. In a list of `actions`, it must be the last one.
All coordinates refer to the screenshot at the start of this turn. After you turn your head, the pixels no longer match."""


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
              - `type`: Type `text` into the in-game text chat. Open the chat with `key` "Return" first, then press "Return" again to send.
              - `screenshot`: See your current view. No game time passes.
              - `zoom`: See the `region` of your current view enlarged, for example to read small text. No game time passes. In a list of `actions`, it must be the last one, and it zooms into the view after the other actions.
          coordinate: The [x, y] pixel on the screen, for `mouse_move` and clicks.
          duration: Seconds of game time, for `hold_key` and `wait`.
          region: The [x0, y0, x1, y1] pixels of the screen to enlarge, for `zoom`.
          scroll_amount: Number of wheel steps, for `scroll`.
          scroll_direction: "up", "down", "left", or "right", for `scroll`.
          start_coordinate: Not used in this game.
          text: The key or key combination for `key` and `hold_key`, or the text for `type`.
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
                    "region": region,
                }
            ]
        else:
            raise ToolError("Give an `action`.")

        zoom = None
        if calls and calls[-1].get("action") == "zoom":
            zoom = calls.pop().get("region")
            zoom_box(zoom)  # Check the region before any action runs.
        if any(c.get("action") == "zoom" for c in calls):
            raise ToolError("`zoom` can only be the last action in a list.")

        game_actions: list[Action] = []
        for call in calls:
            game_actions += to_game_actions(call, episode.hfov_deg, episode.config.blocked_keys)

        text_only = episode.config.one_response_per_turn
        if text_only and zoom is not None:
            episode.pending_zoom[slot] = list(zoom_box(zoom))

        if not game_actions and text_only:
            if zoom is not None:
                return f"Your next turn starts with your view zoomed into {zoom} as well."
            return "Your next turn starts with a new screenshot of your view."

        if not game_actions:
            png = await episode.game.screenshot()
            if zoom is not None:
                return [
                    ContentText(text=f"Your view, zoomed into {zoom}."),
                    png_content(zoom_png(png, zoom)),
                ]
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
        if text_only:
            if zoom is not None:
                summary += f" Your next turn starts with your view zoomed into {zoom} as well."
            return summary
        png = result.screenshot_png
        if zoom is not None:
            png = zoom_png(png, zoom)
            summary += f" Your view, zoomed into {zoom}."
        return [ContentText(text=summary), png_content(png)]

    return execute
