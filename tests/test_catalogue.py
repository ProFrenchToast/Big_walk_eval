from pathlib import Path

import yaml

from big_walk_eval.dataset import load_puzzles, puzzle_dataset

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "docs" / "puzzle_catalogue.yaml"
CANDIDATES = ROOT / "puzzles" / "candidates"
REASONS = {
    "sound", "simultaneous", "far_apart", "voice_blocked", "solo", "long_wait", "trivial",
    "very_long", "rules_unverified", "no_gourd",
}  # fmt: skip


def _catalogue() -> dict[str, dict]:
    entries = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids))
    return {e["id"]: e for e in entries}


def test_catalogue_entries():
    for e in _catalogue().values():
        assert e["verdict"] in {"run", "maybe", "skip"}
        assert set(e["reasons"]) <= REASONS
        assert e["verdict"] == "run" or e["reasons"], e["id"]
        assert [s["slot"] for s in e["spawns"]] == [1, 2]


def test_candidates_match_catalogue():
    catalogue = _catalogue()
    candidates = load_puzzles(CANDIDATES)
    assert candidates
    for p in candidates:
        entry = catalogue[p.id]
        assert entry["verdict"] == "run"
        assert not p.needs_sound
        assert [list(s.position) for s in p.spawns] == [s["position"] for s in entry["spawns"]]
        assert [prop.position for prop in p.props] == [tuple(entry["gourd"]["home"])]
    runnable = {i for i, e in catalogue.items() if e["verdict"] == "run" and e["gourd"]}
    assert runnable == {p.id for p in candidates}


def test_candidates_are_not_in_the_default_dataset():
    default = {p.id for p in load_puzzles()}
    assert not default & {p.id for p in load_puzzles(CANDIDATES)}
    assert len(puzzle_dataset("real", 2, puzzles_dir=CANDIDATES)) == len(load_puzzles(CANDIDATES))
