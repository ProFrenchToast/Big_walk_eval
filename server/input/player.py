"""Play a timeline on an input backend in real time."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from big_walk_eval.timeline import InputEvent, Timeline
from server.input.backend import InputBackend

LookFn = Callable[[float, float], Awaitable[None]]


@dataclass(frozen=True)
class _Step:
    t_ms: float
    run: Callable[[], Awaitable[None]]


def mouse_look_steps(
    dyaw_deg: float,
    dpitch_deg: float,
    counts_per_degree: float,
    n_steps: int,
    invert_y: bool = False,
) -> list[tuple[int, int]]:
    """Split a turn into `n_steps` relative mouse moves whose sums are exact integers."""
    total_x = round(dyaw_deg * counts_per_degree)
    total_y = round(dpitch_deg * counts_per_degree) * (-1 if invert_y else 1)
    steps = []
    sent_x = sent_y = 0
    for i in range(1, n_steps + 1):
        x = round(total_x * i / n_steps)
        y = round(total_y * i / n_steps)
        steps.append((x - sent_x, y - sent_y))
        sent_x, sent_y = x, y
    return [s for s in steps if s != (0, 0)]


class TimelinePlayer:
    def __init__(
        self,
        backend: InputBackend,
        counts_per_degree: float,
        invert_y: bool = False,
        look_step_ms: int = 10,
        look_fn: LookFn | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.backend = backend
        self.counts_per_degree = counts_per_degree
        self.invert_y = invert_y
        self.look_step_ms = look_step_ms
        self.look_fn = look_fn
        self.clock = clock
        self.sleep = sleep

    def schedule(self, timeline: Timeline) -> list[_Step]:
        steps: list[_Step] = []
        for ev in timeline.events:
            steps += self._steps_for(ev)
        steps.sort(key=lambda s: s.t_ms)
        return steps

    async def play(self, timeline: Timeline) -> None:
        start = self.clock()
        for step in self.schedule(timeline):
            await self._until(start, step.t_ms)
            await step.run()
        await self._until(start, timeline.end_ms)

    async def _until(self, start: float, t_ms: float) -> None:
        delay = start + t_ms / 1000.0 - self.clock()
        if delay > 0:
            await self.sleep(delay)

    def _steps_for(self, ev: InputEvent) -> list[_Step]:
        b = self.backend
        match ev.op:
            case "key_down":
                return [_Step(ev.t_ms, lambda k=ev.key: b.key_down(k))]
            case "key_up":
                return [_Step(ev.t_ms, lambda k=ev.key: b.key_up(k))]
            case "button_down":
                return [_Step(ev.t_ms, lambda k=ev.button: b.button_down(k))]
            case "button_up":
                return [_Step(ev.t_ms, lambda k=ev.button: b.button_up(k))]
            case "wheel":
                horizontal = ev.wheel_axis == "horizontal"
                return [_Step(ev.t_ms, lambda: b.wheel(ev.wheel, horizontal))]
            case "look":
                if self.look_fn is not None:
                    fn = self.look_fn
                    return [_Step(ev.t_ms, lambda: fn(ev.dyaw_deg, ev.dpitch_deg))]
                n = max(1, ev.duration_ms // self.look_step_ms)
                moves = mouse_look_steps(
                    ev.dyaw_deg, ev.dpitch_deg, self.counts_per_degree, n, self.invert_y
                )
                return [
                    _Step(ev.t_ms + i * ev.duration_ms / n, lambda dx=dx, dy=dy: b.move_rel(dx, dy))
                    for i, (dx, dy) in enumerate(moves)
                ]
        raise ValueError(f"unknown input op {ev.op!r}")
