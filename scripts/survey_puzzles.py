"""Survey the puzzles in the running game, and check the catalogue's spawns.

    uv run python scripts/survey_puzzles.py dump runs/survey.json
    uv run python scripts/survey_puzzles.py check-spawns [--only labyrinth,fielding]

`dump` writes every reward gourd, designer teleport point, puzzle mechanism, and a
profile of each puzzle root (component counts, switch, prop home and prop positions),
as the bridge commands `survey` and `puzzle_roots` report them. Use it to refresh
docs/puzzle_catalogue.yaml after a game update. Keep the output out of the repo.

`check-spawns` teleports two bodies to each catalogue entry's spawns, lets the game
run, and prints how far each body moved. A body that moves more than 0.3 m, or drops,
needs a new spawn. It sends no mouse or keyboard input, but it moves the bodies.

Both need the game with the bridge, hosting a walk (`python -m server.host_walk`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.bridge_client import BridgeClient  # noqa: E402

CATALOGUE = Path(__file__).resolve().parents[1] / "docs" / "puzzle_catalogue.yaml"
PUZZLE_PARENTS = ["LandmarksPlayerCountAny", "Contents"]
SETTLE_S = 1.6


async def dump(bridge: BridgeClient, out: Path) -> None:
    survey = await bridge.call("survey")
    survey["puzzle_roots"] = (await bridge.call("puzzle_roots", parents=PUZZLE_PARENTS))["roots"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(survey, indent=1))
    print(
        f"{len(survey['gourds'])} gourds, {len(survey['teleport_points'])} teleport points, "
        f"{len(survey['puzzle_roots'])} puzzle roots -> {out}"
    )


async def _place(bridge: BridgeClient, slot: int, position: list[float], yaw: float) -> None:
    # A teleport sticks only for the local body, and only if the game then runs.
    await bridge.switch_slot(slot)
    await bridge.teleport(slot, tuple(position), yaw)
    await bridge.resume()
    await asyncio.sleep(SETTLE_S)
    await bridge.pause()


async def check_spawns(bridge: BridgeClient, only: set[str] | None) -> int:
    entries = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    await bridge.pause()
    if len((await bridge.get_state()).bodies) < 2:
        await bridge.spawn_bodies(2)
    bad = 0
    for entry in entries:
        if only and entry["id"] not in only:
            continue
        for spawn in entry["spawns"]:
            await _place(bridge, spawn["slot"], spawn["position"], spawn["yaw_deg"])
        bodies = {b.slot: b for b in (await bridge.get_state()).bodies}
        report = []
        for spawn in entry["spawns"]:
            got, want = bodies[spawn["slot"]].position, spawn["position"]
            moved = math.dist((got[0], got[2]), (want[0], want[2]))
            drop = want[1] - got[1]
            ok = moved < 0.3 and drop < 0.3
            bad += not ok
            mark = "" if ok else " BAD"
            report.append(f"{spawn['name']} moved {moved:.2f} m, dropped {drop:.2f} m{mark}")
        print(f"{entry['id']:24} " + "; ".join(report), flush=True)
    return bad


async def _main(args: argparse.Namespace) -> int:
    bridge = BridgeClient(port=args.bridge_port, timeout_s=120)
    try:
        if args.command == "dump":
            await dump(bridge, Path(args.out))
            return 0
        only = set(args.only.split(",")) if args.only else None
        return 1 if await check_spawns(bridge, only) else 0
    finally:
        await bridge.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--bridge-port", type=int, default=47800)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("dump").add_argument("out")
    sub.add_parser("check-spawns").add_argument("--only", default="")
    sys.exit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
