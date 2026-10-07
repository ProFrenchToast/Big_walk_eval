"""Read or set the bridge's capture switches while the game runs (no restart).

    uv run --extra server python -m server.capture_config
    uv run --extra server python -m server.capture_config --per-body-view on --diagnostics on
    uv run --extra server python -m server.capture_config --looks off

Talks to the bridge directly (127.0.0.1:47800), next to the game server.
The bridge also saves the new values to its BepInEx config file.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from server.bridge_client import BridgeClient

SWITCHES = ["per_body_view", "looks", "own_text", "other_text", "active_from_screen", "diagnostics"]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=47800)
    for name in SWITCHES:
        parser.add_argument("--" + name.replace("_", "-"), choices=["on", "off"])
    args = parser.parse_args()
    changes = {
        name: getattr(args, name) == "on" for name in SWITCHES if getattr(args, name) is not None
    }
    bridge = BridgeClient(port=args.port)
    try:
        print(json.dumps(await bridge.call("capture_config", **changes), indent=2))
    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(main())
