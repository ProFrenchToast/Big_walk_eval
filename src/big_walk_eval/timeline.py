"""Convert a list of actions into timed input events under a game-time budget.

FakeGame and the real game server both play the same timeline, so a budget
and a truncation mean the same thing in tests and in the game.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from big_walk_eval.protocol import (
    BUTTON_EDGE_MS,
    CLICK_MS,
    KEY_GAP_MS,
    KEY_TAP_MS,
    LOOK_MS,
    SCROLL_MS,
    Action,
    HoldKeyAction,
    KeyAction,
    LookAction,
    MouseAction,
    ScrollAction,
    WaitAction,
)

InputOp = Literal["key_down", "key_up", "button_down", "button_up", "look", "wheel"]


@dataclass(frozen=True)
class InputEvent:
    t_ms: int
    op: InputOp
    key: str | None = None
    button: str | None = None
    dyaw_deg: float = 0.0
    dpitch_deg: float = 0.0
    duration_ms: int = 0
    wheel: int = 0
    wheel_axis: Literal["vertical", "horizontal"] = "vertical"


@dataclass
class Timeline:
    events: list[InputEvent] = field(default_factory=list)
    end_ms: int = 0
    truncated: bool = False
    actions_run: int = 0
    held_buttons: frozenset[str] = frozenset()


def action_ms(action: Action) -> int:
    match action:
        case KeyAction(repeat=repeat):
            return repeat * (KEY_TAP_MS + KEY_GAP_MS)
        case HoldKeyAction(duration_ms=d) | WaitAction(duration_ms=d):
            return d
        case LookAction():
            return LOOK_MS
        case MouseAction(event="click"):
            return CLICK_MS + BUTTON_EDGE_MS
        case MouseAction():
            return BUTTON_EDGE_MS
        case ScrollAction():
            return SCROLL_MS
    raise TypeError(f"unknown action {action!r}")


def build_timeline(
    actions: Iterable[Action],
    budget_ms: int,
    held_buttons: Iterable[str] = (),
) -> Timeline:
    """Schedule actions one after another until the budget runs out.

    `hold_key` and `wait` are cut at the budget. Other actions run whole or
    not at all. `held_buttons` are mouse buttons already held from earlier
    turns; the result says which buttons are held after the timeline.
    """
    tl = Timeline()
    held = set(held_buttons)
    t = 0
    actions = list(actions)
    for i, action in enumerate(actions):
        remaining = budget_ms - t
        dur = action_ms(action)
        if remaining <= 0:
            tl.truncated = True
            break
        if dur > remaining:
            if isinstance(action, HoldKeyAction | WaitAction):
                action = action.model_copy(update={"duration_ms": remaining})
                dur = remaining
                tl.truncated = True
            else:
                tl.truncated = True
                break
        tl.events.extend(_events_for(action, t, held))
        t += dur
        tl.actions_run = i + 1
        if tl.truncated:
            break
    tl.end_ms = t
    tl.held_buttons = frozenset(held)
    return tl


def _events_for(action: Action, t: int, held: set[str]) -> list[InputEvent]:
    match action:
        case KeyAction(keys=keys, repeat=repeat):
            out: list[InputEvent] = []
            for r in range(repeat):
                start = t + r * (KEY_TAP_MS + KEY_GAP_MS)
                out += [InputEvent(start, "key_down", key=k) for k in keys]
                out += [InputEvent(start + KEY_TAP_MS, "key_up", key=k) for k in reversed(keys)]
            return out
        case HoldKeyAction(keys=keys, duration_ms=d):
            return [InputEvent(t, "key_down", key=k) for k in keys] + [
                InputEvent(t + d, "key_up", key=k) for k in reversed(keys)
            ]
        case LookAction(dyaw_deg=dy, dpitch_deg=dp):
            return [InputEvent(t, "look", dyaw_deg=dy, dpitch_deg=dp, duration_ms=LOOK_MS)]
        case MouseAction(button=b, event="down"):
            if b in held:
                return []
            held.add(b)
            return [InputEvent(t, "button_down", button=b)]
        case MouseAction(button=b, event="up"):
            if b not in held:
                return []
            held.discard(b)
            return [InputEvent(t, "button_up", button=b)]
        case MouseAction(button=b, event="click"):
            out = []
            if b in held:
                out.append(InputEvent(t, "button_up", button=b))
            out += [
                InputEvent(t, "button_down", button=b),
                InputEvent(t + CLICK_MS, "button_up", button=b),
            ]
            held.discard(b)
            return out
        case WaitAction():
            return []
        case ScrollAction(direction=direction, amount=amount):
            sign = 1 if direction in ("up", "right") else -1
            axis = "vertical" if direction in ("up", "down") else "horizontal"
            return [InputEvent(t, "wheel", wheel=sign * amount, wheel_axis=axis)]
    raise TypeError(f"unknown action {action!r}")
