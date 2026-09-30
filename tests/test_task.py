from __future__ import annotations

import pytest
from inspect_ai import eval
from inspect_ai.model import get_model

from big_walk_eval.dataset import load_puzzles, puzzle_dataset
from big_walk_eval.episode import EpisodeLog
from big_walk_eval.scripted import Script, ScriptedPolicy, ScriptStep
from big_walk_eval.task import big_walk_coop
from tests.conftest import ROOT

SOLUTION = ROOT / "scripts" / "solutions" / "fake_plate_gate.yaml"


def run_task(tmp_path, policy=None, **task_args):
    model = get_model("mockllm/model", custom_outputs=policy) if policy else "mockllm/model"
    [log] = eval(big_walk_coop(**task_args), model=model, log_dir=str(tmp_path), display="none")
    assert log.status == "success", log.error
    assert log.samples
    return log


def test_puzzle_files_parse():
    ids = {p.id for p in load_puzzles()}
    assert "fake_plate_gate" in ids


def test_dataset_filters():
    ds = puzzle_dataset("fake", n_agents=2)
    assert [s.id for s in ds] == ["fake_plate_gate"]
    assert ds[0].metadata["puzzle"]["spawns"][0]["name"] == "Ash"
    assert [s.id for s in puzzle_dataset("fake", 3, puzzles="fake_plate_gate")] == [
        "fake_plate_gate"
    ]
    with pytest.raises(ValueError):
        puzzle_dataset("fake", n_agents=4)
    with pytest.raises(ValueError):
        puzzle_dataset("fake", n_agents=2, puzzles=["nope"])


def test_scripted_solution_scores_correct(tmp_path):
    log = run_task(tmp_path, ScriptedPolicy(Script.load(SOLUTION)))
    sample = log.samples[0]
    score = sample.scores["gourd_held"]
    assert score.value == "C", score.explanation
    assert score.metadata["gourd_holder"] == "Birch"
    assert score.metadata["ended_by_vote"] is True
    assert score.metadata["false_end"] is False
    assert score.metadata["n_messages"] == 2
    record = sample.store_as(EpisodeLog)
    assert any(e["type"] == "gate_opened" for e in record.events)
    assert log.results.scores[0].metrics["accuracy"].value == 1.0


def test_default_mockllm_ends_by_limit(tmp_path):
    log = run_task(tmp_path, max_turns=4)
    score = log.samples[0].scores["gourd_held"]
    assert score.value == "I"
    assert score.metadata["ended_by_limit"] is True
    assert score.metadata["turns"] == 4


def test_vote_without_gourd_is_false_end(tmp_path):
    vote = ScriptStep(calls=[{"end_episode": {}}])
    log = run_task(tmp_path, ScriptedPolicy({"Ash": [vote], "Birch": [vote]}))
    score = log.samples[0].scores["gourd_held"]
    assert score.value == "I"
    assert score.metadata["false_end"] is True


def test_http_backend_needs_real_puzzles():
    with pytest.raises(ValueError, match="no puzzle matches"):
        big_walk_coop(backend="http", puzzles="fake_plate_gate")
