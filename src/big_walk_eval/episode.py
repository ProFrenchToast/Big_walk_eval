"""Runtime state of one episode, shared by the solver and the agent tools."""

from __future__ import annotations

from dataclasses import dataclass, field

from inspect_ai.tool import ToolError
from inspect_ai.util import StoreModel
from pydantic import Field

from big_walk_eval.chat import ChatRouter
from big_walk_eval.game.client import GameClient
from big_walk_eval.protocol import PRACTICE_MOD_KEYS, SCREEN_HEIGHT, SCREEN_WIDTH, GameEvent
from big_walk_eval.replay import Recorder

DEFAULT_CHAT_RANGE_M = 20.0


@dataclass(frozen=True)
class EpisodeConfig:
    max_game_ms_per_turn: int = 3000
    max_tool_calls_per_turn: int = 6
    max_generates_per_turn: int = 6
    # None: the puzzle's chat_range_m, else DEFAULT_CHAT_RANGE_M.
    chat_range_m: float | None = None
    hfov_deg: float = 90.0
    keep_images: int = 3
    echo_chat: bool = False
    blocked_keys: frozenset[str] = PRACTICE_MOD_KEYS
    # 0 turns off the per-body video capture.
    capture_fps: int = 0
    capture_width: int = SCREEN_WIDTH // 2
    capture_height: int = SCREEN_HEIGHT // 2


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
    recorder: Recorder = field(default_factory=Recorder)

    def __post_init__(self) -> None:
        range_m = self.config.chat_range_m
        self.chat = ChatRouter(DEFAULT_CHAT_RANGE_M if range_m is None else range_m, self.names)
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
        self.recorder.start_turn(index, slot, self.names[slot])
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
    replay: dict | None = None
    """A `big_walk_eval.replay.Recording`: every input sent to the game, in order."""
    capture: dict | None = None
    """A `CaptureInfo`: where the game wrote each body's video frames."""
    capture_error: str | None = None


def read_episode_log(
    log_path: str, sample_id: str | None = None, epoch: int = 1
) -> tuple[EpisodeLog, dict]:
    """The `EpisodeLog` of one sample in an Inspect log, and the task args.

    Default: the first sample.
    """
    from inspect_ai.log import read_eval_log, read_eval_log_sample, read_eval_log_sample_summaries

    if sample_id is None:
        summaries = read_eval_log_sample_summaries(log_path)
        if not summaries:
            raise ValueError(f"{log_path} has no samples")
        sample_id = str(summaries[0].id)
    sample = read_eval_log_sample(log_path, id=sample_id, epoch=epoch)
    task_args = read_eval_log(log_path, header_only=True).eval.task_args
    return sample.store_as(EpisodeLog), task_args
