from __future__ import annotations

from typing import Literal

import anyio
from inspect_ai import Task, task

from big_walk_eval.dataset import puzzle_dataset
from big_walk_eval.episode import EpisodeConfig
from big_walk_eval.game.fake_game import FakeGame
from big_walk_eval.game.http_game import DEFAULT_URL, HttpGame
from big_walk_eval.prompts import BIG_WALK_CONTROLS, FAKE_GAME_CONTROLS
from big_walk_eval.scorer import gourd_held
from big_walk_eval.solver import round_robin


@task
def big_walk_coop(
    backend: Literal["fake", "http"] = "fake",
    game_url: str = DEFAULT_URL,
    puzzles: str | list[str] = "all",
    n_agents: int = 2,
    max_turns: int | None = None,
    max_game_ms_per_turn: int = 3000,
    max_tool_calls_per_turn: int = 6,
    max_generates_per_turn: int = 6,
    chat_range_m: float = 20.0,
    hfov_deg: float = 90.0,
    keep_images: int = 3,
    echo_chat: bool = False,
    seed: int = 0,
    puzzles_dir: str | None = None,
    puzzle_game: Literal["real", "fake"] | None = None,
) -> Task:
    """LLM agents cooperate to solve a Big Walk puzzle. Each agent controls one body.

    Args:
      backend: "fake" runs FakeGame in process. "http" talks to the game server.
      game_url: Game server URL, for backend="http".
      puzzles: "all", or puzzle IDs as a list or a comma-separated string.
      n_agents: Number of agents, one body each.
      max_turns: Turn limit for all puzzles. Default: each puzzle's `max_turns`.
      max_game_ms_per_turn: Unpaused game time per turn.
      max_tool_calls_per_turn: Tool calls per turn.
      max_generates_per_turn: Generate calls per turn. 1 gives one reply per turn.
      chat_range_m: Distance within which `say` is heard.
      hfov_deg: Horizontal field of view for `mouse_move`, if the game does not report it.
      keep_images: Screenshots kept in each agent's history.
      echo_chat: Also show `say` messages in game, for replays.
      seed: FakeGame seed.
      puzzles_dir: Directory with puzzle YAML files. Default: `puzzles/` in the repo.
      puzzle_game: Which puzzles to load. Default: "fake" for backend="fake", else "real".
        Set "fake" with backend="http" to run FakeGame puzzles on a server started with --fake.
    """
    fake = backend == "fake"
    if not fake and backend != "http":
        raise ValueError(f"backend must be 'fake' or 'http', got {backend!r}")
    puzzle_kind = puzzle_game or ("fake" if fake else "real")
    config = EpisodeConfig(
        max_game_ms_per_turn=max_game_ms_per_turn,
        max_tool_calls_per_turn=max_tool_calls_per_turn,
        max_generates_per_turn=max_generates_per_turn,
        chat_range_m=chat_range_m,
        hfov_deg=hfov_deg,
        keep_images=keep_images,
        echo_chat=echo_chat,
    )
    return Task(
        dataset=puzzle_dataset(
            puzzle_kind,
            n_agents,
            puzzles=puzzles,
            puzzles_dir=puzzles_dir,
        ),
        solver=round_robin(
            (lambda: FakeGame(seed=seed)) if fake else (lambda: HttpGame(game_url)),
            config,
            controls=FAKE_GAME_CONTROLS if puzzle_kind == "fake" else BIG_WALK_CONTROLS,
            game_name="a simple test game" if puzzle_kind == "fake" else "Big Walk",
            max_turns=max_turns,
            # One game instance runs one episode at a time.
            game_lock=None if fake else anyio.Lock(),
        ),
        scorer=gourd_held(),
    )
