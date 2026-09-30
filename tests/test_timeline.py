from __future__ import annotations

from big_walk_eval.protocol import (
    BUTTON_EDGE_MS,
    CLICK_MS,
    KEY_GAP_MS,
    KEY_TAP_MS,
    LOOK_MS,
    HoldKeyAction,
    KeyAction,
    LookAction,
    MouseAction,
    WaitAction,
)
from big_walk_eval.timeline import InputEvent, build_timeline


def ops(tl) -> list[tuple[int, str, str | None]]:
    return [(e.t_ms, e.op, e.key or e.button) for e in tl.events]


def test_key_repeat_and_chord():
    tl = build_timeline([KeyAction(keys=["shift", "w"], repeat=2)], 10_000)
    period = KEY_TAP_MS + KEY_GAP_MS
    assert ops(tl) == [
        (0, "key_down", "shift"),
        (0, "key_down", "w"),
        (KEY_TAP_MS, "key_up", "w"),
        (KEY_TAP_MS, "key_up", "shift"),
        (period, "key_down", "shift"),
        (period, "key_down", "w"),
        (period + KEY_TAP_MS, "key_up", "w"),
        (period + KEY_TAP_MS, "key_up", "shift"),
    ]
    assert tl.end_ms == 2 * period
    assert not tl.truncated


def test_hold_is_cut_at_budget_and_released():
    tl = build_timeline(
        [HoldKeyAction(keys=["w"], duration_ms=5000), WaitAction(duration_ms=100)], 3000
    )
    assert ops(tl) == [(0, "key_down", "w"), (3000, "key_up", "w")]
    assert tl.end_ms == 3000
    assert tl.truncated
    assert tl.actions_run == 1


def test_atomic_action_that_does_not_fit_is_skipped():
    tl = build_timeline([WaitAction(duration_ms=950), LookAction(dyaw_deg=5)], 1000)
    assert tl.truncated
    assert tl.end_ms == 950
    assert tl.events == []


def test_exact_budget_is_not_truncated():
    tl = build_timeline([WaitAction(duration_ms=900), LookAction(dyaw_deg=5)], 900 + LOOK_MS)
    assert not tl.truncated
    assert tl.events == [InputEvent(900, "look", dyaw_deg=5, duration_ms=LOOK_MS)]


def test_held_buttons_persist_between_timelines():
    tl = build_timeline([MouseAction(event="down")], 1000)
    assert tl.held_buttons == {"left"}
    assert ops(tl) == [(0, "button_down", "left")]
    assert tl.end_ms == BUTTON_EDGE_MS

    again = build_timeline([MouseAction(event="down")], 1000, tl.held_buttons)
    assert again.events == []
    released = build_timeline([MouseAction(event="up")], 1000, tl.held_buttons)
    assert ops(released) == [(0, "button_up", "left")]
    assert released.held_buttons == frozenset()


def test_click_on_held_button_releases_first():
    tl = build_timeline([MouseAction(button="right", event="click")], 1000, {"right"})
    assert ops(tl) == [
        (0, "button_up", "right"),
        (0, "button_down", "right"),
        (CLICK_MS, "button_up", "right"),
    ]
    assert tl.held_buttons == frozenset()
