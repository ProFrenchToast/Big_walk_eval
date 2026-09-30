from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol, runtime_checkable


@runtime_checkable
class InputBackend(Protocol):
    """Sends input to the game. Key and button names are canonical (see protocol.VALID_KEYS)."""

    # True when each body has its own input (Backend B). Then held buttons stay
    # on their body across a switch, and the server does not release and
    # press them again.
    per_body: bool

    async def select_slot(self, slot: int) -> None: ...

    async def focus(self) -> None: ...

    async def key_down(self, key: str) -> None: ...

    async def key_up(self, key: str) -> None: ...

    async def button_down(self, button: str) -> None: ...

    async def button_up(self, button: str) -> None: ...

    async def move_rel(self, dx: int, dy: int) -> None: ...

    async def wheel(self, clicks: int, horizontal: bool = False) -> None: ...

    async def release_all(self) -> None:
        """Release every key and button that this backend holds down."""
        ...


class RecordingInputBackend:
    """Records calls instead of sending them. For tests and dry runs."""

    def __init__(self, per_body: bool = False, clock: Callable[[], float] = time.monotonic):
        self.per_body = per_body
        self.clock = clock
        self.calls: list[tuple[float, str, tuple]] = []
        self.keys: set[str] = set()
        self.buttons: set[str] = set()
        self.slot: int | None = None

    def _log(self, name: str, *args: object) -> None:
        self.calls.append((self.clock(), name, args))

    def names(self) -> list[tuple[str, tuple]]:
        return [(name, args) for _, name, args in self.calls]

    async def select_slot(self, slot: int) -> None:
        self.slot = slot
        self._log("select_slot", slot)

    async def focus(self) -> None:
        self._log("focus")

    async def key_down(self, key: str) -> None:
        self.keys.add(key)
        self._log("key_down", key)

    async def key_up(self, key: str) -> None:
        self.keys.discard(key)
        self._log("key_up", key)

    async def button_down(self, button: str) -> None:
        self.buttons.add(button)
        self._log("button_down", button)

    async def button_up(self, button: str) -> None:
        self.buttons.discard(button)
        self._log("button_up", button)

    async def move_rel(self, dx: int, dy: int) -> None:
        self._log("move_rel", dx, dy)

    async def wheel(self, clicks: int, horizontal: bool = False) -> None:
        self._log("wheel", clicks, horizontal)

    async def release_all(self) -> None:
        for key in sorted(self.keys):
            await self.key_up(key)
        for button in sorted(self.buttons):
            await self.button_up(button)
