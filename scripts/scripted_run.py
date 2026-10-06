"""Run a fixed solution through the real task and turn loop, with no LLM.

FakeGame:
    uv run python scripts/scripted_run.py scripts/solutions/fake_plate_gate.yaml
Real game (game server running):
    uv run python scripts/scripted_run.py scripts/solutions/<puzzle>.yaml --backend http
FakeGame over HTTP, to test the network path (server: `python -m server.app --fake`):
    uv run python scripts/scripted_run.py scripts/solutions/fake_plate_gate.yaml \
        --backend http --puzzle-game fake

A pass here means the harness, the game server, and the bridge work
together. Only then run agents: a failure with agents is then an agent
failure, not a harness bug.
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

from inspect_ai import eval
from inspect_ai.log import resolve_sample_attachments
from inspect_ai.model import ContentImage, get_model

from big_walk_eval.episode import EpisodeLog
from big_walk_eval.game.http_game import DEFAULT_URL
from big_walk_eval.scripted import Script, ScriptedPolicy
from big_walk_eval.task import big_walk_coop


def _offline_token_count() -> None:
    # mockllm counts tokens with tiktoken, which downloads its encoding on first
    # use. The count means nothing for a scripted run, so skip the download.
    try:
        import inspect_ai.model._model as model_module

        model_module.count_text_tokens = lambda text: len(text) // 4 + 1
    except (ImportError, AttributeError):
        pass


def save_images(sample, out: Path) -> int:
    """Write each turn's first view, then each tool result's view, as turnNNN_<agent>[_KK].png."""
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    turn, agent, k = 0, "unknown", 0
    for message in resolve_sample_attachments(sample).messages:
        meta = message.metadata or {}
        if message.role == "user":
            turn, agent, k = meta.get("turn", turn), meta.get("agent", agent), 0
        elif message.role != "tool":
            continue
        if isinstance(message.content, str):
            continue
        for content in message.content:
            if isinstance(content, ContentImage) and content.image.startswith("data:image/png"):
                data = base64.b64decode(content.image.split(",", 1)[1])
                suffix = f"_{k:02d}" if message.role == "tool" else ""
                (out / f"turn{turn + 1:03d}_{agent}{suffix}.png").write_bytes(data)
                k += message.role == "tool"
                n += 1
    return n


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("solution", type=Path, help="solution YAML (see scripts/solutions/)")
    parser.add_argument("--backend", choices=["fake", "http"], default="fake")
    parser.add_argument("--game-url", default=DEFAULT_URL)
    parser.add_argument(
        "--puzzle-game", choices=["real", "fake"], help="puzzle kind; default follows --backend"
    )
    parser.add_argument("--puzzles-dir", help="puzzle folder, e.g. puzzles/candidates")
    parser.add_argument("--max-turns", type=int)
    parser.add_argument("--max-game-ms-per-turn", type=int, default=3000)
    parser.add_argument("--log-dir", default="logs/scripted")
    parser.add_argument("--save-images", type=Path, help="write each turn's view as PNG here")
    parser.add_argument(
        "--capture", action="store_true", help="record every body's view (scripts/make_video.py)"
    )
    parser.add_argument("--capture-fps", type=int, default=30)
    parser.add_argument("--capture-dir", default="captures", help="FakeGame frame folder")
    args = parser.parse_args()

    _offline_token_count()
    script = Script.load(args.solution)
    task = big_walk_coop(
        backend=args.backend,
        game_url=args.game_url,
        puzzle_game=args.puzzle_game,
        puzzles=script.puzzle,
        puzzles_dir=args.puzzles_dir,
        n_agents=len(script.agents),
        max_turns=args.max_turns,
        max_game_ms_per_turn=args.max_game_ms_per_turn,
        capture=args.capture,
        capture_fps=args.capture_fps,
        capture_dir=args.capture_dir,
    )
    model = get_model("mockllm/model", custom_outputs=ScriptedPolicy(script))
    [log] = eval(task, model=model, log_dir=args.log_dir, display="plain")
    if log.status != "success" or not log.samples:
        print(f"run failed: {log.error}")
        return 1

    sample = log.samples[0]
    score = sample.scores["puzzle_solved"]
    record = sample.store_as(EpisodeLog)
    print(f"\nscore: {score.value}  ({score.explanation})")
    print(f"turns: {record.n_turns}, game time: {record.total_game_ms} ms")
    for event in record.events:
        print(
            f"  turn {event['turn'] + 1} event {event['type']} slot={event['slot']} {event['data']}"
        )
    if args.save_images:
        print(f"saved {save_images(sample, args.save_images)} images to {args.save_images}")
    if record.capture:
        print(f"capture: {record.capture['frames']} frames in {record.capture['directory']}")
    elif record.capture_error:
        print(f"capture failed: {record.capture_error}")
    print(f"log: {log.location}")
    return 0 if score.value == "C" else 2


if __name__ == "__main__":
    sys.exit(main())
