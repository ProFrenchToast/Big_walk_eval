"""Models shared by the harness, the game server, and FakeGame.

Change these in one place only. The game server imports this module, so the
HTTP API and the harness cannot drift.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCREEN_WIDTH = 1366
SCREEN_HEIGHT = 768

# Game time that each atomic action uses. The timeline builder, FakeGame, and
# the real game server all read these, so budgets mean the same thing everywhere.
KEY_TAP_MS = 50
KEY_GAP_MS = 50
CLICK_MS = 50
BUTTON_EDGE_MS = 50
LOOK_MS = 100
SCROLL_MS = 50

Vec3 = tuple[float, float, float]
Hand = Literal["left", "right"]
MouseButton = Literal["left", "right", "middle"]


class _Wire(BaseModel):
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")


# ---------------------------------------------------------------- game state


class HeldItem(_Wire):
    hand: Hand
    item_id: str
    item_type: str
    is_reward: bool


class BodyState(_Wire):
    slot: int
    name: str
    position: Vec3
    yaw_deg: float
    pitch_deg: float = 0.0
    held: list[HeldItem] = Field(default_factory=list)
    # Game-specific body state (crouch, sit, jump) for checks and logs. Agents do not see it.
    pose: dict[str, Any] = Field(default_factory=dict)


class GameEvent(_Wire):
    type: str
    t_ms: int = 0
    slot: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class GameState(_Wire):
    paused: bool
    active_slot: int
    bodies: list[BodyState]
    events: list[GameEvent] = Field(default_factory=list)
    game_ms: int = 0
    camera_hfov_deg: float | None = None
    info: dict[str, Any] = Field(default_factory=dict)

    def body(self, slot: int) -> BodyState:
        for b in self.bodies:
            if b.slot == slot:
                return b
        raise KeyError(f"no body in slot {slot}")

    def reward_holder(self) -> BodyState | None:
        for b in self.bodies:
            if any(h.is_reward for h in b.held):
                return b
        return None


# ------------------------------------------------------------------- actions


class KeyAction(_Wire):
    type: Literal["key"] = "key"
    keys: list[str]
    repeat: int = Field(default=1, ge=1, le=100)


class HoldKeyAction(_Wire):
    type: Literal["hold_key"] = "hold_key"
    keys: list[str]
    duration_ms: int = Field(ge=0)


class LookAction(_Wire):
    """Turn the camera by an exact angle. Positive yaw turns right, positive pitch looks down."""

    type: Literal["look"] = "look"
    dyaw_deg: float
    dpitch_deg: float = 0.0


class MouseAction(_Wire):
    """`down` and `up` set a button that stays held across turns. `click` is down then up."""

    type: Literal["mouse"] = "mouse"
    button: MouseButton = "left"
    event: Literal["down", "up", "click"]


class WaitAction(_Wire):
    type: Literal["wait"] = "wait"
    duration_ms: int = Field(ge=0)


class ScrollAction(_Wire):
    type: Literal["scroll"] = "scroll"
    direction: Literal["up", "down", "left", "right"]
    amount: int = Field(default=1, ge=1, le=50)


Action = Annotated[
    KeyAction | HoldKeyAction | LookAction | MouseAction | WaitAction | ScrollAction,
    Field(discriminator="type"),
]


class ActResult(_Wire):
    screenshot_png: bytes
    game_ms: int
    truncated: bool
    events: list[GameEvent] = Field(default_factory=list)


# -------------------------------------------------------------------- puzzles


class BodySpawn(_Wire):
    slot: int
    name: str
    position: Vec3
    yaw_deg: float = 0.0


class PropPlacement(_Wire):
    """Put a prop at a position during reset. The prop is the nearest one of
    `item_type` to `near` (default: `position`). Stands in for a save snapshot."""

    item_type: str
    position: Vec3
    near: Vec3 | None = None


class OverviewCamera(_Wire):
    position: Vec3
    look_at: Vec3


class PuzzleConfig(_Wire):
    """One puzzle, loaded from `puzzles/<id>.yaml`."""

    id: str
    title: str
    area: str = ""
    game: Literal["real", "fake"] = "real"
    needs_sound: bool = False
    min_agents: int = 2
    snapshot: str = ""
    spawns: list[BodySpawn]
    props: list[PropPlacement] = Field(default_factory=list)
    reward_item_type: str = ""
    max_turns: int = 60
    notes: str = ""
    location_hint: str = ""
    overview: OverviewCamera | None = None

    def reset_request(self, n_agents: int) -> ResetRequest:
        if n_agents > len(self.spawns):
            raise ValueError(
                f"puzzle {self.id} has {len(self.spawns)} spawns, {n_agents} agents requested"
            )
        return ResetRequest(
            puzzle_id=self.id,
            snapshot=self.snapshot,
            bodies=self.spawns[:n_agents],
            props=self.props,
            reward_item_type=self.reward_item_type,
        )


# ------------------------------------------------------- game server requests


class ResetRequest(_Wire):
    puzzle_id: str
    snapshot: str = ""
    bodies: list[BodySpawn]
    props: list[PropPlacement] = Field(default_factory=list)
    reward_item_type: str = ""


class SwitchRequest(_Wire):
    slot: int


class ActRequest(_Wire):
    slot: int
    actions: list[Action]
    budget_ms: int = Field(ge=0)


class ChatEchoRequest(_Wire):
    slot: int
    text: str


class OverviewRequest(_Wire):
    position: Vec3 | None = None
    look_at: Vec3 | None = None


class ScreenshotResponse(_Wire):
    png: bytes | None


class OkResponse(_Wire):
    ok: bool = True


class HealthResponse(_Wire):
    ok: bool
    backend: str
    game_version: str | None = None
    bridge_connected: bool = False
    mods: dict[str, str] = Field(default_factory=dict)


# ----------------------------------------------------------------------- keys

# Canonical key names. Models send xdotool-style names ("Return", "shift+w"),
# which `parse_keys` maps onto this set.
_NAMED_KEYS = {
    "space",
    "enter",
    "esc",
    "tab",
    "backspace",
    "shift",
    "ctrl",
    "alt",
    "up",
    "down",
    "left",
    "right",
    "minus",
    "equal",
    "plus",
    "comma",
    "period",
    "slash",
    "semicolon",
    "quote",
    "backquote",
    "lbracket",
    "rbracket",
    "backslash",
}
VALID_KEYS: frozenset[str] = frozenset(
    _NAMED_KEYS
    | {chr(c) for c in range(ord("a"), ord("z") + 1)}
    | {str(d) for d in range(10)}
    | {f"f{n}" for n in range(1, 13)}
)

_KEY_ALIASES = {
    "return": "enter",
    "kp_enter": "enter",
    "escape": "esc",
    "control": "ctrl",
    "control_l": "ctrl",
    "control_r": "ctrl",
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "shift_l": "shift",
    "shift_r": "shift",
    "alt_l": "alt",
    "alt_r": "alt",
    "back_space": "backspace",
    "spacebar": "space",
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
    "kp_add": "plus",
    "equals": "equal",
    "=": "equal",
    "-": "minus",
    ",": "comma",
    ".": "period",
    "/": "slash",
    ";": "semicolon",
    "'": "quote",
    "`": "backquote",
    "[": "lbracket",
    "]": "rbracket",
    "\\": "backslash",
}

# Hotkeys of big-walk-practice and the tools installed next to it. An agent
# that presses one of these would switch bodies, teleport every body, or open
# a menu, so the tool rejects them.
PRACTICE_MOD_KEYS: frozenset[str] = frozenset(
    {str(d) for d in range(10)} | {"plus", "equal", "r", "g", "f1", "f2", "f3", "f5", "f9"}
)


class KeyParseError(ValueError):
    pass


def parse_keys(text: str) -> list[str]:
    """Parse "shift+w" into canonical key names ["shift", "w"]."""
    raw = text.strip()
    parts = ["plus"] if raw == "+" else [p.strip() for p in raw.split("+")]
    if not parts or any(p == "" for p in parts):
        raise KeyParseError(f"cannot parse key combination {text!r}")
    keys: list[str] = []
    for part in parts:
        low = part.lower()
        key = _KEY_ALIASES.get(low, low)
        if key not in VALID_KEYS:
            raise KeyParseError(f"unknown key {part!r}")
        if key not in keys:
            keys.append(key)
    return keys
