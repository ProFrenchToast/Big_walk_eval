"""Make one video of an episode from every agent's own view.

    uv run python scripts/scripted_run.py scripts/solutions/fake_plate_gate.yaml --capture
    uv run python scripts/make_video.py logs/scripted/<log>.eval

The episode must run with `-T capture=true`. The game writes the frames on
the machine that runs it. If you copied them to another folder, give that
folder with --capture-dir. ffmpeg comes from PATH or from the `video` extra
(`uv sync --extra video`). Without ffmpeg, use --jpegs to write the frames.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from big_walk_eval.episode import list_samples, read_episode_log
from big_walk_eval.protocol import CaptureInfo
from big_walk_eval.replay import Recording
from big_walk_eval.video import Composer, save


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("log", help="Inspect log (.eval or .json)")
    parser.add_argument("--sample-id", help="needed if the log has several samples")
    parser.add_argument("--epoch", type=int, help="needed if the sample ran several epochs")
    parser.add_argument("--list", action="store_true", help="list the samples in the log and stop")
    parser.add_argument("--capture-dir", type=Path, help="episode frame folder, if moved")
    parser.add_argument("--slots", help="comma-separated slots to show; default: all")
    parser.add_argument("--out", type=Path, help="default: <frame folder>/episode.mp4")
    parser.add_argument("--jpegs", type=Path, help="write composed frames here instead of mp4")
    parser.add_argument("--caption-s", type=float, default=5.0, help="game seconds per message")
    parser.add_argument("--hold-s", type=float, default=2.0, help="video pause per message")
    args = parser.parse_args()
    if args.list:
        for sample_id, epoch, score in list_samples(args.log):
            print(f"{sample_id}  epoch {epoch}  score {score}")
        return 0

    try:
        log, _ = read_episode_log(args.log, args.sample_id, args.epoch)
    except ValueError as e:
        print(e)
        return 1
    if log.capture is None:
        detail = f": {log.capture_error}" if log.capture_error else ""
        print(f"the episode has no capture{detail}. Run it with -T capture=true.")
        return 1
    info = CaptureInfo.model_validate(log.capture)
    recording = Recording.model_validate(log.replay) if log.replay else None
    slots = [int(s) for s in args.slots.split(",")] if args.slots else None
    composer = Composer(
        info,
        directory=args.capture_dir,
        recording=recording,
        slots=slots,
        caption_s=args.caption_s,
        hold_s=args.hold_s,
    )
    if not composer.directory.is_dir():
        print(f"no frames at {composer.directory}. Copy them here or give --capture-dir.")
        return 1

    try:
        print(save(composer, args.out, args.jpegs))
    except RuntimeError as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
