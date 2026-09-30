"""Backend A: real OS input with Win32 SendInput. Windows only.

Keys are sent as scan codes, because many games read scan codes and ignore
virtual keys. Mouse look uses relative MOUSEEVENTF_MOVE counts.
"""

from __future__ import annotations

import asyncio
import ctypes
import sys
from ctypes import wintypes

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
WHEEL_DELTA = 120
VK_MENU = 0x12
SW_RESTORE = 9

MOUSE_BUTTON_FLAGS = {
    "left": (0x0002, 0x0004),
    "right": (0x0008, 0x0010),
    "middle": (0x0020, 0x0040),
}

# Scan code set 1. Values above 0xFF are extended keys (E0 prefix).
SCAN_CODES: dict[str, int] = {
    "esc": 0x01,
    **{str(d): 0x02 + d - 1 for d in range(1, 10)},
    "0": 0x0B,
    "minus": 0x0C,
    "equal": 0x0D,
    "backspace": 0x0E,
    "tab": 0x0F,
    **dict(zip("qwertyuiop", range(0x10, 0x1A), strict=True)),
    "lbracket": 0x1A,
    "rbracket": 0x1B,
    "enter": 0x1C,
    "ctrl": 0x1D,
    **dict(zip("asdfghjkl", range(0x1E, 0x27), strict=True)),
    "semicolon": 0x27,
    "quote": 0x28,
    "backquote": 0x29,
    "shift": 0x2A,
    "backslash": 0x2B,
    **dict(zip("zxcvbnm", range(0x2C, 0x33), strict=True)),
    "comma": 0x33,
    "period": 0x34,
    "slash": 0x35,
    "alt": 0x38,
    "space": 0x39,
    **{f"f{n}": 0x3B + n - 1 for n in range(1, 11)},
    "plus": 0x4E,
    "f11": 0x57,
    "f12": 0x58,
    "up": 0xE048,
    "left": 0xE04B,
    "right": 0xE04D,
    "down": 0xE050,
}


def key_fields(key: str, up: bool) -> tuple[int, int]:
    """(wScan, dwFlags) for a key event."""
    code = SCAN_CODES[key]
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    if code > 0xFF:
        flags |= KEYEVENTF_EXTENDEDKEY
    return code & 0xFF, flags


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class FocusError(RuntimeError):
    pass


class SendInputBackend:
    """Backend A. Input goes to whichever body is active. NEEDS GAME."""

    per_body = False

    def __init__(self, window_title: str = "Big Walk") -> None:
        if sys.platform != "win32":
            raise RuntimeError("SendInputBackend runs on Windows only")
        self.window_title = window_title
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._keys: set[str] = set()
        self._buttons: set[str] = set()

    def _send(self, *inputs: INPUT) -> None:
        array = (INPUT * len(inputs))(*inputs)
        sent = self._user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            raise OSError(ctypes.get_last_error(), "SendInput was blocked")

    def _key(self, key: str, up: bool) -> None:
        scan, flags = key_fields(key, up)
        self._send(INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(0, scan, flags, 0, 0))))

    def _mouse(self, flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> None:
        mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
        self._send(INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=mi)))

    async def select_slot(self, slot: int) -> None:
        return None

    async def focus(self) -> None:
        # NEEDS GAME: check that the game accepts input right after focus changes.
        u = self._user32
        hwnd = u.FindWindowW(None, self.window_title)
        if not hwnd:
            raise FocusError(f"no window titled {self.window_title!r}")
        if u.GetForegroundWindow() == hwnd:
            return
        u.ShowWindow(hwnd, SW_RESTORE)
        # Windows allows SetForegroundWindow only after recent input; a tap of Alt counts.
        u.keybd_event(VK_MENU, 0, 0, 0)
        u.SetForegroundWindow(hwnd)
        u.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        await asyncio.sleep(0.05)
        if u.GetForegroundWindow() != hwnd:
            raise FocusError("could not bring the game window to the foreground")

    async def key_down(self, key: str) -> None:
        self._key(key, up=False)
        self._keys.add(key)

    async def key_up(self, key: str) -> None:
        self._key(key, up=True)
        self._keys.discard(key)

    async def button_down(self, button: str) -> None:
        self._mouse(MOUSE_BUTTON_FLAGS[button][0])
        self._buttons.add(button)

    async def button_up(self, button: str) -> None:
        self._mouse(MOUSE_BUTTON_FLAGS[button][1])
        self._buttons.discard(button)

    async def move_rel(self, dx: int, dy: int) -> None:
        self._mouse(MOUSEEVENTF_MOVE, dx, dy)

    async def wheel(self, clicks: int, horizontal: bool = False) -> None:
        self._mouse(
            MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL, data=clicks * WHEEL_DELTA
        )

    async def release_all(self) -> None:
        for key in sorted(self._keys):
            await self.key_up(key)
        for button in sorted(self._buttons):
            await self.button_up(button)
