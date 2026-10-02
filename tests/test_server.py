from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest
from inspect_ai import Task, eval
from inspect_ai.model import get_model
from PIL import Image

from big_walk_eval.dataset import puzzle_dataset
from big_walk_eval.episode import EpisodeConfig
from big_walk_eval.game.fake_game import FakeGame
from big_walk_eval.game.http_game import GameServerError, HttpGame
from big_walk_eval.prompts import FAKE_GAME_CONTROLS
from big_walk_eval.protocol import (
    KEY_GAP_MS,
    KEY_TAP_MS,
    TYPE_CHAR_MS,
    CaptureInfo,
    CaptureRequest,
    HoldKeyAction,
    KeyAction,
    LookAction,
    MouseAction,
    PropPlacement,
    ResetRequest,
    TypeAction,
    WaitAction,
)
from big_walk_eval.scorer import puzzle_solved
from big_walk_eval.scripted import Script, ScriptedPolicy
from big_walk_eval.solver import round_robin
from big_walk_eval.timeline import build_timeline
from server.app import create_app
from server.bridge_client import BridgeClient, BridgeError
from server.bridge_game import BridgeGame
from server.calibrate import calibrate
from server.config import ServerConfig
from server.input.backend import RecordingInputBackend
from server.input.player import TimelinePlayer, mouse_look_steps
from server.input.sendinput import SCAN_CODES, key_fields, unicode_units
from server.record_spawns import spawns_yaml
from tests.conftest import ASH, BIRCH, ROOT, reset_request
from tests.fake_bridge import FakeBridge, FakeClock


def http_game(game: FakeGame | None = None) -> HttpGame:
    app = create_app(game or FakeGame(seed=0))
    return HttpGame("http://game", transport=httpx.ASGITransport(app=app))


# ------------------------------------------------------------ HTTP API + HttpGame


async def test_http_game_matches_fake_game():
    direct = FakeGame(seed=0)
    remote = http_game(FakeGame(seed=0))
    actions = [LookAction(dyaw_deg=-36.87), HoldKeyAction(keys=["w"], duration_ms=2500)]
    assert await remote.reset(reset_request()) == await direct.reset(reset_request())
    assert await remote.act(1, actions, 3000) == await direct.act(1, actions, 3000)
    assert await remote.state() == await direct.state()
    await remote.switch(2)
    await direct.switch(2)
    assert await remote.screenshot() == await direct.screenshot()
    assert (await remote.health()).backend == "fake"
    assert await remote.overview_shot() == await direct.overview_shot()
    await remote.close()


async def test_http_errors_are_raised():
    remote = http_game()
    await remote.reset(reset_request())
    with pytest.raises(GameServerError, match="400"):
        await remote.switch(7)
    await remote.close()

    app = create_app(FakeGame())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://g") as c:
        resp = await c.post("/act", content='{"slot": 1, "actions": [], "budget_ms": -5}')
        assert resp.status_code == 400
        assert "budget_ms" in resp.json()["detail"]


def test_scripted_episode_over_http(tmp_path):
    app = create_app(FakeGame(seed=0))
    task = Task(
        dataset=puzzle_dataset("fake", 2),
        solver=round_robin(
            lambda: HttpGame("http://game", transport=httpx.ASGITransport(app=app)),
            EpisodeConfig(),
            controls=FAKE_GAME_CONTROLS,
        ),
        scorer=puzzle_solved(),
    )
    policy = ScriptedPolicy(Script.load(ROOT / "scripts" / "solutions" / "fake_plate_gate.yaml"))
    [log] = eval(
        task,
        model=get_model("mockllm/model", custom_outputs=policy),
        log_dir=str(tmp_path),
        display="none",
    )
    assert log.status == "success", log.error
    assert log.samples[0].scores["puzzle_solved"].value == "C"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_server_starts_in_fake_mode():
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "server.app", "--fake", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 30
        while True:
            try:
                resp = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
                break
            except httpx.HTTPError:
                if time.time() > deadline or proc.poll() is not None:
                    raise
                time.sleep(0.2)
        assert resp.json()["backend"] == "fake"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# ------------------------------------------------------------------- bridge


@pytest.fixture
async def bridge_env():
    clock = FakeClock()
    bridge = FakeBridge(clock)
    await bridge.start()
    client = BridgeClient("127.0.0.1", bridge.port, timeout_s=5)
    yield clock, bridge, client
    await client.close()
    await bridge.stop()


def make_game(clock, client, per_body=False, **config) -> tuple[BridgeGame, RecordingInputBackend]:
    backend = RecordingInputBackend(per_body=per_body, clock=clock)
    cfg = ServerConfig(counts_per_degree=10, **config)
    return BridgeGame(client, backend, cfg, clock=clock, sleep=clock.sleep), backend


async def test_bridge_game_capture(bridge_env, tmp_path):
    clock, bridge, client = bridge_env
    game, _ = make_game(clock, client, capture_dir=str(tmp_path))
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))
    assert await game.stop_capture() is None
    await game.start_capture(CaptureRequest(episode_id="ep1", fps=10, width=64, height=36))
    assert bridge.capture["slots"] == [1, 2]
    assert bridge.capture["directory"] == str((tmp_path / "ep1").resolve())
    await game.act(2, [WaitAction(duration_ms=500)], 3000)
    info = await game.stop_capture()
    assert info.slots == {1: "Ash", 2: "Birch"}
    assert info.frames == 6
    assert CaptureInfo.model_validate_json((tmp_path / "ep1" / "capture.json").read_text()) == info
    assert bridge.capture is None
    with pytest.raises(ValueError, match="slot 7"):
        await game.start_capture(CaptureRequest(episode_id="ep2", slots=[7]))


async def test_http_capture_matches_fake_game(tmp_path):
    game = http_game(FakeGame(seed=0, capture_dir=tmp_path))
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))
    await game.start_capture(CaptureRequest(episode_id="ep", fps=10, width=64, height=36))
    await game.act(1, [WaitAction(duration_ms=300)], 3000)
    info = await game.stop_capture()
    assert info.frames == 4
    assert await game.stop_capture() is None
    with pytest.raises(GameServerError, match="400"):
        await game.start_capture(CaptureRequest(episode_id="ep", slots=[7]))


async def test_bridge_client_roundtrip_and_errors(bridge_env):
    _, bridge, client = bridge_env
    hello = await client.hello()
    assert hello.practice_version == "0.6.0"
    bridge.fail["pause"] = "main thread is busy"
    with pytest.raises(BridgeError, match="main thread is busy"):
        await client.pause()
    assert (await client.resume()) is not None


async def test_bridge_game_reset(bridge_env):
    clock, bridge, client = bridge_env
    game, _ = make_game(clock, client)
    state = await game.reset(
        ResetRequest(
            puzzle_id="p", snapshot="saves/p", bodies=[ASH, BIRCH], reward_item_type="Gourd"
        )
    )
    # Each body is teleported while it is the local body, then the game runs briefly.
    assert [c for c in bridge.cmds() if c not in ("get_state", "menu")][:15] == [
        "pause",
        "load_snapshot",
        "spawn_bodies",
        "release_switches",
        "clear_chat",
        "switch_slot",
        "teleport",
        "resume",
        "pause",
        "switch_slot",
        "teleport",
        "resume",
        "pause",
        "switch_slot",
        "events",
    ]
    assert state.active_slot == 1
    assert [b.name for b in state.bodies] == ["Ash", "Birch"]
    assert state.body(1).position == (-5.0, 0.0, 0.0)
    assert state.camera_hfov_deg == pytest.approx(91.52, abs=0.01)
    assert state.events == []


async def test_bridge_game_act_plays_timeline_while_resumed(bridge_env):
    clock, bridge, client = bridge_env
    game, backend = make_game(clock, client)
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))
    backend.calls.clear()
    bridge.commands.clear()

    result = await game.act(2, [HoldKeyAction(keys=["w"], duration_ms=1000)], 3000)

    assert bridge.cmds() == ["switch_slot", "resume", "pause", "screenshot", "events"]
    t0 = next(t for t, name, _ in backend.calls if name == "key_down")
    t1 = next(t for t, name, _ in backend.calls if name == "key_up")
    assert t1 - t0 == pytest.approx(1.0)
    assert result.game_ms == 1000
    assert result.screenshot_png == b"png:2:1366x768"
    assert not result.truncated


async def test_held_buttons_move_with_their_body(bridge_env):
    clock, _, client = bridge_env
    game, backend = make_game(clock, client)
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))
    await game.act(1, [MouseAction(event="down")], 3000)
    assert backend.buttons == {"left"}

    backend.calls.clear()
    await game.switch(2)
    assert backend.names() == [("button_up", ("left",)), ("select_slot", (2,))]
    assert backend.buttons == set()

    backend.calls.clear()
    await game.switch(1)
    assert backend.names() == [("select_slot", (1,)), ("button_down", ("left",))]
    assert game.held == {1: {"left"}, 2: set()}


async def test_per_body_backend_keeps_buttons_on_switch(bridge_env):
    clock, _, client = bridge_env
    game, backend = make_game(clock, client, per_body=True)
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))
    await game.act(1, [MouseAction(event="down")], 3000)
    backend.calls.clear()
    await game.switch(2)
    assert backend.names() == [("select_slot", (2,))]


async def test_blocked_keys_rejected_by_server(bridge_env):
    clock, _, client = bridge_env
    game, _ = make_game(clock, client)
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))
    with pytest.raises(ValueError, match="blocked key"):
        await game.act(1, [HoldKeyAction(keys=["r"], duration_ms=10)], 3000)


async def test_bridge_state_marks_reward_by_type(bridge_env):
    clock, bridge, client = bridge_env
    game, _ = make_game(clock, client)
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH], reward_item_type="Gourd"))
    bridge.bodies[2]["held"] = [{"hand": "left", "item_id": "17", "item_type": "Gourd"}]
    holder = (await game.state()).reward_holder()
    assert holder is not None and holder.name == "Birch"


async def test_switch_via_keys(bridge_env):
    clock, bridge, client = bridge_env
    game, backend = make_game(clock, client, switch_via_keys=True)
    original = backend.key_down

    async def key_down(key: str) -> None:
        await original(key)
        if key.isdigit():
            bridge.active = int(key) or 10

    backend.key_down = key_down
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))
    await game.switch(2)
    assert bridge.active == 2
    assert "switch_slot" not in bridge.cmds()


async def test_bridge_look_mode(bridge_env):
    clock, bridge, client = bridge_env
    game, backend = make_game(clock, client, look_mode="bridge")
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))
    await game.act(1, [LookAction(dyaw_deg=30, dpitch_deg=-5)], 3000)
    assert bridge.bodies[1]["yaw_deg"] == pytest.approx(30)
    assert not any(name == "move_rel" for _, name, _ in backend.calls)


async def test_reset_drops_held_items_then_places_props(bridge_env):
    clock, bridge, client = bridge_env
    game, backend = make_game(clock, client)
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))
    bridge.bodies[2]["held"] = [{"hand": "right", "item_id": "9", "item_type": "Ball"}]
    backend.calls.clear()
    bridge.commands.clear()

    await game.reset(
        ResetRequest(
            puzzle_id="p",
            bodies=[ASH, BIRCH],
            props=[PropPlacement(item_type="Ball", position=(1.0, 2.0, 3.0))],
        )
    )

    # Birch presses the drop button while the game runs, before any prop moves.
    assert ("button_down", ("right",)) in backend.names()
    cmds = bridge.cmds()
    assert cmds.index("place_prop") < cmds.index("teleport")
    assert bridge.props == {"Ball": [1.0, 2.0, 3.0]}
    assert bridge.homed_props == set()


async def test_reset_can_pin_a_prop_to_its_home(bridge_env):
    clock, bridge, client = bridge_env
    game, _ = make_game(clock, client)
    await game.reset(
        ResetRequest(
            puzzle_id="p",
            bodies=[ASH, BIRCH],
            props=[PropPlacement(item_type="GourdProp", position=(1.0, 2.0, 3.0), home=True)],
        )
    )
    assert bridge.homed_props == {"GourdProp"}


async def test_reset_releases_held_world_switches(bridge_env):
    clock, bridge, client = bridge_env
    game, _ = make_game(clock, client)
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))
    bridge.held_switches["Podium/BasicPushButton/PeckSwitchTrigger"] = 1
    bridge.commands.clear()

    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))

    assert bridge.held_switches == {}
    cmds = bridge.cmds()
    assert cmds.index("release_switches") < cmds.index("teleport")


async def test_reset_stands_sitting_bodies_up(bridge_env):
    clock, bridge, client = bridge_env
    game, backend = make_game(clock, client)
    for slot in (1, 2):
        bridge.bodies[slot] = {"position": [0, 0, 0], "yaw_deg": 0.0, "pitch_deg": 0.0, "held": []}
    bridge.bodies[2]["pose"] = {"sitting": True}

    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))

    # Only the sitting body taps the sit key, while it is the active body and the game runs.
    taps = [i for i, (_, name, args) in enumerate(backend.calls) if name == "key_down"]
    assert [backend.calls[i][2] for i in taps] == [("z",)]
    switches = [(c, a) for c, a in bridge.commands if c in ("switch_slot", "resume", "pause")]
    assert ("switch_slot", {"slot": 2}) in switches


async def test_reset_levels_each_view(bridge_env):
    clock, bridge, client = bridge_env
    game, backend = make_game(clock, client)
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))
    bridge.bodies[1]["pitch_deg"] = 20.0
    backend.calls.clear()

    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))

    moves = [args for _, name, args in backend.calls if name == "move_rel"]
    # counts_per_degree=10: 20 degrees of pitch back to level. Yaw already matches the spawn.
    assert sum(dy for _, dy in moves) == -200
    assert sum(dx for dx, _ in moves) == 0


async def test_reset_hosts_a_walk_from_the_title_screen(bridge_env):
    clock, bridge, client = bridge_env
    bridge.menu = "title"
    game, _ = make_game(clock, client)
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))
    actions = [a.get("action") for c, a in bridge.commands if c == "menu"]
    assert [a for a in actions if a != "status"] == [
        "title_host",
        "load_save",
        "new_game",
        "host_confirm",
        "player_count",
    ]
    assert bridge.menu == "ready"


async def test_reset_opens_an_existing_save(bridge_env):
    clock, bridge, client = bridge_env
    bridge.menu = "title"
    bridge.saves = {"evalwalk"}
    game, _ = make_game(clock, client)
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))
    actions = [a.get("action") for c, a in bridge.commands if c == "menu"]
    assert "new_game" not in actions
    assert bridge.menu == "ready"


async def test_reward_type_overrides_bridge_is_reward_false(bridge_env):
    clock, bridge, client = bridge_env
    game, _ = make_game(clock, client)
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH], reward_item_type="Ball"))
    bridge.bodies[1]["held"] = [
        {"hand": "right", "item_id": "9", "item_type": "Ball", "is_reward": False}
    ]
    holder = (await game.state()).reward_holder()
    assert holder is not None and holder.name == "Ash"


async def test_bridge_screenshot_scaled_to_requested_size(bridge_env):
    _, bridge, client = bridge_env
    image = io.BytesIO()
    Image.new("RGB", (200, 100), "red").save(image, format="PNG")
    bridge.screen = (image.getvalue(), 200, 100)
    png = await client.screenshot(40, 20)
    assert Image.open(io.BytesIO(png)).size == (40, 20)


# ------------------------------------------------------------ input helpers


def test_mouse_look_steps_sum_exactly():
    steps = mouse_look_steps(12.34, -3.21, 7.5, 10)
    assert sum(dx for dx, _ in steps) == round(12.34 * 7.5)
    assert sum(dy for _, dy in steps) == round(-3.21 * 7.5)
    inverted = mouse_look_steps(0, 10, 2, 4, invert_y=True)
    assert sum(dy for _, dy in inverted) == -20


async def test_player_spreads_mouse_look_over_look_ms():
    clock = FakeClock()
    backend = RecordingInputBackend(clock=clock)
    player = TimelinePlayer(
        backend, counts_per_degree=10, look_step_ms=10, clock=clock, sleep=clock.sleep
    )
    start = clock()
    await player.play(build_timeline([LookAction(dyaw_deg=10)], 3000))
    moves = [(t - start, args) for t, name, args in backend.calls if name == "move_rel"]
    assert len(moves) == 10
    assert sum(args[0] for _, args in moves) == 100
    assert moves[-1][0] == pytest.approx(0.09)
    assert clock() - start == pytest.approx(0.1)


async def test_bridge_game_types_text_as_characters(bridge_env):
    clock, bridge, client = bridge_env
    game, backend = make_game(clock, client)
    await game.reset(ResetRequest(puzzle_id="p", bodies=[ASH, BIRCH]))
    backend.calls.clear()

    actions = [KeyAction(keys=["enter"]), TypeAction(text="r1!"), KeyAction(keys=["enter"])]
    result = await game.act(1, actions, 3000)

    typed = [args[0] for _, name, args in backend.calls if name == "type_char"]
    assert typed == ["r", "1", "!"]
    keys = [args[0] for _, name, args in backend.calls if name == "key_down"]
    assert keys == ["enter", "enter"]
    assert result.game_ms == 2 * (KEY_TAP_MS + KEY_GAP_MS) + 3 * TYPE_CHAR_MS


def test_unicode_units():
    assert unicode_units("a") == [0x61]
    assert unicode_units(chr(0x1F600)) == [0xD83D, 0xDE00]


def test_scan_codes():
    assert key_fields("w", up=False) == (0x11, 0x0008)
    assert key_fields("w", up=True) == (0x11, 0x000A)
    assert key_fields("up", up=False) == (0x48, 0x0009)
    from big_walk_eval.protocol import VALID_KEYS

    assert set(SCAN_CODES) == set(VALID_KEYS)


@pytest.mark.skipif(sys.platform == "win32", reason="checks the non-Windows guard")
def test_sendinput_refuses_non_windows():
    from server.input.sendinput import SendInputBackend

    with pytest.raises(RuntimeError, match="Windows only"):
        SendInputBackend()


# ------------------------------------------------------------------- helpers


async def test_record_spawns_yaml_parses_back():
    import yaml

    from big_walk_eval.protocol import BodySpawn

    game = FakeGame()
    state = await game.reset(reset_request())
    text = spawns_yaml(state, names=["Oak", "Pine"])
    spawns = [BodySpawn.model_validate(s) for s in yaml.safe_load(text)["spawns"]]
    assert [s.name for s in spawns] == ["Oak", "Pine"]
    assert spawns[0].position == (-5.0, 0.0, 0.0)


class TurningInput(RecordingInputBackend):
    def __init__(self, bridge: FakeBridge, cpd: float, invert: bool):
        super().__init__()
        self.bridge, self.cpd, self.invert = bridge, cpd, invert

    async def move_rel(self, dx: int, dy: int) -> None:
        body = self.bridge.bodies[self.bridge.active]
        body["yaw_deg"] += dx / self.cpd
        body["pitch_deg"] += (-dy if self.invert else dy) / self.cpd


@pytest.mark.parametrize("invert", [False, True])
async def test_calibrate_finds_counts_per_degree(bridge_env, invert):
    clock, bridge, client = bridge_env
    bridge.handle("spawn_bodies", {"n": 1})
    result = await calibrate(
        client, TurningInput(bridge, cpd=7.25, invert=invert), counts=600, sleep=clock.sleep
    )
    assert result.counts_per_degree == pytest.approx(7.25)
    assert result.pitch_counts_per_degree == pytest.approx(7.25)
    assert result.invert_mouse_y is invert
    assert bridge.bodies[1]["yaw_deg"] == pytest.approx(0)
