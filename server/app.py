"""Game server: HTTP JSON API in front of one `GameClient`.

    uv run --extra server python -m server.app --fake              # FakeGame, any OS
    uv run --extra server python -m server.app --config server.yaml  # real game, Windows

Binds to 127.0.0.1. Reach it from another machine through an SSH tunnel.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, ValidationError

from big_walk_eval.game.client import GameClient
from big_walk_eval.protocol import (
    ActRequest,
    ChatEchoRequest,
    OkResponse,
    OverviewRequest,
    ResetRequest,
    ScreenshotResponse,
    SwitchRequest,
)

logger = logging.getLogger(__name__)
M = TypeVar("M", bound=BaseModel)


def _json(model: BaseModel, status: int = 200) -> Response:
    return Response(model.model_dump_json(), status_code=status, media_type="application/json")


def _error(status: int, message: str) -> Response:
    return Response(
        json.dumps({"detail": message}), status_code=status, media_type="application/json"
    )


def create_app(game: GameClient) -> FastAPI:
    app = FastAPI(title="Big Walk game server")
    lock = asyncio.Lock()

    async def run(fn: Callable[[], Awaitable[BaseModel]]) -> Response:
        # One call at a time touches the game and the input.
        async with lock:
            try:
                return _json(await fn())
            except (ValueError, KeyError, ValidationError) as e:
                return _error(400, str(e))
            except Exception as e:
                logger.exception("game call failed")
                return _error(500, f"{type(e).__name__}: {e}")

    async def body(request: Request, model: type[M]) -> M:
        return model.model_validate_json(await request.body())

    @app.get("/health")
    async def health() -> Response:
        return await run(game.health)

    @app.post("/reset")
    async def reset(request: Request) -> Response:
        async def call():
            return await game.reset(await body(request, ResetRequest))

        return await run(call)

    @app.post("/switch")
    async def switch(request: Request) -> Response:
        async def call():
            await game.switch((await body(request, SwitchRequest)).slot)
            return OkResponse()

        return await run(call)

    @app.get("/screenshot")
    async def screenshot() -> Response:
        async def call():
            return ScreenshotResponse(png=await game.screenshot())

        return await run(call)

    @app.post("/act")
    async def act(request: Request) -> Response:
        async def call():
            req = await body(request, ActRequest)
            return await game.act(req.slot, req.actions, req.budget_ms)

        return await run(call)

    @app.get("/state")
    async def state() -> Response:
        return await run(game.state)

    @app.post("/chat_echo")
    async def chat_echo(request: Request) -> Response:
        async def call():
            req = await body(request, ChatEchoRequest)
            await game.echo_chat(req.slot, req.text)
            return OkResponse()

        return await run(call)

    @app.post("/overview_shot")
    async def overview_shot(request: Request) -> Response:
        async def call():
            req = await body(request, OverviewRequest)
            return ScreenshotResponse(png=await game.overview_shot(req.position, req.look_at))

        return await run(call)

    return app


def main() -> None:
    import uvicorn

    from server.config import ServerConfig

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="server YAML config (see server/config.example.yaml)")
    parser.add_argument("--fake", action="store_true", help="serve FakeGame instead of the game")
    parser.add_argument("--seed", type=int, default=0, help="FakeGame seed")
    parser.add_argument("--host", help="override the bind address")
    parser.add_argument("--port", type=int, help="override the port")
    args = parser.parse_args()
    config = ServerConfig.load(args.config)
    if args.fake:
        from big_walk_eval.game.fake_game import FakeGame

        game: GameClient = FakeGame(seed=args.seed)
    else:
        from server.bridge_game import make_bridge_game

        game = make_bridge_game(config)
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(game), host=args.host or config.host, port=args.port or config.port)


if __name__ == "__main__":
    main()
