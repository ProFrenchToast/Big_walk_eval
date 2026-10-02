"""`GameClient` for the game server on the Windows machine."""

from __future__ import annotations

from typing import TypeVar

import httpx
from pydantic import BaseModel

from big_walk_eval.protocol import (
    Action,
    ActRequest,
    ActResult,
    CaptureInfo,
    CaptureRequest,
    CaptureStopResponse,
    GameState,
    HealthResponse,
    OkResponse,
    OverviewRequest,
    ResetRequest,
    ScreenshotResponse,
    SwitchRequest,
    Vec3,
)

DEFAULT_URL = "http://127.0.0.1:47801"
M = TypeVar("M", bound=BaseModel)


class GameServerError(RuntimeError):
    pass


class HttpGame:
    def __init__(
        self,
        base_url: str = DEFAULT_URL,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s, transport=transport)

    async def _call(
        self, method: str, path: str, response: type[M], body: BaseModel | None = None
    ) -> M:
        resp = await self._client.request(
            method,
            path,
            content=body.model_dump_json() if body is not None else None,
            headers={"content-type": "application/json"} if body is not None else None,
        )
        if resp.status_code >= 400:
            raise GameServerError(f"{method} {path} -> {resp.status_code}: {resp.text}")
        return response.model_validate_json(resp.content)

    async def health(self) -> HealthResponse:
        return await self._call("GET", "/health", HealthResponse)

    async def reset(self, request: ResetRequest) -> GameState:
        return await self._call("POST", "/reset", GameState, request)

    async def switch(self, slot: int) -> None:
        await self._call("POST", "/switch", OkResponse, SwitchRequest(slot=slot))

    async def screenshot(self) -> bytes:
        shot = await self._call("GET", "/screenshot", ScreenshotResponse)
        if shot.png is None:
            raise GameServerError("the server returned no screenshot")
        return shot.png

    async def act(self, slot: int, actions: list[Action], budget_ms: int) -> ActResult:
        request = ActRequest(slot=slot, actions=actions, budget_ms=budget_ms)
        return await self._call("POST", "/act", ActResult, request)

    async def state(self) -> GameState:
        return await self._call("GET", "/state", GameState)

    async def overview_shot(
        self, position: Vec3 | None = None, look_at: Vec3 | None = None
    ) -> bytes | None:
        request = OverviewRequest(position=position, look_at=look_at)
        shot = await self._call("POST", "/overview_shot", ScreenshotResponse, request)
        return shot.png

    async def start_capture(self, request: CaptureRequest) -> None:
        await self._call("POST", "/capture/start", OkResponse, request)

    async def stop_capture(self) -> CaptureInfo | None:
        return (await self._call("POST", "/capture/stop", CaptureStopResponse)).info

    async def close(self) -> None:
        await self._client.aclose()
