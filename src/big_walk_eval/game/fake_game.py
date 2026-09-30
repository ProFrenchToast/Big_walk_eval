"""A small deterministic game that implements `GameClient`, for tests and CI.

The world is a 30 m x 30 m field seen from above in the x-z plane (y is up).
A wall at z = GATE_Z crosses the field with a gate in the middle. The gourd
is behind the wall. The gate is open only while a body stands on the
pressure plate, and the plate is far from the gate, so one body must stand
on the plate while another walks through and takes the gourd.

Like the real game under hot-swap, only the active body moves. Inactive
bodies keep their position and whatever they hold.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Literal

from big_walk_eval.game import fake_render
from big_walk_eval.protocol import (
    Action,
    ActResult,
    BodyState,
    GameEvent,
    GameState,
    Hand,
    HealthResponse,
    HeldItem,
    ResetRequest,
    Vec3,
)
from big_walk_eval.timeline import InputEvent, build_timeline

HALF_SIZE = 15.0
GATE_Z = 10.0
GATE_HALF_WIDTH = 1.0
PLATE_XZ = (-8.0, 4.0)
PLATE_RADIUS = 1.0
GOURD_XZ = (0.0, 13.0)
STICK_XZ = (3.0, 2.0)
WALK_SPEED = 2.0
SPRINT_FACTOR = 1.5
REACH_M = 1.5
TICK_MS = 20
HFOV_DEG = 90.0
MAX_PITCH_DEG = 80.0

_MOVE_KEYS = {
    "w": (0.0, 1.0),
    "up": (0.0, 1.0),
    "s": (0.0, -1.0),
    "down": (0.0, -1.0),
    "a": (-1.0, 0.0),
    "left": (-1.0, 0.0),
    "d": (1.0, 0.0),
    "right": (1.0, 0.0),
}
_BUTTON_HAND: dict[str, Hand] = {"left": "left", "right": "right"}


@dataclass(frozen=True)
class Wall:
    x1: float
    z1: float
    x2: float
    z2: float
    kind: Literal["boundary", "wall", "gate"]


@dataclass
class FakeBody:
    slot: int
    name: str
    x: float
    z: float
    yaw: float
    pitch: float = 0.0
    held: dict[Hand, str] = field(default_factory=dict)
    buttons: set[str] = field(default_factory=set)

    def forward(self) -> tuple[float, float]:
        r = math.radians(self.yaw)
        return math.sin(r), math.cos(r)


@dataclass
class FakeItem:
    id: str
    type: str
    x: float
    z: float
    is_reward: bool
    holder: tuple[int, Hand] | None = None


WALLS: tuple[Wall, ...] = (
    Wall(-HALF_SIZE, -HALF_SIZE, HALF_SIZE, -HALF_SIZE, "boundary"),
    Wall(HALF_SIZE, -HALF_SIZE, HALF_SIZE, HALF_SIZE, "boundary"),
    Wall(HALF_SIZE, HALF_SIZE, -HALF_SIZE, HALF_SIZE, "boundary"),
    Wall(-HALF_SIZE, HALF_SIZE, -HALF_SIZE, -HALF_SIZE, "boundary"),
    Wall(-HALF_SIZE, GATE_Z, -GATE_HALF_WIDTH, GATE_Z, "wall"),
    Wall(GATE_HALF_WIDTH, GATE_Z, HALF_SIZE, GATE_Z, "wall"),
    Wall(-GATE_HALF_WIDTH, GATE_Z, GATE_HALF_WIDTH, GATE_Z, "gate"),
)


def _orient(ax: float, az: float, bx: float, bz: float, cx: float, cz: float) -> float:
    return (bx - ax) * (cz - az) - (bz - az) * (cx - ax)


def _on_segment(a: tuple[float, float], b: tuple[float, float], p: tuple[float, float]) -> bool:
    return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def segments_cross(
    p1: tuple[float, float],
    p2: tuple[float, float],
    q1: tuple[float, float],
    q2: tuple[float, float],
) -> bool:
    """True if segment p1-p2 touches or crosses segment q1-q2."""
    d1 = _orient(*q1, *q2, *p1)
    d2 = _orient(*q1, *q2, *p2)
    d3 = _orient(*p1, *p2, *q1)
    d4 = _orient(*p1, *p2, *q2)
    if ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4)):
        return True
    return (
        (d1 == 0 and _on_segment(q1, q2, p1))
        or (d2 == 0 and _on_segment(q1, q2, p2))
        or (d3 == 0 and _on_segment(p1, p2, q1))
        or (d4 == 0 and _on_segment(p1, p2, q2))
    )


class FakeGame:
    """Implements `GameClient`. Deterministic for a given seed and action sequence."""

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed
        self.bodies: dict[int, FakeBody] = {}
        self.items: dict[str, FakeItem] = {}
        self.active_slot = 0
        self.paused = True
        self.game_ms = 0
        self.gate_open = False
        self.chat_echoes: list[tuple[int, str]] = []
        self._events: list[GameEvent] = []

    # ------------------------------------------------------------ GameClient

    async def health(self) -> HealthResponse:
        return HealthResponse(ok=True, backend="fake", game_version="fake-1")

    async def reset(self, request: ResetRequest) -> GameState:
        if not request.bodies:
            raise ValueError("reset needs at least one body")
        rng = random.Random(f"{self.seed}:{request.puzzle_id}")
        self.bodies = {
            b.slot: FakeBody(
                slot=b.slot,
                name=b.name,
                x=b.position[0],
                z=b.position[2],
                yaw=_wrap(b.yaw_deg),
            )
            for b in request.bodies
        }
        gx, gz = GOURD_XZ
        sx, sz = STICK_XZ
        self.items = {
            "gourd": FakeItem("gourd", "Gourd", gx + rng.uniform(-0.3, 0.3), gz, True),
            "stick": FakeItem("stick", "Stick", sx + rng.uniform(-1, 1), sz, False),
        }
        self.active_slot = request.bodies[0].slot
        self.paused = True
        self.game_ms = 0
        self._events = []
        self.gate_open = self._plate_pressed()
        return await self.state()

    async def switch(self, slot: int) -> None:
        if slot not in self.bodies:
            raise ValueError(f"no body in slot {slot}")
        self.active_slot = slot

    async def screenshot(self) -> bytes:
        return fake_render.first_person(self, self.bodies[self.active_slot])

    async def act(self, slot: int, actions: list[Action], budget_ms: int) -> ActResult:
        await self.switch(slot)
        body = self.bodies[slot]
        tl = build_timeline(actions, budget_ms, body.buttons)
        keys: set[str] = set()
        t = 0
        self.paused = False
        for ev in tl.events:
            self._simulate(body, keys, ev.t_ms - t)
            t = ev.t_ms
            self._apply(body, keys, ev)
        self._simulate(body, keys, tl.end_ms - t)
        self.paused = True
        return ActResult(
            screenshot_png=await self.screenshot(),
            game_ms=tl.end_ms,
            truncated=tl.truncated,
            events=self._drain(),
        )

    async def state(self) -> GameState:
        return GameState(
            paused=self.paused,
            active_slot=self.active_slot,
            bodies=[self._body_state(b) for b in self.bodies.values()],
            events=self._drain(),
            game_ms=self.game_ms,
            camera_hfov_deg=HFOV_DEG,
            info={"gate_open": self.gate_open},
        )

    async def echo_chat(self, slot: int, text: str) -> None:
        self.chat_echoes.append((slot, text))

    async def overview_shot(
        self, position: Vec3 | None = None, look_at: Vec3 | None = None
    ) -> bytes | None:
        return fake_render.overview(self)

    async def close(self) -> None:
        return None

    # ------------------------------------------------------------- world rules

    def blocking_walls(self) -> list[Wall]:
        return [w for w in WALLS if w.kind != "gate" or not self.gate_open]

    def item_position(self, item: FakeItem) -> tuple[float, float]:
        if item.holder is None:
            return item.x, item.z
        body = self.bodies[item.holder[0]]
        fx, fz = body.forward()
        side = -0.3 if item.holder[1] == "left" else 0.3
        return body.x + 0.4 * fx + side * fz, body.z + 0.4 * fz - side * fx

    def _plate_pressed(self) -> bool:
        px, pz = PLATE_XZ
        return any(math.hypot(b.x - px, b.z - pz) <= PLATE_RADIUS for b in self.bodies.values())

    def _blocked(self, a: tuple[float, float], b: tuple[float, float]) -> bool:
        return any(segments_cross(a, b, (w.x1, w.z1), (w.x2, w.z2)) for w in self.blocking_walls())

    def _simulate(self, body: FakeBody, keys: set[str], dt_ms: int) -> None:
        while dt_ms > 0:
            step = min(TICK_MS, dt_ms)
            dt_ms -= step
            self.game_ms += step
            mx = sum(_MOVE_KEYS[k][0] for k in keys if k in _MOVE_KEYS)
            mz = sum(_MOVE_KEYS[k][1] for k in keys if k in _MOVE_KEYS)
            norm = math.hypot(mx, mz)
            if norm == 0:
                continue
            speed = WALK_SPEED * (SPRINT_FACTOR if "shift" in keys else 1.0)
            dist = speed * step / 1000.0
            fx, fz = body.forward()
            rx, rz = fz, -fx
            dx = (mz * fx + mx * rx) / norm * dist
            dz = (mz * fz + mx * rz) / norm * dist
            new = (body.x + dx, body.z + dz)
            if not self._blocked((body.x, body.z), new):
                body.x, body.z = new
                self._update_gate(body.slot)

    def _update_gate(self, slot: int | None) -> None:
        pressed = self._plate_pressed()
        if pressed == self.gate_open:
            return
        self.gate_open = pressed
        self._emit("plate_pressed" if pressed else "plate_released", slot)
        self._emit("gate_opened" if pressed else "gate_closed", slot)

    def _apply(self, body: FakeBody, keys: set[str], ev: InputEvent) -> None:
        match ev.op:
            case "key_down":
                keys.add(ev.key or "")
            case "key_up":
                keys.discard(ev.key or "")
            case "look":
                body.yaw = _wrap(body.yaw + ev.dyaw_deg)
                body.pitch = max(-MAX_PITCH_DEG, min(MAX_PITCH_DEG, body.pitch + ev.dpitch_deg))
            case "button_down":
                body.buttons.add(ev.button or "")
                hand = _BUTTON_HAND.get(ev.button or "")
                if hand:
                    self._grab(body, hand)
            case "button_up":
                body.buttons.discard(ev.button or "")
                hand = _BUTTON_HAND.get(ev.button or "")
                if hand:
                    self._release(body, hand)
            case "wheel":
                pass

    def _grab(self, body: FakeBody, hand: Hand) -> None:
        if hand in body.held:
            return
        best: FakeItem | None = None
        best_d = REACH_M
        for item in self.items.values():
            if item.holder is not None:
                continue
            d = math.hypot(item.x - body.x, item.z - body.z)
            if d <= best_d and not self._blocked((body.x, body.z), (item.x, item.z)):
                best, best_d = item, d
        if best is None:
            return
        best.holder = (body.slot, hand)
        body.held[hand] = best.id
        self._emit(
            "item_picked_up",
            body.slot,
            item_id=best.id,
            item_type=best.type,
            is_reward=best.is_reward,
            hand=hand,
        )

    def _release(self, body: FakeBody, hand: Hand) -> None:
        item_id = body.held.pop(hand, None)
        if item_id is None:
            return
        item = self.items[item_id]
        fx, fz = body.forward()
        drop = (body.x + 0.5 * fx, body.z + 0.5 * fz)
        if self._blocked((body.x, body.z), drop):
            drop = (body.x, body.z)
        item.x, item.z = drop
        item.holder = None
        self._emit("item_dropped", body.slot, item_id=item.id, hand=hand)

    def _body_state(self, b: FakeBody) -> BodyState:
        return BodyState(
            slot=b.slot,
            name=b.name,
            position=(b.x, 0.0, b.z),
            yaw_deg=b.yaw,
            pitch_deg=b.pitch,
            held=[
                HeldItem(
                    hand=hand,
                    item_id=item_id,
                    item_type=self.items[item_id].type,
                    is_reward=self.items[item_id].is_reward,
                )
                for hand, item_id in sorted(b.held.items())
            ],
        )

    def _emit(self, type_: str, slot: int | None, **data: object) -> None:
        self._events.append(GameEvent(type=type_, t_ms=self.game_ms, slot=slot, data=data))

    def _drain(self) -> list[GameEvent]:
        out, self._events = self._events, []
        return out


def _wrap(yaw: float) -> float:
    y = math.fmod(yaw + 180.0, 360.0)
    if y < 0:
        y += 360.0
    return y - 180.0
