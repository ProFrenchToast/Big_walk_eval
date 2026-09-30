"""Get the game from the title screen into a hosted walk, through the bridge menu command.

    uv run python -m server.host_walk --save evalwalk --players 2

Opens the save if it exists, else starts a new game with that save name.
The player count picks the puzzle variant; it does not limit the number of bodies.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from typing import Any

from server.bridge_client import BridgeClient, BridgeError


async def menu(bridge: BridgeClient, action: str, **args: Any) -> dict[str, Any]:
    return await bridge.call("menu", action=action, **args)


async def wait_for(
    bridge: BridgeClient, done, timeout_s: float, poll_s: float = 0.5
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while True:
        status = await menu(bridge, "status")
        if done(status):
            return status
        if time.monotonic() > deadline:
            raise TimeoutError(f"menu did not reach the expected state: {status}")
        await asyncio.sleep(poll_s)


def _open(name: str):
    return lambda s: name in s["open_menus"]


async def host_walk(
    bridge: BridgeClient, save: str, players: int = 2, timeout_s: float = 120.0
) -> dict[str, Any]:
    status = await menu(bridge, "status")
    if status["local_player_ready"]:
        return status
    if "title" in status["open_menus"]:
        await menu(bridge, "title_host")
    await wait_for(bridge, _open("host_select"), 15)
    try:
        await menu(bridge, "load_save", name=save)
    except BridgeError:
        await menu(bridge, "new_game")
    await wait_for(bridge, _open("host_confirm"), 15)
    await menu(bridge, "host_confirm", name=save)
    await wait_for(bridge, _open("player_count"), 30)
    await menu(bridge, "player_count", n=players)
    return await wait_for(bridge, lambda s: s["local_player_ready"], timeout_s, poll_s=1.0)


async def _main(save: str, players: int, port: int) -> None:
    bridge = BridgeClient(port=port, timeout_s=30)
    try:
        print(await host_walk(bridge, save, players))
    finally:
        await bridge.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", default="evalwalk")
    parser.add_argument("--players", type=int, default=2, choices=[2, 3, 4])
    parser.add_argument("--bridge-port", type=int, default=47800)
    args = parser.parse_args()
    asyncio.run(_main(args.save, args.players, args.bridge_port))


if __name__ == "__main__":
    main()
