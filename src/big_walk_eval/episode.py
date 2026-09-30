"""Runtime state of one episode, shared by the solver and the agent tools."""

from __future__ import annotations

from dataclasses import dataclass, field

from inspect_ai.tool import ToolError
from inspect_ai.util import StoreModel
from pydantic import Field

from big_walk_eval.chat import ChatRouter
from big_walk_eval.game.client import GameClient
from big_walk_eval.protocol import PRACTICE_MOD_KEYS, GameEvent


@dataclass(frozen=True)
class EpisodeConfig:
    max_game_ms_per_turn: int = 3000
    max_tool_calls_per_turn: int = 6
    max_generates_per_turn: int = 6
    chat_range_m: float = 20.0
    hfov_deg: float = 90.0
    keep_images: int = 3
    echo_chat: bool = False
    blocked_keys: frozenset[str] = PRACTICE_MOD_KEYS


@dataclass
class TurnState:
    index: int
    slot: int
    max_game_ms: int
    max_tool_calls: int
    game_ms: int = 0
    tool_calls: int = 0
    truncated: bool = False

    @property
    def remaining_ms(self) -> int:
        return max(0, self.max_game_ms - self.game_ms)

    @property
    def done(self) -> bool:
        return self.tool_calls >= self.max_tool_calls or self.remaining_ms == 0


@dataclass
class EventRecord:
    turn: int
    event: GameEvent


@dataclass
class Episode:
    game: GameClient
    config: EpisodeConfig
    names: dict[int, str]
    chat: ChatRouter = field(init=False)
    hfov_deg: float = field(init=False)
    votes: dict[int, bool] = field(init=False)
    turn: TurnState | None = None
    total_game_ms: int = 0
    events: list[EventRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.chat = ChatRouter(self.config.chat_range_m, self.names)
        self.hfov_deg = self.config.hfov_deg
        self.votes = {slot: False for slot in self.names}

    @property
    def all_voted(self) -> bool:
        return all(self.votes.values())

    def start_turn(self, index: int, slot: int) -> TurnState:
        self.turn = TurnState(
            index=index,
            slot=slot,
            max_game_ms=self.config.max_game_ms_per_turn,
            max_tool_calls=self.config.max_tool_calls_per_turn,
        )
        return self.turn

    def begin_tool_call(self, slot: int) -> TurnState:
        """Count one tool call against the turn. Raise a ToolError past the limit."""
        turn = self.turn
        if turn is None or turn.slot != slot:
            raise ToolError("It is not your turn.")
        if turn.tool_calls >= turn.max_tool_calls:
            raise ToolError(
                f"You have used all {turn.max_tool_calls} actions for this turn. "
                "This action did not run."
            )
        turn.tool_calls += 1
        return turn

    def add_game_time(self, ms: int, truncated: bool) -> None:
        if self.turn is not None:
            self.turn.game_ms += ms
            self.turn.truncated |= truncated
        self.total_game_ms += ms

    def record_events(self, events: list[GameEvent]) -> None:
        index = self.turn.index if self.turn else -1
        self.events.extend(EventRecord(index, e) for e in events)


class EpisodeLog(StoreModel):
    """Per-sample record in the sample store. The scorer reads it."""

    puzzle_id: str = ""
    agents: dict[str, str] = Field(default_factory=dict)
    votes: dict[str, bool] = Field(default_factory=dict)
    chat: list[dict] = Field(default_factory=list)
    turns: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    total_game_ms: int = 0
    n_turns: int = 0
    ended_by_vote: bool = False
    final_state: dict | None = None
