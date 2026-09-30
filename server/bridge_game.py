"""The real game as a `GameClient`: the bridge mod for state, an input backend for input.

One `act` runs as: switch slot -> focus -> resume -> play the timeline -> pause -> capture.
Not safe for concurrent calls. The app runs one call at a time.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from big_walk_eval.look import vfov_to_hfov
from big_walk_eval.protocol import (
    Action,
    ActResult,
    BodyState,
    CaptureInfo,
    CaptureRequest,
    GameState,
    HealthResponse,
    HeldItem,
    HoldKeyAction,
    KeyAction,
    ResetRequest,
    Vec3,
)
from big_walk_eval.timeline import build_timeline
from server.bridge_client import BridgeClient, BridgeError
from server.config import ServerConfig
from server.input.backend import InputBackend
from server.input.player import TimelinePlayer


class BridgeGame:
    def __init__(
        self,
        bridge: BridgeClient,
        input: InputBackend,
        config: ServerConfig,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.bridge = bridge
        self.input = input
        self.config = config
        self.clock = clock
        self.sleep = sleep
        self.player = TimelinePlayer(
            input,
            counts_per_degree=config.counts_per_degree,
            invert_y=config.invert_mouse_y,
            look_step_ms=config.look_step_ms,
            look_fn=bridge.look if config.look_mode == "bridge" else None,
            clock=clock,
            sleep=sleep,
        )
        self.names: dict[int, str] = {}
        self.held: dict[int, set[str]] = {}
        self.active: int | None = None
        self._capture: tuple[CaptureRequest, Path, list[int]] | None = None
        self._reward_type = ""
        self._blocked = set(config.blocked_keys)

    async def health(self) -> HealthResponse:
        try:
            hello = await self.bridge.hello()
        except (BridgeError, OSError):
            return HealthResponse(ok=False, backend="bridge", bridge_connected=False)
        mods = {"bridge": hello.bridge_version, "practice": hello.practice_version}
        return HealthResponse(
            ok=True,
            backend=f"bridge+{self.config.input_backend}",
            game_version=hello.game_version,
            bridge_connected=True,
            mods={k: v for k, v in mods.items() if v},
        )

    async def reset(self, request: ResetRequest) -> GameState:
        await self.stop_capture()
        await self._release_everything()
        await self.bridge.pause()
        if request.snapshot:
            # NEEDS GAME: the mod's load_snapshot is TODO(dump).
            await self.bridge.load_snapshot(request.snapshot)
        await self.bridge.spawn_bodies(len(request.bodies))
        for body in request.bodies:
            await self.bridge.teleport(body.slot, body.position, body.yaw_deg)
        self.names = {b.slot: b.name for b in request.bodies}
        self.held = {b.slot: set() for b in request.bodies}
        self._reward_type = request.reward_item_type
        self.active = None
        await self._switch(request.bodies[0].slot)
        await self.bridge.events()
        return await self.state()

    async def switch(self, slot: int) -> None:
        await self._switch(slot)

    async def screenshot(self) -> bytes:
        return await self.bridge.screenshot(
            self.config.screenshot_width, self.config.screenshot_height
        )

    async def act(self, slot: int, actions: list[Action], budget_ms: int) -> ActResult:
        for action in actions:
            if isinstance(action, KeyAction | HoldKeyAction):
                bad = self._blocked.intersection(action.keys)
                if bad:
                    raise ValueError(f"blocked key {sorted(bad)[0]!r}")
        await self._switch(slot)
        timeline = build_timeline(actions, budget_ms, self.held[slot])
        await self.input.focus()
        wall0 = self.clock()
        t0 = await self.bridge.resume()
        try:
            await self.player.play(timeline)
        except BaseException:
            await self.input.release_all()
            self.held[slot] = set()
            raise
        finally:
            t1 = await self.bridge.pause()
            wall1 = self.clock()
        self.held[slot] = set(timeline.held_buttons)
        if t0 is not None and t1 is not None:
            game_ms = round((t1 - t0) * 1000)
        else:
            game_ms = round((wall1 - wall0) * 1000)
        return ActResult(
            screenshot_png=await self.screenshot(),
            game_ms=game_ms,
            truncated=timeline.truncated,
            events=await self.bridge.events(),
        )

    async def state(self) -> GameState:
        raw = await self.bridge.get_state()
        events = await self.bridge.events()
        bodies = [
            BodyState(
                slot=b.slot,
                name=self.names.get(b.slot, f"slot {b.slot}"),
                position=b.position,
                yaw_deg=b.yaw_deg,
                pitch_deg=b.pitch_deg,
                held=[
                    HeldItem(
                        hand=h.hand,
                        item_id=h.item_id,
                        item_type=h.item_type,
                        is_reward=h.is_reward
                        if h.is_reward is not None
                        else bool(self._reward_type) and h.item_type == self._reward_type,
                    )
                    for h in b.held
                ],
            )
            for b in raw.bodies
            if not self.names or b.slot in self.names
        ]
        return GameState(
            paused=raw.paused,
            active_slot=raw.active_slot,
            bodies=bodies,
            events=events,
            game_ms=round(raw.time_s * 1000) if raw.time_s is not None else 0,
            camera_hfov_deg=vfov_to_hfov(raw.camera_vfov_deg) if raw.camera_vfov_deg else None,
        )

    async def echo_chat(self, slot: int, text: str) -> None:
        # NEEDS GAME: the mod's chat command is TODO(dump).
        await self.bridge.chat(slot, text)

    async def overview_shot(
        self, position: Vec3 | None = None, look_at: Vec3 | None = None
    ) -> bytes | None:
        return await self.bridge.overview_shot(
            position, look_at, self.config.screenshot_width, self.config.screenshot_height
        )

    async def start_capture(self, request: CaptureRequest) -> None:
        await self.stop_capture()
        slots = request.slots or sorted(self.names)
        for slot in slots:
            if slot not in self.names:
                raise ValueError(f"no body in slot {slot}")
        directory = Path(self.config.capture_dir).resolve() / request.episode_id
        directory.mkdir(parents=True, exist_ok=True)
        # NEEDS GAME: the mod renders one camera per body and pipes frames to ffmpeg.
        await self.bridge.capture_start(
            str(directory), request.fps, request.width, request.height, slots
        )
        self._capture = (request, directory, slots)

    async def stop_capture(self) -> CaptureInfo | None:
        if self._capture is None:
            return None
        request, directory, slots = self._capture
        self._capture = None
        result = await self.bridge.capture_stop()
        info = CaptureInfo(
            episode_id=request.episode_id,
            directory=str(directory),
            fps=request.fps,
            width=request.width,
            height=request.height,
            slots={slot: self.names[slot] for slot in slots},
            frames=int(result.get("frames", 0)),
            start_game_ms=round(float(result.get("start_time_s") or 0.0) * 1000),
        )
        (directory / "capture.json").write_text(info.model_dump_json(indent=2))
        return info

    async def close(self) -> None:
        await self.stop_capture()
        await self._release_everything()
        await self.bridge.close()

    # ---------------------------------------------------------------- switching

    async def _switch(self, slot: int) -> None:
        if slot not in self.names:
            raise ValueError(f"no body in slot {slot}")
        if slot == self.active:
            return
        if not self.input.per_body:
            # Backend A: OS input reaches only the active body. Release the old
            # body's buttons before the swap and press the new body's buttons
            # after it. NEEDS GAME: check 1 must show that the old body keeps its
            # grip through this release while paused.
            await self.input.release_all()
        await self._switch_slot(slot)
        await self.input.select_slot(slot)
        if not self.input.per_body:
            for button in sorted(self.held.get(slot, ())):
                await self.input.button_down(button)
        self.active = slot

    async def _switch_slot(self, slot: int) -> None:
        if not self.config.switch_via_keys:
            await self.bridge.switch_slot(slot)
            return
        # Fallback: press the practice mod's slot key (1-9, 0 for slot 10).
        key = str(slot % 10)
        await self.input.focus()
        await self.input.key_down(key)
        await self.sleep(0.05)
        await self.input.key_up(key)
        deadline = self.clock() + self.config.switch_timeout_s
        while (await self.bridge.get_state()).active_slot != slot:
            if self.clock() > deadline:
                raise TimeoutError(f"the game did not switch to slot {slot}")
            await self.sleep(0.05)

    async def _release_everything(self) -> None:
        await self.input.release_all()
        if self.input.per_body:
            for slot, buttons in self.held.items():
                await self.input.select_slot(slot)
                for button in sorted(buttons):
                    await self.input.button_up(button)
        self.held = {slot: set() for slot in self.held}


def make_bridge_game(config: ServerConfig) -> BridgeGame:
    bridge = BridgeClient(config.bridge_host, config.bridge_port, config.bridge_timeout_s)
    if config.input_backend == "bridge":
        from server.input.bridge_input import BridgeInputBackend

        backend: InputBackend = BridgeInputBackend(bridge)
    else:
        from server.input.sendinput import SendInputBackend

        backend = SendInputBackend(config.window_title)
    return BridgeGame(bridge, backend, config)
