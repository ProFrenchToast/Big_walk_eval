"""Play back the inputs of a recorded episode and report drift from the recording.

FakeGame, from an Inspect log:
    uv run python scripts/replay.py logs/scripted/<log>.eval
Real game (game server running), saving one view per act:
    uv run python scripts/replay.py <log>.eval --backend http --frames runs/replay

Every episode stores its recording in the sample store (`EpisodeLog.replay`).
This script sends the same inputs to a fresh game and compares every body
with the recorded checkpoints. FakeGame replays exactly. On the real game,
the drift shows how deterministic the game is under replayed input.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from big_walk_eval.episode import read_episode_log
from big_walk_eval.game.client import GameClient
from big_walk_eval.game.fake_game import FakeGame
from big_walk_eval.game.http_game import DEFAULT_URL, HttpGame
from big_walk_eval.replay import Recording, play


def load(log_path: str, sample_id: str | None, epoch: int) -> tuple[Recording, dict]:
    log, task_args = read_episode_log(log_path, sample_id, epoch)
    if log.replay is None:
        raise SystemExit(f"sample {sample_id or 'first'} epoch {epoch} has no recording")
    return Recording.model_validate(log.replay), task_args


async def run(recording: Recording, game: GameClient, args: argparse.Namespace) -> bool:
    if args.frames:
        args.frames.mkdir(parents=True, exist_ok=True)
    worst_m = worst_deg = 0.0
    held_ok = True
    n = 0
    try:
        async for frame in play(recording, game, echo_chat=args.echo_chat):
            n += 1
            step = frame.step
            name = recording.agents.get(step.slot, f"slot{step.slot}")
            line = f"act {n:4d} turn {step.turn + 1:3d} {name:<8} {step.used_ms:5d} ms"
            if frame.result.game_ms != step.used_ms:
                line += f" (replay {frame.result.game_ms} ms)"
            if frame.drift is not None:
                worst_m = max(worst_m, frame.drift.max_position_m)
                worst_deg = max(worst_deg, frame.drift.max_yaw_deg)
                held_ok &= not frame.drift.held_differs
                line += (
                    f"  drift {frame.drift.max_position_m:.3f} m {frame.drift.max_yaw_deg:.1f} deg"
                )
                if frame.drift.held_differs:
                    line += f"  held differs: slots {frame.drift.held_differs}"
            if args.verbose:
                print(line)
            if args.frames:
                path = args.frames / f"act{n:04d}_turn{step.turn + 1:03d}_{name}.png"
                path.write_bytes(frame.result.screenshot_png)
        final = await game.state()
    finally:
        await game.close()

    holder = final.reward_holder()
    print(f"replayed {n} acts, {recording.total_game_ms} ms of recorded game time")
    print(f"max drift: {worst_m:.3f} m, {worst_deg:.1f} deg; held items match: {held_ok}")
    print(f"gourd held by: {holder.name if holder else 'nobody'}")
    return held_ok and worst_m <= args.tolerance_m and worst_deg <= args.tolerance_deg


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("log", help="Inspect log (.eval or .json)")
    parser.add_argument("--sample-id", help="default: the first sample")
    parser.add_argument("--epoch", type=int, default=1)
    parser.add_argument("--backend", choices=["fake", "http"], default="fake")
    parser.add_argument("--game-url", default=DEFAULT_URL)
    parser.add_argument("--seed", type=int, help="FakeGame seed; default: the task's seed")
    parser.add_argument("--frames", type=Path, help="write the view after each act as PNG here")
    parser.add_argument("--echo-chat", action="store_true", help="show `say` messages in game")
    parser.add_argument("--tolerance-m", type=float, default=0.01)
    parser.add_argument("--tolerance-deg", type=float, default=0.5)
    parser.add_argument("-v", "--verbose", action="store_true", help="print one line per act")
    args = parser.parse_args()

    recording, task_args = load(args.log, args.sample_id, args.epoch)
    if args.backend == "fake":
        seed = args.seed if args.seed is not None else int(task_args.get("seed", 0))
        game: GameClient = FakeGame(seed=seed)
    else:
        game = HttpGame(args.game_url)
    ok = asyncio.run(run(recording, game, args))
    print("reproduced" if ok else "drifted from the recording")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
