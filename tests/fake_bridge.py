"""A TCP server that speaks the bridge mod protocol, for tests."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from typing import Any


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)
        await asyncio.sleep(0)


class FakeBridge:
    def __init__(self, clock: Callable[[], float]) -> None:
        self.clock = clock
        self.paused = True
        self.active = 1
        self.bodies: dict[int, dict[str, Any]] = {}
        self.commands: list[tuple[str, dict[str, Any]]] = []
        self.pending_events: list[dict[str, Any]] = []
        self.fail: dict[str, str] = {}
        self.camera_vfov_deg = 60.0
        self.props: dict[str, list[float]] = {}
        self.saves: set[str] = set()
        self.menu = "ready"  # title, host_select, host_confirm, player_count, or ready
        self.screen: tuple[bytes, int, int] | None = None
        self.capture: dict[str, Any] | None = None
        self._game_time = 0.0
        self._resumed_at = 0.0
        self._server: asyncio.base_events.Server | None = None
        self.port = 0

    def cmds(self) -> list[str]:
        return [c for c, _ in self.commands]

    def time_s(self) -> float:
        running = 0.0 if self.paused else self.clock() - self._resumed_at
        return self._game_time + running

    def handle(self, cmd: str, args: dict[str, Any]) -> dict[str, Any]:
        self.commands.append((cmd, args))
        if cmd in self.fail:
            raise RuntimeError(self.fail[cmd])
        match cmd:
            case "hello":
                return {
                    "game_version": "1.5.1",
                    "bridge_version": "0.1.0",
                    "practice_version": "0.6.0",
                }
            case "pause":
                if not self.paused:
                    self._game_time += self.clock() - self._resumed_at
                    self.paused = True
                return {"time_s": self.time_s()}
            case "resume":
                if self.paused:
                    self._resumed_at = self.clock()
                    self.paused = False
                return {"time_s": self.time_s()}
            case "get_state":
                return {
                    "paused": self.paused,
                    "active_slot": self.active,
                    "time_s": self.time_s(),
                    "camera_vfov_deg": self.camera_vfov_deg,
                    "bodies": [{"slot": s, **b} for s, b in sorted(self.bodies.items())],
                }
            case "switch_slot":
                if args["slot"] not in self.bodies:
                    raise RuntimeError(f"no body in slot {args['slot']}")
                self.active = args["slot"]
                return {}
            case "spawn_bodies":
                for slot in range(1, args["n"] + 1):
                    self.bodies.setdefault(
                        slot, {"position": [0, 0, 0], "yaw_deg": 0.0, "pitch_deg": 0.0, "held": []}
                    )
                self.pending_events.append({"type": "bodies_spawned", "data": {"n": args["n"]}})
                return {"count": len(self.bodies)}
            case "teleport":
                body = self.bodies[args["slot"]]
                body["position"] = args["position"]
                body["yaw_deg"] = args["yaw_deg"]
                return {}
            case "screenshot":
                if self.screen is not None:
                    png, width, height = self.screen
                    return {
                        "png_base64": base64.b64encode(png).decode(),
                        "width": width,
                        "height": height,
                    }
                png = f"png:{self.active}:{args['width']}x{args['height']}".encode()
                return {"png_base64": base64.b64encode(png).decode()}
            case "place_prop":
                self.props[args["item_type"]] = args["position"]
                return {"item_id": "1", "item_type": args["item_type"]}
            case "menu":
                return self._menu(args.get("action", "status"), args)
            case "overview_shot":
                return {"png_base64": base64.b64encode(b"overview").decode()}
            case "events":
                events, self.pending_events = self.pending_events, []
                return {"events": events}
            case "look":
                body = self.bodies[self.active]
                body["yaw_deg"] += args["dyaw_deg"]
                body["pitch_deg"] += args["dpitch_deg"]
                return {}
            case "capture_start":
                self.capture = {**args, "start_time_s": self.time_s()}
                return {}
            case "capture_stop":
                if self.capture is None:
                    raise RuntimeError("no capture runs")
                start = self.capture["start_time_s"]
                frames = int((self.time_s() - start) * self.capture["fps"]) + 1
                self.capture = None
                return {"frames": frames, "start_time_s": start}
            case "load_snapshot" | "chat" | "input":
                return {}
        raise RuntimeError(f"unknown command {cmd}")

    def _menu(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        steps = {
            "title_host": ("title", "host_select"),
            "new_game": ("host_select", "host_confirm"),
            "host_confirm": ("host_confirm", "player_count"),
            "player_count": ("player_count", "ready"),
        }
        if action == "load_save":
            if self.menu != "host_select" or args.get("name") not in self.saves:
                raise RuntimeError(f"no save named {args.get('name')}")
            self.menu = "host_confirm"
        elif action in steps:
            before, after = steps[action]
            if self.menu != before:
                raise RuntimeError(f"the {before} menu is not open")
            self.menu = after
        ready = self.menu == "ready"
        return {
            "open_menus": [] if ready else [self.menu],
            "hosting": ready,
            "local_player": ready,
            "local_player_ready": ready,
        }

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while line := await reader.readline():
            request = json.loads(line)
            try:
                result = self.handle(request["cmd"], request.get("args") or {})
                response = {"id": request["id"], "ok": True, "result": result}
            except Exception as e:
                response = {"id": request["id"], "ok": False, "error": str(e)}
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
        writer.close()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
