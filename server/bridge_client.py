"""TCP client for the BigWalk.EvalBridge mod.

Wire format: one JSON object per line, UTF-8, on 127.0.0.1:47800.
  request:  {"id": 7, "cmd": "get_state", "args": {...}}
  response: {"id": 7, "ok": true, "result": {...}}
            {"id": 7, "ok": false, "error": "message"}
Slots are 1-based, as in the harness. The mod maps them to the practice
mod's slot index (slot 1 = key "1" = practice index 0).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import itertools
import json
from typing import Any

from pydantic import BaseModel, Field

from big_walk_eval.protocol import GameEvent, Hand, Vec3


class BridgeError(RuntimeError):
    pass


class BridgeHeld(BaseModel):
    hand: Hand
    item_id: str
    item_type: str
    is_reward: bool | None = None


class BridgeBody(BaseModel):
    slot: int
    position: Vec3
    yaw_deg: float
    pitch_deg: float = 0.0
    held: list[BridgeHeld] = Field(default_factory=list)


class BridgeState(BaseModel):
    paused: bool
    active_slot: int
    time_s: float | None = None
    camera_vfov_deg: float | None = None
    bodies: list[BridgeBody]


class BridgeHello(BaseModel):
    game_version: str | None = None
    bridge_version: str | None = None
    practice_version: str | None = None


class BridgeClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 47800, timeout_s: float = 30.0):
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._ids = itertools.count(1)
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port, limit=64 * 1024 * 1024),
            self.timeout_s,
        )

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(ConnectionError):
                await self._writer.wait_closed()
        self._reader = self._writer = None

    async def call(self, cmd: str, **args: Any) -> dict[str, Any]:
        async with self._lock:
            if not self.connected:
                await self.connect()
            assert self._reader is not None and self._writer is not None
            request_id = next(self._ids)
            line = json.dumps({"id": request_id, "cmd": cmd, "args": args}) + "\n"
            try:
                self._writer.write(line.encode())
                await self._writer.drain()
                raw = await asyncio.wait_for(self._reader.readline(), self.timeout_s)
            except (ConnectionError, TimeoutError) as e:
                await self.close()
                raise BridgeError(f"bridge {cmd}: {e!r}") from e
            if not raw:
                await self.close()
                raise BridgeError(f"bridge closed the connection during {cmd}")
            response = json.loads(raw)
            if response.get("id") != request_id:
                await self.close()
                raise BridgeError(f"bridge answered id {response.get('id')}, expected {request_id}")
            if not response.get("ok"):
                raise BridgeError(f"bridge {cmd}: {response.get('error', 'unknown error')}")
            return response.get("result") or {}

    # ------------------------------------------------------------- commands

    async def hello(self) -> BridgeHello:
        return BridgeHello.model_validate(await self.call("hello"))

    async def pause(self) -> float | None:
        return (await self.call("pause")).get("time_s")

    async def resume(self) -> float | None:
        return (await self.call("resume")).get("time_s")

    async def get_state(self) -> BridgeState:
        return BridgeState.model_validate(await self.call("get_state"))

    async def switch_slot(self, slot: int) -> None:
        await self.call("switch_slot", slot=slot)

    async def spawn_bodies(self, n: int) -> int:
        return int((await self.call("spawn_bodies", n=n)).get("count", n))

    async def teleport(self, slot: int, position: Vec3, yaw_deg: float) -> None:
        await self.call("teleport", slot=slot, position=list(position), yaw_deg=yaw_deg)

    async def screenshot(self, width: int, height: int) -> bytes:
        result = await self.call("screenshot", width=width, height=height)
        return base64.b64decode(result["png_base64"])

    async def load_snapshot(self, name: str) -> None:
        await self.call("load_snapshot", name=name)

    async def events(self) -> list[GameEvent]:
        result = await self.call("events")
        return [GameEvent.model_validate(e) for e in result.get("events", [])]

    async def look(self, dyaw_deg: float, dpitch_deg: float) -> None:
        await self.call("look", dyaw_deg=dyaw_deg, dpitch_deg=dpitch_deg)

    async def chat(self, slot: int, text: str) -> None:
        await self.call("chat", slot=slot, text=text)

    async def overview_shot(
        self, position: Vec3 | None, look_at: Vec3 | None, width: int, height: int
    ) -> bytes | None:
        result = await self.call(
            "overview_shot",
            position=list(position) if position else None,
            look_at=list(look_at) if look_at else None,
            width=width,
            height=height,
        )
        data = result.get("png_base64")
        return base64.b64decode(data) if data else None

    async def capture_start(
        self, directory: str, fps: int, width: int, height: int, slots: list[int]
    ) -> None:
        await self.call(
            "capture_start", directory=directory, fps=fps, width=width, height=height, slots=slots
        )

    async def capture_stop(self) -> dict[str, Any]:
        """Returns `frames` (frames written per slot) and `start_time_s` (game time)."""
        return await self.call("capture_stop")

    async def input(self, slot: int, event: dict[str, Any]) -> None:
        await self.call("input", slot=slot, **event)
