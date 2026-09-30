"""Record every input the agents send to the game, and play a recording back.

`RecordingGame` wraps any `GameClient` and writes each call that changes the
game (reset, switch, act) to a `Recorder`, in order and with the game time at
which it ran. The tools add `say` and vote markers, so a video of the replay
can show the chat. The solver stores the recording in `EpisodeLog.replay`, so
it lives in the Inspect log next to each agent's messages.

Screenshots are not recorded. The Inspect log already has each agent's view,
and a playback renders its own frames.

After each act, `RecordingGame` also reads every body's position (a
checkpoint). A playback compares against these to measure drift. The real
game is probably not deterministic under replayed input, so expect some drift
there; FakeGame replays exactly.
"""

from __future__ import annotations

import math
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field

from big_walk_eval.chat import ChatRecord
from big_walk_eval.game.client import GameClient
from big_walk_eval.protocol import (
    Action,
    ActResult,
    BodyState,
    CaptureInfo,
    CaptureRequest,
    GameEvent,
    GameState,
    HealthResponse,
    ResetRequest,
    Vec3,
    _Wire,
)

RECORDING_VERSION = 1


class _Step(_Wire):
    seq: int = 0
    turn: int = -1
    game_ms: int = 0
    """Total game time of the episode when the step started."""
    wall_s: float = 0.0
    """Seconds since the reset, for a video synced to the real run."""


class ResetStep(_Step):
    kind: Literal["reset"] = "reset"
    request: ResetRequest
    bodies: list[BodyState]


class TurnStep(_Step):
    kind: Literal["turn"] = "turn"
    slot: int
    name: str


class SwitchStep(_Step):
    kind: Literal["switch"] = "switch"
    slot: int


class ActStep(_Step):
    kind: Literal["act"] = "act"
    slot: int
    actions: list[Action]
    budget_ms: int
    used_ms: int = 0
    truncated: bool = False
    events: list[GameEvent] = Field(default_factory=list)
    bodies: list[BodyState] | None = None
    """Checkpoint: every body after the act. None if checkpoints are off or the act failed."""
    error: str | None = None


class CaptureStep(_Step):
    """The game started to record each body's view. Capture frame 0 is at this step's game time."""

    kind: Literal["capture"] = "capture"
    episode_id: str


class SayStep(_Step):
    kind: Literal["say"] = "say"
    slot: int
    text: str
    recipients: list[int]


class VoteStep(_Step):
    kind: Literal["vote"] = "vote"
    slot: int
    vote: bool


class EndStep(_Step):
    kind: Literal["end"] = "end"
    ended_by_vote: bool
    bodies: list[BodyState]


ReplayStep = Annotated[
    ResetStep | TurnStep | SwitchStep | ActStep | CaptureStep | SayStep | VoteStep | EndStep,
    Field(discriminator="kind"),
]


class Recording(_Wire):
    version: int = RECORDING_VERSION
    puzzle_id: str = ""
    agents: dict[int, str] = Field(default_factory=dict)
    backend: str | None = None
    game_version: str | None = None
    started_at: str | None = None
    total_game_ms: int = 0
    steps: list[ReplayStep] = Field(default_factory=list)

    def acts(self) -> list[ActStep]:
        return [s for s in self.steps if isinstance(s, ActStep)]


class Recorder:
    """Collects the steps of one episode in order."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.recording = Recording()
        self.turn = -1
        self._clock = clock
        self._t0 = clock()

    def _add(self, step: _Step) -> None:
        step.seq = len(self.recording.steps)
        step.turn = self.turn
        step.game_ms = self.recording.total_game_ms
        step.wall_s = round(self._clock() - self._t0, 3)
        self.recording.steps.append(step)

    def reset(self, request: ResetRequest, state: GameState, health: HealthResponse) -> None:
        self.recording = Recording(
            puzzle_id=request.puzzle_id,
            agents={b.slot: b.name for b in request.bodies},
            backend=health.backend,
            game_version=health.game_version,
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        self.turn = -1
        self._t0 = self._clock()
        self._add(ResetStep(request=request, bodies=state.bodies))

    def start_turn(self, index: int, slot: int, name: str) -> None:
        self.turn = index
        self._add(TurnStep(slot=slot, name=name))

    def switch(self, slot: int) -> None:
        self._add(SwitchStep(slot=slot))

    def act(
        self,
        slot: int,
        actions: list[Action],
        budget_ms: int,
        result: ActResult | None,
        bodies: list[BodyState] | None,
        error: str | None = None,
    ) -> None:
        step = ActStep(slot=slot, actions=actions, budget_ms=budget_ms, bodies=bodies, error=error)
        if result is not None:
            step.used_ms = result.game_ms
            step.truncated = result.truncated
            step.events = result.events
        self._add(step)
        self.recording.total_game_ms += step.used_ms

    def capture(self, episode_id: str) -> None:
        self._add(CaptureStep(episode_id=episode_id))

    def say(self, record: ChatRecord) -> None:
        self._add(SayStep(slot=record.sender, text=record.text, recipients=record.recipients))

    def vote(self, slot: int, vote: bool) -> None:
        self._add(VoteStep(slot=slot, vote=vote))

    def end(self, ended_by_vote: bool, state: GameState) -> None:
        self._add(EndStep(ended_by_vote=ended_by_vote, bodies=state.bodies))


class RecordingGame:
    """A `GameClient` that passes every call to `inner` and records the ones that change the game.

    With `checkpoints`, each act is followed by one `state()` call to record
    every body. The events that call drains are held back and returned by the
    next `act` or `state`, so the harness still sees every event once.
    """

    def __init__(self, inner: GameClient, recorder: Recorder, checkpoints: bool = True) -> None:
        self.inner = inner
        self.recorder = recorder
        self.checkpoints = checkpoints
        self._held_events: list[GameEvent] = []

    def _with_held(self, events: list[GameEvent]) -> list[GameEvent]:
        out, self._held_events = [*self._held_events, *events], []
        return out

    async def health(self) -> HealthResponse:
        return await self.inner.health()

    async def reset(self, request: ResetRequest) -> GameState:
        health = await self.inner.health()
        state = await self.inner.reset(request)
        self._held_events = []
        self.recorder.reset(request, state, health)
        return state

    async def switch(self, slot: int) -> None:
        await self.inner.switch(slot)
        self.recorder.switch(slot)

    async def screenshot(self) -> bytes:
        return await self.inner.screenshot()

    async def act(self, slot: int, actions: list[Action], budget_ms: int) -> ActResult:
        try:
            result = await self.inner.act(slot, actions, budget_ms)
        except Exception as e:
            self.recorder.act(slot, actions, budget_ms, None, None, f"{type(e).__name__}: {e}")
            raise
        events = self._with_held(result.events)
        bodies = None
        if self.checkpoints:
            checkpoint = await self.inner.state()
            self._held_events = checkpoint.events
            bodies = checkpoint.bodies
        self.recorder.act(slot, actions, budget_ms, result, bodies)
        return result.model_copy(update={"events": events})

    async def state(self) -> GameState:
        state = await self.inner.state()
        return state.model_copy(update={"events": self._with_held(state.events)})

    async def echo_chat(self, slot: int, text: str) -> None:
        await self.inner.echo_chat(slot, text)

    async def overview_shot(
        self, position: Vec3 | None = None, look_at: Vec3 | None = None
    ) -> bytes | None:
        return await self.inner.overview_shot(position, look_at)

    async def start_capture(self, request: CaptureRequest) -> None:
        await self.inner.start_capture(request)
        self.recorder.capture(request.episode_id)

    async def stop_capture(self) -> CaptureInfo | None:
        return await self.inner.stop_capture()

    async def close(self) -> None:
        await self.inner.close()


# ------------------------------------------------------------------ playback


@dataclass
class Drift:
    """How far each body is from its recorded checkpoint."""

    position_m: dict[int, float] = field(default_factory=dict)
    yaw_deg: dict[int, float] = field(default_factory=dict)
    held_differs: list[int] = field(default_factory=list)

    @property
    def max_position_m(self) -> float:
        return max(self.position_m.values(), default=0.0)

    @property
    def max_yaw_deg(self) -> float:
        return max(self.yaw_deg.values(), default=0.0)

    def within(self, position_m: float, yaw_deg: float) -> bool:
        return (
            not self.held_differs
            and self.max_position_m <= position_m
            and self.max_yaw_deg <= yaw_deg
        )


def drift(recorded: list[BodyState], actual: list[BodyState]) -> Drift:
    out = Drift()
    now = {b.slot: b for b in actual}
    for want in recorded:
        got = now.get(want.slot)
        if got is None:
            out.position_m[want.slot] = math.inf
            out.held_differs.append(want.slot)
            continue
        out.position_m[want.slot] = math.dist(want.position, got.position)
        out.yaw_deg[want.slot] = abs((got.yaw_deg - want.yaw_deg + 180.0) % 360.0 - 180.0)
        if sorted((h.hand, h.item_type) for h in want.held) != sorted(
            (h.hand, h.item_type) for h in got.held
        ):
            out.held_differs.append(want.slot)
    return out


@dataclass
class PlaybackFrame:
    step: ActStep
    result: ActResult
    drift: Drift | None


async def play(
    recording: Recording,
    game: GameClient,
    echo_chat: bool = False,
) -> AsyncIterator[PlaybackFrame]:
    """Send the recorded inputs to `game` again. Yield one frame after each act.

    Each frame has the game's screenshot and, if the act has a checkpoint,
    the drift from it. Say steps go to the in-game chat when `echo_chat`.
    """
    if recording.version != RECORDING_VERSION:
        raise ValueError(f"recording version {recording.version}, expected {RECORDING_VERSION}")
    for step in recording.steps:
        match step:
            case ResetStep(request=request):
                await game.reset(request)
            case SwitchStep(slot=slot):
                await game.switch(slot)
            case ActStep():
                result = await game.act(step.slot, step.actions, step.budget_ms)
                d = None
                if step.bodies is not None:
                    d = drift(step.bodies, (await game.state()).bodies)
                yield PlaybackFrame(step, result, d)
            case SayStep(slot=slot, text=text) if echo_chat:
                await game.echo_chat(slot, text)
