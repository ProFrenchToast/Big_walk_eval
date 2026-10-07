"""Play back the inputs of a recorded episode, report drift, and make a video.

FakeGame, from an Inspect log:
    uv run python scripts/replay.py logs/scripted/<log>.eval
Real game (game server running), saving one view per act:
    uv run python scripts/replay.py <log>.eval --backend http --frames runs/replay

Every episode stores its recording in the sample store (`EpisodeLog.replay`).
This script sends the same inputs to a fresh game and compares every body
with the recorded checkpoints. FakeGame replays exactly. On the real game,
the drift shows how deterministic the game is under replayed input.

The playback captures every body's view and writes the same video as
scripts/make_video.py makes from a live capture, also for episodes that ran
without capture. Default: <frame folder>/replay.mp4. The game writes the
frames on the machine that runs it, so run this script on that machine.
ffmpeg comes from PATH or from the `video` extra (`uv sync --extra video`).
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

from big_walk_eval.episode import list_samples, read_episode_log
from big_walk_eval.game.client import GameClient
from big_walk_eval.game.fake_game import FakeGame
from big_walk_eval.game.http_game import DEFAULT_URL, HttpGame
from big_walk_eval.protocol import CaptureInfo, CaptureRequest
from big_walk_eval.replay import ActStep, Recording, ResetStep, play, turned_deg
from big_walk_eval.video import Composer, save


def load(log_path: str, sample_id: str | None, epoch: int | None) -> tuple[Recording, dict]:
    try:
        log, task_args = read_episode_log(log_path, sample_id, epoch)
    except ValueError as e:
        raise SystemExit(str(e)) from None
    if log.replay is None:
        raise SystemExit("the sample has no recording")
    return Recording.model_validate(log.replay), task_args


def capture_request(
    recording: Recording, task_args: dict, args: argparse.Namespace
) -> CaptureRequest | None:
    """Capture settings: the flags, else the task's, else the defaults."""
    if args.no_video:
        return None
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    episode_id = re.sub(r"[^A-Za-z0-9_.-]", "_", f"replay_{recording.puzzle_id}_{stamp}")
    fields = {"episode_id": episode_id[:128]}
    for name in ("fps", "width", "height"):
        value = getattr(args, f"capture_{name}") or task_args.get(f"capture_{name}")
        if value:
            fields[name] = int(value)
    return CaptureRequest(**fields)


async def run(
    recording: Recording, game: GameClient, args: argparse.Namespace, capture: CaptureRequest | None
) -> tuple[bool, CaptureInfo | None]:
    if args.frames:
        args.frames.mkdir(parents=True, exist_ok=True)
    worst_m = worst_deg = 0.0
    held_ok = True
    n = 0
    info = None
    recorded_before = {}
    last = None
    for s in recording.steps:
        if isinstance(s, ResetStep):
            last = s.bodies
        elif isinstance(s, ActStep):
            recorded_before[s.seq] = last
            last = s.bodies
    try:
        async for frame in play(recording, game, capture):
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
                worst = max(frame.drift.yaw_deg, key=frame.drift.yaw_deg.get, default=None)
                if worst is not None:
                    line += f" (worst: {recording.agents.get(worst, worst)})"
                want = turned_deg(recorded_before.get(step.seq), step.bodies, step.slot)
                got = turned_deg(frame.before, frame.after, step.slot)
                if want is not None and got is not None:
                    line += f"  turned {got:+.1f} deg, recorded {want:+.1f}"
                if frame.drift.held_differs:
                    line += f"  held differs: slots {frame.drift.held_differs}"
            if args.verbose:
                print(line)
            if args.frames:
                path = args.frames / f"act{n:04d}_turn{step.turn + 1:03d}_{name}.png"
                path.write_bytes(frame.result.screenshot_png)
        final = await game.state()
    finally:
        try:
            if capture is not None:
                info = await game.stop_capture()
        finally:
            await game.close()

    holder = final.reward_holder()
    print(f"replayed {n} acts, {recording.total_game_ms} ms of recorded game time")
    print(f"max drift: {worst_m:.3f} m, {worst_deg:.1f} deg; held items match: {held_ok}")
    print(f"gourd held by: {holder.name if holder else 'nobody'}")
    ok = held_ok and worst_m <= args.tolerance_m and worst_deg <= args.tolerance_deg
    return ok, info


def make_video(info: CaptureInfo, recording: Recording, args: argparse.Namespace) -> bool:
    composer = Composer(info, recording=recording, caption_s=args.caption_s, hold_s=args.hold_s)
    if not composer.directory.is_dir():
        print(f"no video: no frames at {composer.directory}. Run this on the game's machine.")
        return False
    out = args.video or composer.directory / "replay.mp4"
    try:
        print(save(composer, out, args.jpegs))
    except RuntimeError as e:
        print(f"no video: {e}")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("log", help="Inspect log (.eval or .json)")
    parser.add_argument("--sample-id", help="needed if the log has several samples")
    parser.add_argument("--epoch", type=int, help="needed if the sample ran several epochs")
    parser.add_argument("--list", action="store_true", help="list the samples in the log and stop")
    parser.add_argument("--backend", choices=["fake", "http"], default="fake")
    parser.add_argument("--game-url", default=DEFAULT_URL)
    parser.add_argument("--seed", type=int, help="FakeGame seed; default: the task's seed")
    parser.add_argument("--frames", type=Path, help="write the view after each act as PNG here")
    parser.add_argument("--tolerance-m", type=float, default=0.01)
    parser.add_argument("--tolerance-deg", type=float, default=0.5)
    parser.add_argument("--video", type=Path, help="default: <frame folder>/replay.mp4")
    parser.add_argument("--jpegs", type=Path, help="write the video frames here instead of mp4")
    parser.add_argument("--no-video", action="store_true", help="do not capture or make a video")
    parser.add_argument("--capture-fps", type=int, help="default: the task's, else 30")
    parser.add_argument("--capture-width", type=int, help="default: the task's, else 683")
    parser.add_argument("--capture-height", type=int, help="default: the task's, else 384")
    parser.add_argument("--capture-dir", default="captures", help="FakeGame frame folder")
    parser.add_argument("--caption-s", type=float, default=5.0, help="game seconds per message")
    parser.add_argument(
        "--hold-s", type=float, default=0.0, help="freeze the video this long per message"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="print one line per act")
    args = parser.parse_args()
    if args.list:
        for sample_id, epoch, score in list_samples(args.log):
            print(f"{sample_id}  epoch {epoch}  score {score}")
        return 0

    recording, task_args = load(args.log, args.sample_id, args.epoch)
    if args.backend == "fake":
        seed = args.seed if args.seed is not None else int(task_args.get("seed", 0))
        game: GameClient = FakeGame(seed=seed, capture_dir=args.capture_dir)
    else:
        game = HttpGame(args.game_url)
    capture = capture_request(recording, task_args, args)
    ok, info = asyncio.run(run(recording, game, args, capture))
    print("reproduced" if ok else "drifted from the recording")
    if capture is not None:
        if info is None:
            print("no video: the game returned no capture")
            return 1
        if not make_video(info, recording, args):
            return 1
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
