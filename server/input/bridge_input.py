"""Backend B: the bridge mod injects input into one body's Rewired player.

Each body keeps its own input state, so a held button stays on its body
while another body acts. The mod side is TODO(dump): it needs a Rewired
CustomController per body. NEEDS GAME.
"""

from __future__ import annotations

from server.bridge_client import BridgeClient


class BridgeInputBackend:
    per_body = True

    def __init__(self, bridge: BridgeClient) -> None:
        self.bridge = bridge
        self.slot: int | None = None
        self._held: dict[int, tuple[set[str], set[str]]] = {}

    def _state(self) -> tuple[int, set[str], set[str]]:
        if self.slot is None:
            raise RuntimeError("select a slot before sending input")
        keys, buttons = self._held.setdefault(self.slot, (set(), set()))
        return self.slot, keys, buttons

    async def select_slot(self, slot: int) -> None:
        self.slot = slot

    async def focus(self) -> None:
        return None

    async def key_down(self, key: str) -> None:
        slot, keys, _ = self._state()
        await self.bridge.input(slot, {"op": "key_down", "key": key})
        keys.add(key)

    async def key_up(self, key: str) -> None:
        slot, keys, _ = self._state()
        await self.bridge.input(slot, {"op": "key_up", "key": key})
        keys.discard(key)

    async def button_down(self, button: str) -> None:
        slot, _, buttons = self._state()
        await self.bridge.input(slot, {"op": "button_down", "button": button})
        buttons.add(button)

    async def button_up(self, button: str) -> None:
        slot, _, buttons = self._state()
        await self.bridge.input(slot, {"op": "button_up", "button": button})
        buttons.discard(button)

    async def move_rel(self, dx: int, dy: int) -> None:
        slot, _, _ = self._state()
        await self.bridge.input(slot, {"op": "move_rel", "dx": dx, "dy": dy})

    async def wheel(self, clicks: int, horizontal: bool = False) -> None:
        slot, _, _ = self._state()
        await self.bridge.input(slot, {"op": "wheel", "clicks": clicks, "horizontal": horizontal})

    async def type_char(self, char: str) -> None:
        slot, _, _ = self._state()
        await self.bridge.input(slot, {"op": "char", "char": char})

    async def release_all(self) -> None:
        """Release held keys on the current body. Held buttons stay: they are the grip."""
        _, keys, _ = self._state()
        for key in sorted(keys):
            await self.key_up(key)
