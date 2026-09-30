from __future__ import annotations

from typing import Protocol, runtime_checkable

from big_walk_eval.protocol import (
    Action,
    ActResult,
    CaptureInfo,
    CaptureRequest,
    GameState,
    HealthResponse,
    ResetRequest,
    Vec3,
)


@runtime_checkable
class GameClient(Protocol):
    """The only way the harness talks to a game. `HttpGame` and `FakeGame` implement it.

    The game is paused whenever no call to `act` is running.
    """

    async def health(self) -> HealthResponse: ...

    async def reset(self, request: ResetRequest) -> GameState:
        """Load the puzzle snapshot, place one body per spawn, switch to the first, and pause."""
        ...

    async def switch(self, slot: int) -> None:
        """Give control and the camera to `slot`. No game time passes."""
        ...

    async def screenshot(self) -> bytes:
        """PNG of the active body's view, SCREEN_WIDTH x SCREEN_HEIGHT."""
        ...

    async def act(self, slot: int, actions: list[Action], budget_ms: int) -> ActResult:
        """Switch to `slot`, resume, play the actions within `budget_ms` of game time, pause."""
        ...

    async def state(self) -> GameState:
        """Current state. `events` holds the events not yet returned by `act` or `state`."""
        ...

    async def echo_chat(self, slot: int, text: str) -> None:
        """Optional: show a chat message in game, for replays."""
        ...

    async def overview_shot(
        self, position: Vec3 | None = None, look_at: Vec3 | None = None
    ) -> bytes | None:
        """Optional: PNG from a free camera. None if the game cannot do it."""
        ...

    async def start_capture(self, request: CaptureRequest) -> None:
        """Optional: record each body's own view while game time runs. See `CaptureRequest`."""
        ...

    async def stop_capture(self) -> CaptureInfo | None:
        """Stop the capture and finish its files. None if no capture runs."""
        ...

    async def close(self) -> None: ...
