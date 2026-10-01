from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from big_walk_eval.protocol import PRACTICE_MOD_KEYS, SCREEN_HEIGHT, SCREEN_WIDTH


class ServerConfig(BaseModel):
    """Game server settings. Load from YAML with `ServerConfig.load(path)`."""

    host: str = "127.0.0.1"
    port: int = 47801
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 47800
    bridge_timeout_s: float = 30.0

    # "sendinput" is Backend A (OS input to the active body). "bridge" is
    # Backend B (per-body input injected by the bridge mod).
    input_backend: Literal["sendinput", "bridge"] = "sendinput"
    # "mouse" turns with relative mouse counts. "bridge" asks the mod to turn
    # the camera by an exact angle.
    look_mode: Literal["mouse", "bridge"] = "mouse"
    counts_per_degree: float = 10.0
    invert_mouse_y: bool = False
    look_step_ms: int = 10
    # Press the practice mod's slot key instead of the bridge switch_slot command.
    switch_via_keys: bool = False
    switch_timeout_s: float = 5.0
    # Unpaused time after each spawn teleport in reset, so the teleport survives later switches.
    teleport_settle_s: float = 1.5
    # The mouse button of the game's "drop" action. Reset uses it to empty the hands.
    drop_button: Literal["left", "right", "middle"] = "right"
    # The key of the game's "sit" toggle. Reset uses it to stand a sitting body up.
    sit_key: str = "z"
    # On reset, get from the title screen into a hosted walk if needed (server/host_walk.py).
    auto_host: bool = True
    save_name: str = "evalwalk"
    player_count: Literal[2, 3, 4] = 2

    window_title: str = "Big Walk"
    screenshot_width: int = SCREEN_WIDTH
    screenshot_height: int = SCREEN_HEIGHT
    blocked_keys: list[str] = Field(default_factory=lambda: sorted(PRACTICE_MOD_KEYS))
    # Per-body video frames go to <capture_dir>/<episode_id>/ on this machine.
    capture_dir: str = "captures"

    @classmethod
    def load(cls, path: str | Path | None) -> ServerConfig:
        if path is None:
            return cls()
        return cls.model_validate(yaml.safe_load(Path(path).read_text()) or {})
