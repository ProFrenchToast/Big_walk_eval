from __future__ import annotations

from typing import Literal

import anyio
from inspect_ai import Task, task

from big_walk_eval.dataset import puzzle_dataset
from big_walk_eval.episode import EpisodeConfig
from big_walk_eval.game.fake_game import FakeGame
from big_walk_eval.game.http_game import DEFAULT_URL, HttpGame
from big_walk_eval.prompts import BIG_WALK_CONTROLS, BIG_WALK_GOURD, FAKE_GAME_CONTROLS
from big_walk_eval.scorer import puzzle_solved
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
    one_response_per_turn: bool = True,
    hfov_deg: float = 90.0,
    keep_images: int = 3,
    capture: bool = False,
    capture_fps: int = 30,
    capture_width: int = 683,
    capture_height: int = 384,
    capture_dir: str = "captures",
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
      max_generates_per_turn: Generate calls per turn, when `one_response_per_turn` is off.
      one_response_per_turn: One reply per turn. Its actions return text only, and the
        agent sees its view only at the start of each turn. Off: each action returns a
        screenshot, and the agent can reply up to `max_generates_per_turn` times.
      hfov_deg: Horizontal field of view for `mouse_move`, if the game does not report it.
      keep_images: Screenshots kept in each agent's history.
      capture: Record video frames from every body's own view while game time runs.
        Make a video with `scripts/make_video.py`.
      capture_fps: Frames per second of game time.
      capture_width: Frame width.
      capture_height: Frame height.
      capture_dir: Where FakeGame writes the frames. The game server uses its own `capture_dir`.
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
        one_response_per_turn=one_response_per_turn,
        hfov_deg=hfov_deg,
        keep_images=keep_images,
        capture_fps=capture_fps if capture else 0,
        capture_width=capture_width,
        capture_height=capture_height,
    )
    return Task(
        dataset=puzzle_dataset(
            puzzle_kind,
            n_agents,
            puzzles=puzzles,
            puzzles_dir=puzzles_dir,
        ),
        solver=round_robin(
            (lambda: FakeGame(seed=seed, capture_dir=capture_dir))
            if fake
            else (lambda: HttpGame(game_url)),
            config,
            controls=FAKE_GAME_CONTROLS if puzzle_kind == "fake" else BIG_WALK_CONTROLS,
            game_name="a simple test game" if puzzle_kind == "fake" else "Big Walk",
            reward_description="" if puzzle_kind == "fake" else BIG_WALK_GOURD,
            max_turns=max_turns,
            # One game instance runs one episode at a time.
            game_lock=None if fake else anyio.Lock(),
        ),
        scorer=puzzle_solved(),
    )
