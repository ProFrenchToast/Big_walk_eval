from __future__ import annotations

import subprocess
import sys

import pytest
from PIL import Image

from big_walk_eval.episode import EpisodeConfig
from big_walk_eval.game.fake_game import FakeGame
from big_walk_eval.protocol import (
    CaptureInfo,
    CaptureRequest,
    GameEvent,
    HoldKeyAction,
    WaitAction,
)
from big_walk_eval.replay import (
    ActStep,
    CaptureStep,
    Recording,
    ResetStep,
)
from big_walk_eval.video import ACTIVE, HEADER_H, IDLE, Composer, find_ffmpeg, write_mp4
from tests.conftest import ROOT, reset_request
from tests.test_replay import SOLUTION
from tests.test_solver import run


def frame(capture_dir, episode: str, slot: int, index: int) -> bytes:
    return (capture_dir / episode / f"slot{slot}" / f"{index:06d}.jpg").read_bytes()


async def test_fake_game_captures_every_body_per_game_time_step(tmp_path):
    game = FakeGame(seed=0, capture_dir=tmp_path)
    await game.reset(reset_request())
    await game.start_capture(CaptureRequest(episode_id="ep", fps=10, width=64, height=36))
    await game.act(1, [HoldKeyAction(keys=["w"], duration_ms=1000)], 3000)
    await game.act(2, [WaitAction(duration_ms=200)], 3000)
    info = await game.stop_capture()

    assert info.frames == 13
    assert info.slots == {1: "Ash", 2: "Birch"}
    assert CaptureInfo.model_validate_json((tmp_path / "ep" / "capture.json").read_text()) == info
    for slot in (1, 2):
        files = sorted((tmp_path / "ep" / f"slot{slot}").iterdir())
        assert [f.name for f in files] == [f"{i:06d}.jpg" for i in range(13)]
        assert Image.open(files[0]).size == (64, 36)
    # Ash walks, so its view changes. Birch stands still and Ash is out of its view.
    assert frame(tmp_path, "ep", 1, 0) != frame(tmp_path, "ep", 1, 10)
    assert frame(tmp_path, "ep", 2, 0) == frame(tmp_path, "ep", 2, 10)
    assert await game.stop_capture() is None


async def test_capture_rejects_unknown_slot(tmp_path):
    game = FakeGame(seed=0, capture_dir=tmp_path)
    await game.reset(reset_request())
    with pytest.raises(ValueError, match="slot 7"):
        await game.start_capture(CaptureRequest(episode_id="ep", slots=[7]))
    with pytest.raises(ValueError):
        CaptureRequest(episode_id="../escape")


def captured_episode(tmp_path, puzzle):
    config = EpisodeConfig(capture_fps=5, capture_width=64, capture_height=36)
    _, log = run(
        tmp_path,
        puzzle,
        SOLUTION,
        config=config,
        game_factory=lambda: FakeGame(seed=0, capture_dir=tmp_path / "captures"),
    )
    return log


def test_episode_capture(tmp_path, fake_puzzle):
    log = captured_episode(tmp_path, fake_puzzle)
    assert log.capture_error is None
    info = CaptureInfo.model_validate(log.capture)
    assert info.episode_id.startswith("fake_plate_gate_")
    assert info.frames == log.total_game_ms * 5 // 1000 + 1
    assert info.width == 64
    recording = Recording.model_validate(log.replay)
    kinds = [s.kind for s in recording.steps]
    assert kinds.index("capture") < kinds.index("act")
    capture = next(s for s in recording.steps if isinstance(s, CaptureStep))
    assert capture.episode_id == info.episode_id

    composer = Composer(info, recording=recording, hold_s=1.0)
    sequence = list(composer.sequence())
    assert len(sequence) == info.frames + 2 * 5
    assert [f.index for f in sequence] == sorted(f.index for f in sequence)
    image = composer.render(sequence[0])
    assert image.size == composer.size

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        pytest.skip("no ffmpeg")
    out = tmp_path / "episode.mp4"
    assert write_mp4(composer, out, ffmpeg) == len(sequence)
    assert out.stat().st_size > 1000


def synthetic(tmp_path) -> tuple[CaptureInfo, Recording]:
    info = CaptureInfo(
        episode_id="ep",
        directory=str(tmp_path),
        fps=10,
        width=40,
        height=30,
        slots={1: "Ash", 2: "Birch", 3: "Cedar"},
        frames=10,
    )
    for slot in info.slots:
        (tmp_path / f"slot{slot}").mkdir()
        for k in range(info.frames):
            Image.new("RGB", (40, 30), (slot * 60, k * 20, 0)).save(
                tmp_path / f"slot{slot}" / f"{k:06d}.jpg"
            )
    reset = ResetStep.model_validate(
        {"request": {"puzzle_id": "p", "bodies": []}, "bodies": [], "game_ms": 0}
    )
    recording = Recording(
        agents=info.slots,
        steps=[
            reset,
            CaptureStep(episode_id="ep", game_ms=0),
            ActStep(
                slot=1,
                actions=[],
                budget_ms=3000,
                used_ms=500,
                game_ms=0,
                turn=0,
                events=[GameEvent(type="text_chat", slot=1, data={"message": "hello from Ash"})],
            ),
            ActStep(slot=2, actions=[], budget_ms=3000, used_ms=400, game_ms=500, turn=1),
        ],
    )
    return info, recording


def test_composer_highlights_the_acting_body_and_captions_the_speaker(tmp_path):
    info, recording = synthetic(tmp_path)
    composer = Composer(info, recording=recording, hold_s=0.5)
    assert composer.cols == 2 and composer.rows == 2
    sequence = list(composer.sequence())
    assert len(sequence) == 10 + 5
    held = [f for f in sequence if f.index == 5]
    assert len(held) == 6 and all(f.game_ms == 500 for f in held)

    assert composer.act_at(100).slot == 1
    assert composer.act_at(600).slot == 2
    assert composer.act_at(950) is None
    assert [c.text for c in composer.captions_at(1, 600)] == ["hello from Ash"]
    assert [c.speaker for c in composer.captions_at(1, 600)] == ["Ash"]
    assert composer.captions_at(2, 600) == []
    assert composer.captions_at(1, 400) == []

    image = composer.render(sequence[0])
    assert image.getpixel((1, HEADER_H + 1)) == ACTIVE
    assert image.getpixel((41, HEADER_H + 1)) == IDLE

    only_birch = Composer(info, recording=recording, slots=[2])
    assert only_birch.size == (40, HEADER_H + 30)
    with pytest.raises(ValueError, match="slots"):
        Composer(info, slots=[9])


def test_composer_uses_capture_start_offset(tmp_path):
    info, recording = synthetic(tmp_path)
    for step in recording.steps[1:]:
        step.game_ms += 1000
    composer = Composer(info, recording=recording)
    assert composer.act_at(100).slot == 1
    assert composer.captions[0].game_ms == 500


def test_composer_fills_missing_frames(tmp_path):
    info, _ = synthetic(tmp_path)
    (tmp_path / "slot1" / "000003.jpg").unlink()
    composer = Composer(info)
    assert composer.tile(1, 2).getpixel((5, 5)) == composer.tile(1, 3).getpixel((5, 5))


def test_make_video_script(tmp_path, fake_puzzle):
    captured_episode(tmp_path, fake_puzzle)
    [log_file] = tmp_path.glob("*.eval")
    jpegs = tmp_path / "composed"
    result = subprocess.run(
        [sys.executable, "scripts/make_video.py", str(log_file), "--jpegs", str(jpegs)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(list(jpegs.glob("*.jpg"))) > 0
