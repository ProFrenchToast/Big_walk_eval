from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import anyio
import pytest

from big_walk_eval.episode import list_samples, read_episode_log
from big_walk_eval.game.fake_game import FakeGame
from big_walk_eval.protocol import HoldKeyAction, LookAction, MouseAction
from big_walk_eval.replay import (
    ActStep,
    EndStep,
    Recorder,
    Recording,
    RecordingGame,
    ResetStep,
    SwitchStep,
    TurnStep,
    VoteStep,
    drift,
    play,
)
from tests.conftest import ASH_TO_PLATE_YAW, ROOT, reset_request
from tests.test_solver import chat, run, step

WALK_TO_PLATE = [LookAction(dyaw_deg=ASH_TO_PLATE_YAW), HoldKeyAction(keys=["w"], duration_ms=2500)]

SOLUTION = {
    "Ash": [
        step(
            ("computer", {"action": "mouse_move", "coordinate": [171, 384]}),
            ("computer", {"action": "hold_key", "text": "w", "duration": 2.5}),
        ),
        step(chat("on the plate")),
        step(("computer", {"action": "screenshot"})),
        step(("end_episode", {})),
    ],
    "Birch": [
        step(("computer", {"action": "hold_key", "text": "w", "duration": 3})),
        step(("computer", {"action": "hold_key", "text": "w", "duration": 3})),
        step(
            ("computer", {"action": "left_mouse_down"}),
            chat("got it"),
            ("end_episode", {}),
        ),
    ],
}


async def collect(recording: Recording, game: FakeGame):
    return [frame async for frame in play(recording, game)]


async def test_recording_game_records_inputs_and_checkpoints():
    recorder = Recorder()
    game = RecordingGame(FakeGame(seed=0), recorder)
    await game.reset(reset_request())
    await game.switch(1)
    result = await game.act(1, WALK_TO_PLATE, 3000)

    rec = recorder.recording
    assert rec.puzzle_id == "fake_plate_gate"
    assert rec.agents == {1: "Ash", 2: "Birch"}
    assert rec.backend == "fake"
    assert [type(s) for s in rec.steps] == [ResetStep, SwitchStep, ActStep]
    act = rec.steps[2]
    assert act.actions == WALK_TO_PLATE
    assert act.used_ms == 2600
    assert act.game_ms == 0
    assert [e.type for e in act.events] == ["plate_pressed", "gate_opened"]
    assert act.bodies == (await game.state()).bodies
    assert rec.total_game_ms == 2600
    assert [e.type for e in result.events] == ["plate_pressed", "gate_opened"]


class LateEventGame(FakeGame):
    """Emits one event outside `act`, as the real bridge can."""

    late = True

    async def state(self):
        if self.late:
            self.late = False
            self._emit("late", None)
        return await super().state()


async def test_checkpoint_does_not_swallow_events():
    game = RecordingGame(LateEventGame(seed=0), Recorder())
    await game.reset(reset_request())
    game.inner.late = True
    result = await game.act(1, [MouseAction(event="click")], 3000)
    assert [e.type for e in result.events] == []
    assert [e.type for e in (await game.state()).events] == ["late"]
    assert (await game.state()).events == []


async def test_failed_act_is_recorded():
    recorder = Recorder()
    game = RecordingGame(FakeGame(seed=0), recorder)
    await game.reset(reset_request())
    with pytest.raises(ValueError):
        await game.act(9, WALK_TO_PLATE, 3000)
    [act] = recorder.recording.acts()
    assert act.error and "slot 9" in act.error
    assert act.bodies is None


def test_episode_recording_replays_exactly(tmp_path, fake_puzzle):
    _, log = run(tmp_path, fake_puzzle, SOLUTION)
    recording = Recording.model_validate(log.replay)

    kinds = [s.kind for s in recording.steps]
    assert kinds[0] == "reset"
    assert kinds[-1] == "end"
    assert kinds.count("act") == 7
    chats = [
        (a.turn, e.slot, e.data["message"])
        for a in recording.acts()
        for e in a.events
        if e.type == "text_chat"
    ]
    assert chats == [(2, 1, "on the plate"), (5, 2, "got it")]
    assert [(s.slot, s.vote) for s in recording.steps if isinstance(s, VoteStep)] == [
        (2, True),
        (1, True),
    ]
    turns = [s for s in recording.steps if isinstance(s, TurnStep)]
    assert [t.turn for t in turns] == list(range(log.n_turns))
    assert [s.seq for s in recording.steps] == list(range(len(recording.steps)))
    game_ms = [s.game_ms for s in recording.steps]
    assert game_ms == sorted(game_ms)
    assert recording.total_game_ms == log.total_game_ms
    end = recording.steps[-1]
    assert isinstance(end, EndStep) and end.ended_by_vote

    game = FakeGame(seed=0)
    frames = anyio.run(collect, recording, game)
    assert len(frames) == 7
    assert all(f.drift is not None and f.drift.within(0.0, 0.0) for f in frames)
    assert drift(end.bodies, anyio.run(game.state).bodies).within(0.0, 0.0)
    assert anyio.run(game.state).reward_holder().name == "Birch"


async def test_playback_detects_drift():
    recorder = Recorder()
    game = RecordingGame(FakeGame(seed=0), recorder)
    await game.reset(reset_request())
    await game.act(1, WALK_TO_PLATE, 3000)
    recording = recorder.recording.model_copy(deep=True)
    act = recording.acts()[0]
    act.actions = [
        LookAction(dyaw_deg=ASH_TO_PLATE_YAW),
        HoldKeyAction(keys=["w"], duration_ms=1000),
    ]

    [frame] = await collect(recording, FakeGame(seed=0))
    assert frame.drift.max_position_m == pytest.approx(3.0)
    assert not frame.drift.within(0.01, 0.5)


def test_replay_script(tmp_path, fake_puzzle):
    run(tmp_path, fake_puzzle, SOLUTION)
    [log_file] = tmp_path.glob("*.eval")
    frames = tmp_path / "frames"
    result = subprocess.run(
        [sys.executable, "scripts/replay.py", str(log_file), "--frames", str(frames), "--no-video"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "reproduced" in result.stdout
    assert "gourd held by: Birch" in result.stdout
    assert len(list(frames.glob("*.png"))) == 7


def two_sample_log(tmp_path, fake_puzzle) -> Path:
    from inspect_ai.log import read_eval_log, write_eval_log

    run(tmp_path, fake_puzzle, SOLUTION)
    [log_file] = tmp_path.glob("*.eval")
    log = read_eval_log(str(log_file))
    [sample] = log.samples
    second = sample.model_copy(update={"id": "second", "epoch": 2}, deep=True)
    second.store["EpisodeLog:puzzle_id"] = "second_puzzle"
    log.samples = [sample, second]
    out = tmp_path / "two.eval"
    write_eval_log(log, str(out))
    return out


def test_read_episode_log_selects_a_sample(tmp_path, fake_puzzle):
    log_file = str(two_sample_log(tmp_path, fake_puzzle))
    assert [(i, e) for i, e, _ in list_samples(log_file)][1] == ("second", 2)
    assert read_episode_log(log_file, "second")[0].puzzle_id == "second_puzzle"
    assert read_episode_log(log_file, epoch=2)[0].puzzle_id == "second_puzzle"
    assert read_episode_log(log_file, epoch=1)[0].puzzle_id == "fake_plate_gate"
    with pytest.raises(ValueError, match="several samples"):
        read_episode_log(log_file)
    with pytest.raises(ValueError, match="no sample matches"):
        read_episode_log(log_file, "missing")


def test_replay_script_selects_a_sample(tmp_path, fake_puzzle):
    log_file = str(two_sample_log(tmp_path, fake_puzzle))
    cmd = [sys.executable, "scripts/replay.py", log_file, "--no-video"]

    listed = subprocess.run([*cmd, "--list"], cwd=ROOT, capture_output=True, text=True)
    assert listed.returncode == 0 and "second  epoch 2" in listed.stdout
    ambiguous = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    assert ambiguous.returncode != 0 and "several samples" in ambiguous.stderr
    chosen = subprocess.run(
        [*cmd, "--sample-id", "second"], cwd=ROOT, capture_output=True, text=True
    )
    assert chosen.returncode == 0, chosen.stdout + chosen.stderr
    assert "reproduced" in chosen.stdout
