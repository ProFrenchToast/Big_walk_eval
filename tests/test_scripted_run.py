from __future__ import annotations

import subprocess
import sys

from tests.conftest import ROOT


def test_scripted_run_solves_fake_puzzle(tmp_path):
    images = tmp_path / "images"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/scripted_run.py",
            "scripts/solutions/fake_plate_gate.yaml",
            "--log-dir",
            str(tmp_path / "logs"),
            "--save-images",
            str(images),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "score: C" in result.stdout
    names = sorted(p.name for p in images.iterdir())
    # The turn's first view, then one view per computer tool result.
    assert names[:2] == ["turn001_Ash.png", "turn001_Ash_00.png"]
    assert "turn002_Birch.png" in names
