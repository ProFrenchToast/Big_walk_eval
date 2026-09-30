"""Print a puzzle `spawns:` block from the bodies' current positions.

Place the bodies in the game with the practice mod, then run:
    uv run python -m server.record_spawns --names Ash,Birch
and paste the output into puzzles/<id>.yaml.
"""

from __future__ import annotations

import argparse
import asyncio

from big_walk_eval.game.http_game import DEFAULT_URL, HttpGame
from big_walk_eval.protocol import GameState


def spawns_yaml(state: GameState, names: list[str] | None = None) -> str:
    lines = ["spawns:"]
    for i, body in enumerate(sorted(state.bodies, key=lambda b: b.slot)):
        name = names[i] if names and i < len(names) else body.name
        x, y, z = body.position
        lines.append(
            f"  - {{slot: {body.slot}, name: {name}, "
            f"position: [{x:.2f}, {y:.2f}, {z:.2f}], yaw_deg: {body.yaw_deg:.1f}}}"
        )
    return "\n".join(lines)


async def _main(url: str, names: list[str] | None) -> None:
    game = HttpGame(url)
    try:
        print(spawns_yaml(await game.state(), names))
    finally:
        await game.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--names", help="comma-separated names, in slot order")
    args = parser.parse_args()
    asyncio.run(_main(args.url, args.names.split(",") if args.names else None))


if __name__ == "__main__":
    main()
