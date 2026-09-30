from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from big_walk_eval.game.fake_game import FakeGame
from big_walk_eval.protocol import BodySpawn, ResetRequest

ROOT = Path(__file__).resolve().parents[1]

ASH = BodySpawn(slot=1, name="Ash", position=(-5.0, 0.0, 0.0), yaw_deg=0.0)
BIRCH = BodySpawn(slot=2, name="Birch", position=(0.0, 0.0, 0.0), yaw_deg=0.0)
# Angle from Ash's spawn to the plate at (-8, 4): atan2(-3, 4).
ASH_TO_PLATE_YAW = -36.8699


@pytest.fixture(autouse=True)
def offline_token_count(monkeypatch):
    # mockllm counts tokens with tiktoken, which downloads its encoding on first use.
    # Tests must not need the network.
    monkeypatch.setattr(
        "inspect_ai.model._model.count_text_tokens", lambda text: len(text) // 4 + 1
    )


def reset_request(*bodies: BodySpawn) -> ResetRequest:
    return ResetRequest(puzzle_id="fake_plate_gate", bodies=list(bodies) or [ASH, BIRCH])


@pytest.fixture
async def game() -> FakeGame:
    g = FakeGame(seed=0)
    await g.reset(reset_request())
    return g


@pytest.fixture
def fake_puzzle():
    from big_walk_eval.protocol import PuzzleConfig

    return PuzzleConfig.model_validate(
        yaml.safe_load((ROOT / "puzzles" / "fake_plate_gate.yaml").read_text())
    )
