"""puzzles/*.yaml -> Inspect samples."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from inspect_ai.dataset import MemoryDataset, Sample

from big_walk_eval.protocol import PuzzleConfig

PUZZLES_DIR = Path(__file__).resolve().parents[2] / "puzzles"


def load_puzzles(puzzles_dir: str | Path | None = None) -> list[PuzzleConfig]:
    root = Path(puzzles_dir) if puzzles_dir else PUZZLES_DIR
    return [
        PuzzleConfig.model_validate(yaml.safe_load(path.read_text()))
        for path in sorted(root.glob("*.yaml"))
    ]


def puzzle_dataset(
    game: Literal["real", "fake"],
    n_agents: int,
    puzzles: str | list[str] = "all",
    puzzles_dir: str | Path | None = None,
) -> MemoryDataset:
    wanted = None if puzzles == "all" else _as_list(puzzles)
    samples = []
    for p in load_puzzles(puzzles_dir):
        if wanted is not None and p.id not in wanted:
            continue
        if p.game != game or p.needs_sound:
            continue
        if not p.min_agents <= n_agents <= len(p.spawns):
            continue
        samples.append(
            Sample(
                id=p.id,
                input=f"Solve the puzzle: {p.title}",
                target="a player holds the gourd",
                metadata={
                    "puzzle": p.model_dump(mode="json"),
                    "n_agents": n_agents,
                    "title": p.title,
                    "area": p.area,
                    "location_hint": p.location_hint,
                },
            )
        )
    if not samples:
        raise ValueError(
            f"no puzzle matches game={game!r}, n_agents={n_agents}, puzzles={puzzles!r}"
        )
    return MemoryDataset(samples, name=f"big_walk_{game}")


def _as_list(puzzles: str | list[str]) -> list[str]:
    if isinstance(puzzles, str):
        return [p.strip() for p in puzzles.split(",") if p.strip()]
    return list(puzzles)
