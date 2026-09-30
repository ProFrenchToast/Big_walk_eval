# Big Walk Cooperation Eval: Harness Implementation Plan

Status: 2026-09-30. M0 to M5 and M7 are built and tested against FakeGame. M6 (the bridge mod) is a skeleton that has not been compiled. Section 15 lists what changed from this plan and why.

This document is a handoff. It gives the background, the decisions, the architecture, the interfaces, and an ordered build plan. A developer with no access to the game can build and test most of the Python code against a fake game. The parts that need the real game are marked **[NEEDS GAME]**.

Related planning doc (decisions and feasibility checklist): <https://claude.ai/code/artifact/e792197c-4a10-4f5c-b837-8a9935827ab1>

---

## 1. Goal

The eval measures whether LLM agents can cooperate to solve puzzles in the game *Big Walk* (House House, 2026). It also measures perspective taking: each agent sees only its own first-person view, so agents must describe what they see to each other.

- Each agent controls one player body.
- Each agent gets screenshots from its own body only.
- Agents talk through text chat. A message reaches only agents within range, like the in-game proximity chat.
- An episode succeeds when a body holds the puzzle reward (a "gourd") and all agents agree to end.

Big Walk puzzles often need two players to act at the same time. For example, one player holds a button while a partner takes the gourd. This is why the game is a good cooperation test, and it is also the main technical risk (see section 3).

## 2. Background on the game and the mods

### 2.1 The game

- Unity 6 (6000.3.x), compiled with IL2CPP. There is no managed `Assembly-CSharp.dll` to read directly.
- Networking uses Mirror. Voice uses Dissonance. Input uses Rewired.
- The game ships for Windows, macOS, and consoles. Not Linux. Proton is untested with the mods.
- There is no official mod support. The community uses BepInEx 6 bleeding-edge IL2CPP builds (be.755 or newer).

### 2.2 Community tools we use

| Tool | What we use it for | Link |
| --- | --- | --- |
| big-walk-practice | Spawns extra bodies on the host and hot-swaps control between them. This is the base of our approach. | <https://github.com/iameli/big-walk-practice> |
| Ramblers | Reference code only. It captures images from a bot's point of view and reads the hands state. We do not run it. | <https://github.com/benceruleanlu/Ramblers> |
| bigwalk-mods modding guide | How to dump the game with Cpp2IL, the plugin template, and IL2CPP pitfalls. | <https://github.com/dougwithseismic/bigwalk-mods/blob/main/docs/modding-guide.md> |
| Inspect AI | Eval framework for the agent side. | <https://inspect.aisi.org.uk/> |
| Puzzle walkthrough | Puzzle solutions, to pick puzzles and write scripted runs. | <https://www.keengamer.com/articles/guides/big-walk-complete-walkthrough-all-puzzle-solutions/> |

### 2.3 How big-walk-practice works

These facts come from its `NOTES-phase1.md` and README. They matter for the bridge mod design.

- Keybinds: `+` spawns a body and switches to it. `1` to `0` switch control to slots 1 to 10. `R` moves all inactive bodies to the active body. `F5`/`F9` save and restore a formation checkpoint. `G` toggles noclip. `F1` opens the config UI.
- Config file: `BepInEx\config\com.bigwalk.practice.cfg`. Settings include `SlotNames`, `MaxExtraBodies` (1 to 9), `NoDrowsy`, and `ShowNameOverlay`.
- A `PracticeController` is injected with `ClassInjector`. It spawns bodies with Mirror `NetworkServer.ReplacePlayerForConnection`, which copies the game's own `HouseNetworkManager.OnServerAddPlayer` flow.
- Each body is a `PlayerCharacter : NetworkBehaviour`. Useful members: `inputPlayer` (a `Rewired.Player`), `cameraTransform`, `PlayerCameraMinder`, `playerNetworking`, and the static list `PlayerCharacter.allPlayerCharacters`.
- To switch control, the mod sets `bypassUpdate`, `bypassLateUpdate`, and `bypassFixedUpdate` on the inactive bodies. It then enables exactly one camera, under the active body.
- It is MIT licensed. Its repo also has `AGENTS.md` with the build conventions (PowerShell 5.1, `scripts\build.ps1`, never commit decompiled code).

**Important consequence:** an inactive body does not run its `Update`. So it probably keeps its current grip, but we do not know yet. See section 3.

### 2.4 Inspect facts that affect the design

These facts come from `inspect_ai` 0.3.273 source.

- Inspect's built-in `computer()` tool runs its actions in a Linux sandbox with xdotool (`computer_sandbox()` in `inspect_ai/tool/_tools/_computer/_common.py`). We cannot use that backend, because the game runs on Windows.
- Providers swap in their **native** computer-use tool when `is_computer_tool_info()` returns true. That function checks two things only: the tool name is `"computer"`, and the parameter names equal this set: `action, coordinate, duration, region, scroll_amount, scroll_direction, start_coordinate, text, repeat, press_enter, actions`.
- **So a custom tool with the name `computer` and the same parameter names gets native binding.** Its `execute` can call our game server instead of the sandbox. This answers an open question from the planning doc. A quick check on 2026-09-30 confirmed the detection: a `@tool(name="computer")` with these parameter names gives `True`. A unit test must keep this true (see M2). A real model call must still confirm the end-to-end path.
- The Anthropic provider declares the native display as **1366 x 768**. Screenshots must be that size, and coordinates from the model are in that space.
- Newer Anthropic models use a "computer toolset" (`computer_toolset_20260801`) where each action is a separate member. Check how the provider maps those calls back to our tool's `action` argument.
- Models without native computer use see the tool docstring. So we can write our own docstring with Big Walk controls, and native models will not see it.

## 3. Main risk: simultaneous actions

Only one body has control at a time under hot-swap. Many puzzles need a body to keep holding something while another body acts.

Patrick is testing this by hand now (feasibility check 1). The result decides the action backend. Build the code so that the backend can change without changes to the Inspect side.

| Result of check 1 | Action backend |
| --- | --- |
| Pass: an inactive body keeps its grip and position | **Backend A (default):** hot-swap plus real OS input (Win32 `SendInput`) to the active body. |
| Fail, the grip drops | First try a small patch that keeps the grip input active on the inactive body. If that is not possible, use Backend B. |
| Fail, and the patch is not possible | **Backend B:** keep all bodies active and inject input per body through Rewired. Each body has its own `inputPlayer`, so the bridge mod can attach a Rewired `CustomController` to each one. This also allows true simultaneous action. |
| Backend B fails | Ramblers-style puppets through the remote-player motor, or one game client per agent (N Steam accounts). Last resort. |

Backend B is a new idea from reading the practice mod notes. It is not in the planning doc yet. It is worth a spike even if check 1 passes, because it removes the OS input layer.

## 4. Decisions so far

| Area | Decision |
| --- | --- |
| Bodies | big-walk-practice spawns one body per agent. The harness hot-swaps control each turn. |
| Placement | The bridge mod teleports each body to a spawn point from the puzzle config. The formation checkpoint (`F5`/`F9`) is a manual fallback. |
| Actions | Computer-use style actions. Real OS input to the active body (Backend A). Mouse-look and held keys are supported. |
| Timing | The game is paused between turns. Game time moves only while the active agent's actions run. |
| Observation | One screenshot from the active body's own camera, at 1366 x 768. |
| Communication | A `say` tool. The harness delivers each message only to agents within range. Optional echo into in-game chat for replays. |
| Audio | Skip puzzles that need sound. |
| Ending | Each agent has an `end_episode` tool. The episode ends when all agents have an active vote. |
| Scoring | The bridge mod reads the held item of each body. Success means a body holds the gourd. A screenshot judge is a spot check only. |
| Reset | One save snapshot per puzzle, loaded before each sample. |
| Order of work | A scripted run with no LLM comes before the first agent run. This keeps harness bugs apart from agent failures. |

## 5. Architecture

Three components. They talk over JSON.

```
+---------------------------- Windows machine with GPU ----------------------------+
|                                                                                  |
|  Big Walk.exe                                                                    |
|   + BepInEx 6 IL2CPP                                                             |
|   + big-walk-practice   (spawn bodies, hot-swap)                                 |
|   + BigWalk.EvalBridge  (NEW, C#: pause, state, teleport, screenshot, events)     |
|          ^                                                                        |
|          | line-delimited JSON over TCP, 127.0.0.1:47800                         |
|          v                                                                        |
|  game server  (NEW, Python, FastAPI)                                             |
|   - owns the only connection to the bridge mod                                    |
|   - sends OS input with SendInput (Backend A)                                     |
|   - runs one "act" as: switch slot -> resume -> play inputs -> pause -> capture   |
|                                                                                  |
+-------------------------------------^--------------------------------------------+
                                      | HTTP JSON, port 47801 (LAN or SSH tunnel)
+-------------------------------------v--------------------------------------------+
|  harness (NEW, Python, Inspect AI). Can run on the same machine or another one.  |
|   - task, dataset (puzzle configs), round-robin solver                           |
|   - tools: computer (native binding), say, end_episode                           |
|   - chat routing by distance, vote tracking, scorer                              |
|   - GameClient interface with two implementations: HttpGame and FakeGame          |
+----------------------------------------------------------------------------------+
```

The harness uses a `GameClient` interface only. `FakeGame` implements the same interface in pure Python, so the whole harness runs in CI with Inspect's `mockllm` model.

### 5.1 Turn loop

```
reset(sample)                      # load snapshot, spawn and place bodies, pause
while not all_votes_active and turn < max_turns:
    agent = agents[turn % n]
    game.switch(agent.slot)        # while paused
    obs = game.screenshot()
    inbox = chat.deliver(agent)    # messages in range since this agent's last turn
    append user message to agent history: header text + inbox + screenshot
    output = model.generate(agent.history, tools)
    for each tool call in output:
        computer -> game.act(slot, [action], budget)   # resume, input, pause
        say      -> chat.post(sender, text, positions from game.state())
        end_episode -> votes[agent] = True / False
    turn += 1
score from game.state(): any body holds the gourd
```

Rules for the loop:

- One turn is one `generate` call plus its tool calls. Then the next agent takes a turn.
- Cap the unpaused game time per turn (`max_game_ms_per_turn`, start at 3000). Cap tool calls per turn (start at 6).
- A vote stays active until the same agent withdraws it. An agent with an active vote still gets turns, so it can reply to chat or keep holding a button.
- Each tool result for `computer` returns a new screenshot, because native computer-use models expect this.
- Trim old screenshots from each history before `generate`. Keep the last 3 images per agent. Replace older images with the text `[old screenshot removed]`.

### 5.2 Timing

The game server makes game time independent of model latency:

1. The game is paused (`Time.timeScale = 0`) whenever no action runs.
2. For one `act` call, the server switches slot, resumes, plays the input timeline, and pauses again.
3. The server returns the elapsed game time and a new screenshot.

Unity keeps rendering at `timeScale = 0`, and `Update` still runs with `deltaTime = 0`. So a slot switch and a screenshot work while paused. Feasibility check 3 must confirm that physics, props, and puzzle timers stop and restart cleanly.

## 6. Interfaces

Define these first. The three components can then be built in parallel.

### 6.1 `GameClient` (Python, harness side)

```python
class BodyState(BaseModel):
    slot: int
    name: str
    position: tuple[float, float, float]
    yaw_deg: float
    held: list[HeldItem]          # one entry per hand that holds something

class HeldItem(BaseModel):
    hand: Literal["left", "right"]
    item_id: str
    item_type: str                # game class or prefab name
    is_reward: bool               # true for the puzzle gourd

class GameState(BaseModel):
    paused: bool
    active_slot: int
    bodies: list[BodyState]
    events: list[GameEvent]       # since the last call, e.g. reward_spawned, item_picked_up

class ActResult(BaseModel):
    screenshot_png: bytes         # 1366 x 768
    game_ms: int                  # unpaused time used
    truncated: bool               # true if the time budget cut the action short
    events: list[GameEvent]

class GameClient(Protocol):
    async def reset(self, puzzle: PuzzleConfig, bodies: list[BodySpawn]) -> GameState: ...
    async def switch(self, slot: int) -> None: ...
    async def screenshot(self) -> bytes: ...
    async def act(self, slot: int, actions: list[Action], budget_ms: int) -> ActResult: ...
    async def state(self) -> GameState: ...
    async def echo_chat(self, slot: int, text: str) -> None: ...   # optional, for replays
    async def overview_shot(self) -> bytes | None: ...             # optional free-cam image
```

`Action` is a pydantic model of one computer action (section 7).

### 6.2 Game server HTTP API (Windows side)

| Method and path | Body | Returns |
| --- | --- | --- |
| `GET /health` | | game version, bridge connected, mod versions |
| `POST /reset` | `{puzzle_id, snapshot, bodies: [{slot, name, position, yaw_deg}]}` | `GameState` |
| `POST /switch` | `{slot}` | `{ok}` |
| `GET /screenshot` | | PNG, base64 |
| `POST /act` | `{slot, actions: [...], budget_ms}` | `ActResult` |
| `GET /state` | | `GameState` |
| `POST /chat_echo` | `{slot, text}` | `{ok}` |
| `POST /overview_shot` | `{position, look_at}` | PNG, base64 |
| `POST /capture/start` | `CaptureRequest {episode_id, fps, width, height, slots}` | `{ok}` |
| `POST /capture/stop` | | `{info: CaptureInfo \| null}` |

Put the pydantic models in one shared module (`big_walk_eval/protocol.py`). The game server imports the same module, so the two sides cannot drift.

### 6.3 Bridge mod protocol (C#, inside the game)

Line-delimited JSON over TCP on `127.0.0.1:47800`. One request per line, one response per line, with an `id` field. Commands:

| Command | Effect | Notes |
| --- | --- | --- |
| `pause` / `resume` | Sets `Time.timeScale` to 0 or 1. | Run on the Unity main thread (see 8.2). |
| `get_state` | Returns bodies, positions, yaw, held items, paused flag, active slot. | Held items need a class from the dump. |
| `switch_slot {slot}` | Calls the practice mod's switch logic. | Fallback: the game server presses the slot key with `SendInput`. |
| `spawn_bodies {n}` | Makes sure there are n bodies. | Calls the practice mod or its spawn pattern. |
| `teleport {slot, position, yaw}` | Moves the whole rigidbody and sets yaw. | |
| `screenshot {width, height}` | Captures the active camera at end of frame and returns JPEG or PNG as base64. | `ScreenCapture.CaptureScreenshotAsTexture`, then scale. |
| `load_snapshot {name}` / `save_snapshot {name}` | Loads or saves the puzzle save file. | Save file location and load path are unknown. |
| `events` | Returns and clears the event queue. | Harmony postfixes on reward spawn and pickup. |
| `look {dyaw, dpitch}` | Optional. Turns the active camera by an exact angle. | Better than calibrated mouse movement if it works. |
| `capture_start {directory, fps, width, height, slots}` / `capture_stop` | Renders one hidden camera per body at each 1/fps step of game time. Sends the frames to ffmpeg. | For replay videos. See 15.1 item 13. |

## 7. Agent tools

### 7.1 `computer` (native binding)

- Register with the name `computer` and the exact parameter names in section 2.4.
- Write our own docstring for non-native models. List the Big Walk controls in it.
- Supported actions and their mapping:

| Action | Mapping in the game |
| --- | --- |
| `screenshot` | Return the current view. No game time passes. |
| `key` | Tap a key for 50 ms of game time. `repeat` is allowed. |
| `hold_key` | Hold keys for `duration` seconds of game time. This is how an agent walks (for example `w` for 1 s). Cap at the turn budget. |
| `mouse_move` | **Look toward the pixel.** Turn the camera so that the pixel at `coordinate` moves to the screen center. The server converts the pixel offset to yaw and pitch with the camera field of view, then to relative mouse counts with a calibration factor. |
| `left_mouse_down` / `left_mouse_up`, `left_click`, `right_click` | Mouse buttons. Big Walk uses these for hand actions (confirm the exact controls). |
| `wait` | Let game time pass with no input. Cap at the turn budget. |
| `scroll` | Pass through as mouse wheel, if the game uses it. |
| `type`, `zoom`, `cursor_position`, `left_click_drag`, `double_click`, `triple_click`, `middle_click`, `back_click`, `forward_click`, `open_web_browser`, `navigate` | Return an error text: "not available in this game, use `say` to talk". |

"Look toward the pixel" makes absolute `mouse_move` useful in a first-person game. Models already point at things by pixel, so this uses a skill they have.

Unit conversion for `mouse_move`, with the default horizontal field of view `hfov` from config:

```
f      = (1366 / 2) / tan(hfov / 2)
dyaw   = atan((x - 683) / f)
dpitch = atan((y - 384) / f)
counts = angle_deg * counts_per_degree      # calibrate once per machine
```

Write a calibration script (M5) that turns by a known count, reads the yaw from `get_state`, and computes `counts_per_degree`.

### 7.2 `say(message: str)`

- Records the message with the sender's position at that moment.
- Delivers it to each other agent at the start of that agent's next turn, if the distance between the two bodies is at most `chat_range_m` at send time.
- Returns only the text "sent". It does not tell the sender who heard the message. Agents must find this out themselves.
- Optionally echoes the message into in-game chat for replays. Spawned bodies probably share one name in-game chat, so the harness is the source of truth.

### 7.3 `end_episode(withdraw: bool = False)`

- Sets or clears this agent's vote.
- Returns the text "vote recorded". It does not tell the agent how many other votes exist. Agents must ask each other through `say`.
- The loop ends when all agents have an active vote at the end of a turn.

### 7.4 System prompt (draft, one per agent)

Content, in order:

1. You are one of N players in the game Big Walk. Your name is `<name>`.
2. The goal: work with the other players to solve the puzzle near you and get the reward, a gourd. At least one player must hold the gourd at the end.
3. You see only your own first-person view. The other players see different views.
4. You can talk only with `say`. Players far away do not hear you.
5. The game pauses while you think. Time moves only while your actions run.
6. Controls (fill in after Patrick confirms them).
7. When the gourd is held and you agree the task is done, call `end_episode`. The episode ends only when all players have called it.

Keep puzzle hints out of the prompt. Put the puzzle name and a one-line location hint in sample metadata only, for ablations.

## 8. Implementation notes per component

### 8.1 Harness (Python, Inspect)

- Python 3.11+. Use `uv` and a `pyproject.toml`. Use `ruff` and `pytest` with `pytest-asyncio`.
- Do not use `react()`. It runs one agent until it submits. Write a custom `@solver` that holds N message histories and calls `get_model().generate()` for one agent at a time. Use `inspect_ai.model.execute_tools` to run tool calls.
- Store per-sample data in the sample store: votes, chat log (sender, recipients, text, turn), per-turn game time, and events.
- Put each agent's full history in the transcript with `transcript().info` or spans, so the log viewer shows each agent separately.
- Task parameters: `game_url`, `puzzles` (list of IDs or "all"), `n_agents`, `max_turns`, `max_game_ms_per_turn`, `max_tool_calls_per_turn`, `chat_range_m`, `backend` (`http` or `fake`).
- Set `max_samples=1` for the HTTP backend. One game instance runs one sample at a time.
- Scorer returns a `Score` with value `C` or `I` and metadata: `gourd_holder`, `votes`, `turns`, `total_game_ms`, `n_messages`, `ended_by_vote` (true) or `ended_by_limit` (false), and `false_end` (all voted but no gourd held).

### 8.2 Game server (Python, Windows)

- FastAPI plus uvicorn. Bind to `127.0.0.1` by default. Use an SSH tunnel to reach it from another machine. Do not expose it on a public interface.
- `SendInput` with `ctypes`, or the `pydirectinput` package. Use scan codes, not virtual keys, because many games read scan codes. Use `MOUSEEVENTF_MOVE` with relative counts for look.
- The game window must have focus for OS input. Before each `act`, bring the game window to the foreground and check it.
- Split the mouse movement into small steps over about 100 ms. One large jump can be clamped by the game.
- One asyncio lock around every call that touches the bridge mod or the input. Only one action runs at a time.
- Put the input code behind an `InputBackend` interface with `SendInputBackend` (A) and `BridgeInputBackend` (B, input through the mod). Unit-test the timeline builder with a fake backend. The timeline builder converts actions to timed key and mouse events.

### 8.3 Bridge mod (C#, BepInEx 6 IL2CPP)

- Follow the conventions of big-walk-practice: `net6.0`, `BasePlugin`, `ClassInjector` for a `MonoBehaviour` that runs each frame, Harmony for patches. Consider adding it as a new mod in a fork of that repo, so it reuses its build scripts and interop references.
- The TCP listener runs on a background thread. Unity APIs work only on the main thread. So put each request in a concurrent queue, run it in the injected `Update`, and complete a `TaskCompletionSource` with the response.
- `Update` still runs at `timeScale = 0`, so the queue still drains while paused. Use unscaled time for any wait inside the mod.
- Class names that need the dump (Cpp2IL `dummydll` plus `ilspycmd`, as in the modding guide): the hands or grab component, the gourd or reward class, the puzzle completion method, and the save or load entry point. Grep the dump for `Hand`, `Grab`, `Hold`, `Gourd`, `Reward`, `Puzzle`, `Save`. Mark each unknown with `// TODO(dump):` and the grep to run.
- Never commit decompiled game code. Add `out/`, `bin/`, `obj/` to `.gitignore`.
- **[NEEDS GAME]** for everything past compile.

### 8.4 FakeGame (Python, for tests)

A small 2D world that implements `GameClient`. It needs just enough rules to test the loop:

- Bodies with positions and yaw. `hold_key w` moves forward at a fixed speed. `mouse_move` turns.
- One pressure plate, one gate, and one gourd. The gate is open only while a body stands on the plate. A body can take the gourd only through the open gate. This is a real two-player puzzle in miniature.
- `screenshot` draws a simple top-down or text image with Pillow at 1366 x 768.
- Deterministic for a given seed.

With this, `mockllm` runs and a scripted policy can test the solver, chat routing, votes, limits, and the scorer in CI.

## 9. Puzzle config format

One YAML file per puzzle in `puzzles/`:

```yaml
id: green_structure_switches        # candidate, not confirmed
title: Green Structure switches
area: opening
needs_sound: false
min_agents: 2
snapshot: saves/green_structure_switches    # on the Windows machine
spawns:                                      # record these in the game with a helper
  - {slot: 1, name: Ash,   position: [0.0, 0.0, 0.0], yaw_deg: 0}
  - {slot: 2, name: Birch, position: [0.0, 0.0, 0.0], yaw_deg: 0}
reward_item_type: TODO(dump)
max_turns: 60
notes: "Location hint for ablations only. Not shown to agents."
```

Candidates for the first puzzle: Blue Room pegboard, Green Structure switches, Mechanical Arm, Cave and Telescope. Pick one that needs two players and no sound. Patrick decides.

Add a helper command in the game server, `record_spawns`, that reads the current body positions from `get_state` and prints the `spawns` block.

## 10. Repo layout

```
big_walk_eval/
  CLAUDE.md
  docs/IMPLEMENTATION_PLAN.md
  pyproject.toml
  src/big_walk_eval/
    protocol.py          # pydantic models shared by harness and game server
    task.py              # @task big_walk_coop
    dataset.py           # puzzles/*.yaml -> Samples
    solver.py            # round-robin multi-agent solver
    chat.py              # message routing by distance
    scorer.py
    prompts.py
    tools/computer.py    # native-bound computer tool shim
    tools/say.py
    tools/end_episode.py
    game/client.py       # GameClient protocol
    game/http_game.py    # client for the game server
    game/fake_game.py    # FakeGame
  server/                # Windows only
    app.py               # FastAPI
    bridge_client.py     # TCP JSON client for the bridge mod
    input/sendinput.py
    input/timeline.py
    calibrate.py
    record_spawns.py
  bridge/                # C# BepInEx plugin, Windows only
    BigWalk.EvalBridge.csproj
    Plugin.cs
    BridgeServer.cs
    Commands/*.cs
  scripts/
    scripted_run.py      # drives FakeGame or the real game with a fixed policy
  puzzles/*.yaml
  tests/
```

## 11. Build plan

Do the milestones in order. Each one ends with passing tests. M1 to M4 and M7 need no game and no Windows.

| # | Milestone | Done when |
| --- | --- | --- |
| M0 | Scaffold: `pyproject.toml`, `uv`, ruff, pytest, `.gitignore` for Python and C#, package skeleton. | `uv run pytest` passes with a placeholder test. |
| M1 | `protocol.py`, `GameClient`, `FakeGame`. | Tests: plate opens gate, gourd pickup works only through the open gate, determinism. |
| M2 | Tools: `computer` shim, `say`, `end_episode`. | Test: build `ToolInfo(name=td.name, description=td.description, parameters=td.parameters)` from `td = ToolDef(computer_tool())`, then `is_computer_tool_info(...)` is true. Test: unsupported actions return the error text. Test: `mouse_move` angle math. |
| M3 | Round-robin solver, chat routing, votes, limits, screenshot trimming. | Tests with a scripted fake model: chat in range arrives, chat out of range does not, votes end the loop, withdraw works, `max_turns` stops the loop. |
| M4 | Dataset, scorer, task. | `inspect eval src/big_walk_eval/task.py -T backend=fake --model mockllm/model` runs. A scripted policy on FakeGame scores `C`. |
| M5 | Game server with `SendInputBackend`, timeline builder, bridge client, calibration and spawn helpers. | Unit tests pass with a fake bridge and a fake input backend. The server starts on Linux in fake mode. **[NEEDS GAME]** for real input. |
| M6 | Bridge mod skeleton: TCP server, main-thread queue, `pause`, `resume`, `get_state` (positions only), `teleport`, `screenshot`, `switch_slot`. `TODO(dump)` markers for held items, events, snapshots. | It compiles against the interop references. **[NEEDS GAME]** to run. |
| M7 | `scripts/scripted_run.py`: a fixed two-body solution through the real turn loop, on FakeGame first. | It solves the FakeGame puzzle. Later, Patrick runs it on the real puzzle. |
| M8 | **[NEEDS GAME]** First real run: scripted, then two agents on one puzzle. | Patrick runs it. |

After M8: more puzzles, more agents, and ablations (see section 13).

## 12. What Patrick must do or confirm (needs the game)

- [ ] Feasibility check 1: does an inactive body keep holding a button or an object after a hot-swap? This picks Backend A or B.
- [ ] Checks 2 to 9 from the planning doc: idle bodies stay awake, pause and step, per-agent view after a switch, input injection, hands-state readout, placement, reset, target machine.
- [ ] Which machine runs the game (Windows with a GPU, or Proton).
- [ ] The first puzzle.
- [ ] The Big Walk controls: which keys and buttons walk, jump, crouch, grab with each hand, and open chat.
- [ ] Run the Cpp2IL dump locally and give class names for the hands component, the gourd, puzzle completion, and save and load. Do not commit the dump.
- [ ] Pin the game version and turn off Steam auto-updates. Record the game build number in `CLAUDE.md`.
- [ ] Fill in the Big Walk controls in `src/big_walk_eval/prompts.py` (`BIG_WALK_CONTROLS`, marked `TODO(controls)`). Check that no game control uses a practice-mod hotkey (`1` to `0`, `+`, `=`, `R`, `G`, `F1` to `F3`, `F5`, `F9`). The `computer` tool rejects those keys.
- [ ] In check 1, test the exact sequence of section 15.1 item 5.

## 13. Later work (not in scope now)

- Ablations: pixels plus low-level actions, pixels plus semantic actions (`walk_to`, `pick_up`, as in Ramblers), and text state plus semantic actions. This separates perception and motor skill from cooperation.
- Chat on or off, and chat range as a variable.
- More agents (up to 4) and harder puzzles.
- Audio puzzles, with audio-capable models or audio encoded as text.
- Perspective-taking probes: ask an agent what a partner can see, and compare with the partner's real screenshot.

## 14. Open questions

- Does the Anthropic computer toolset (`computer_toolset_20260801`) map calls back into our `action` argument without changes? **Partly answered.** In inspect_ai 0.3.273, `anthropic.py` sends each toolset member call to the tool named `computer` with `action = <member name>` and the member input as the other arguments. So our shim receives the calls. Not checked: whether the member input names match the legacy names (`text`, `coordinate`, `duration`). The Anthropic SDK is not installed in CI. A real model call must still confirm this.
- Does in-game text chat show a separate name for each spawned body? This matters only for the echo feature.
- The right value for `max_game_ms_per_turn`. Start at 3000 and tune after the scripted run.
- Does `timeScale = 0` stop every puzzle timer? Some timers can use unscaled time.

## 15. Implementation status and changes from this plan

### 15.1 Changes

1. **`GameClient.reset` takes a `ResetRequest`**, not `(puzzle, bodies)`. The game server is then a thin HTTP layer over any `GameClient`. `PuzzleConfig.reset_request(n_agents)` builds the request.
2. **The timeline builder is in `src/big_walk_eval/timeline.py`**, not `server/input/timeline.py`. FakeGame and the game server play the same timed events, so budgets and truncation are the same in tests and in the game. The fixed durations (key tap, click, look) are constants in `protocol.py`.
3. **A turn can have more than one generate call.** A turn is a header (chat heard, fresh screenshot), then up to `max_generates_per_turn` (default 6) generate calls with their tool calls. The turn ends when the model replies without a tool call, or when the tool-call cap or the game-time budget is used up. Reason: native computer-use models usually make one action per reply and wait for the screenshot. With one generate call per turn, each turn is one action, and every action waits for all other agents. Set `-T max_generates_per_turn=1` for the behavior of section 5.1.
4. **The harness does the look-toward-pixel math.** The `computer` tool converts the pixel to a `LookAction(dyaw_deg, dpitch_deg)`. The server converts the angle to mouse counts, or sends it to the bridge `look` command. The field of view comes from `Camera.fieldOfView` in `get_state` when the bridge reports it, else from `-T hfov_deg`.
5. **Held mouse buttons are per body.** `left_mouse_down` stays held across turns until `left_mouse_up`. With OS input (Backend A), the server releases the buttons before a switch (while paused) and presses the new body's buttons again after the switch. Check 1 must test this exact sequence: body A grips, the button is released at the OS while paused, control switches to body B, B acts, control switches back, the button is pressed again.
6. **The practice mod switches differently than section 2.3 says.** big-walk-practice 0.6.0 does not set `bypassUpdate` on inactive bodies. It calls `NetworkServer.ReplacePlayerForConnection` and makes the old body a remote body (`MakeRemote`). So check 1 tests whether a *remote* body keeps its grip.
7. **Practice-mod hotkeys are blocked.** The practice mod reads `1` to `0`, `+`, `R`, `F5`, `F9`, and `G` with `Input.GetKeyDown`. If an agent pressed `r`, every body would teleport. The `computer` tool and the game server reject these keys, and `F1` to `F3` (config UI, dev menu, free cam).
8. **Right hand.** Native computer use has no `right_mouse_down`. The tool accepts `left_mouse_down` with `text="right"`, and `right_mouse_down` / `right_mouse_up` for models that read the docstring. Confirm with the real controls.
9. **One episode at a time on the HTTP backend.** `Task` has no `max_samples` option, so the solver holds a lock for the whole episode. `--max-samples 1` is still a good idea.
10. **`puzzle_game` task parameter.** `-T backend=http -T puzzle_game=fake` runs FakeGame puzzles on a server started with `--fake`. Use this to test the network path before the game.
11. **The bridge `spawn_bodies` waits 40 frames after the last spawn.** The practice mod moves a new body back to its formation spot 30 frames after it spawns, which would undo a teleport.
12. **Each episode records its inputs for replays.** `RecordingGame` (`src/big_walk_eval/replay.py`) wraps the `GameClient`. It records each reset, switch, and act in order, with the game time. The tools add `say` messages and votes. After each act, it reads the state of all bodies as a checkpoint. The events of that read go back to the harness on the next call, so no event is lost. The solver puts the recording in `EpisodeLog.replay`. Screenshots are not in the recording, because the Inspect log has them. `scripts/replay.py` sends the recorded inputs to a fresh game and shows the drift from each checkpoint. FakeGame replays with zero drift. **[NEEDS GAME]** Measure the drift on the real game. If the drift is large, the bridge `teleport` can move each body to its checkpoint during a playback. A smooth video also needs frames during an act, not only after it. That needs a bridge command that captures frames at a fixed game-time step.
13. **Per-agent video.** With `-T capture=true`, the game records each body's own view in one run. We do not replay the episode once per agent. Under hot-swap the camera follows the control, and each replay on the real game can drift in a different way. So the N videos would not show the same episode. `CaptureRequest` asks the game to write one JPEG per body for each 1/fps step of game time. Frames are only made while game time runs, so the pauses between actions are not in them. The game writes the frames on its own machine, to `<capture_dir>/<episode_id>/slot<N>/`, with `capture.json` (a `CaptureInfo`). The solver starts the capture after the reset and puts the `CaptureInfo` in `EpisodeLog.capture`. The recording gets a `capture` step, so `src/big_walk_eval/video.py` can match frames to acts and chat by game time. `scripts/make_video.py` makes the grid video. FakeGame renders every body with its raycast view. The bridge (`Commands/BodyCapture.cs`) renders one extra camera per body and sends raw frames to one ffmpeg process per body. **[NEEDS GAME]**: whether `cameraTransform` follows the head of a body that is not active, the layer that hides a body's own head from its camera (`TODO(dump)`), and the cost of N cameras. If the capture slows the live run too much, run it during a playback instead, with `Time.captureDeltaTime`.

### 15.2 Status per milestone

| # | State |
| --- | --- |
| M0 | Done. CI: ruff, format check, pytest on Python 3.11. |
| M1 | Done. FakeGame has a raycast first-person view, so look-toward-pixel is true in FakeGame too. |
| M2 | Done. A test checks `is_computer_tool_info` on the shim. |
| M3 | Done. Tests use `mockllm` with `ScriptedPolicy` (`src/big_walk_eval/scripted.py`). |
| M4 | Done. `inspect eval big_walk_eval/big_walk_coop --model mockllm/model` runs. The scripted solution scores C. |
| M5 | Done except real input. Tests use a TCP fake bridge. `SendInputBackend` is **[NEEDS GAME]**. |
| M6 | Skeleton. Syntax-checked, not compiled. `TODO(dump)`: held items, events, look, snapshots, chat, Backend B input. See `bridge/README.md`. |
| M7 | Done on FakeGame, in process and over HTTP. `scripts/solutions/real_puzzle.yaml.example` is the template for the real puzzle. |
| M8 | Not started. **[NEEDS GAME]** |

### 15.3 Gaps that block a real scored run

- `HeldItems.Read` in the bridge returns nothing until the hands class is known. The scorer then never sees a held gourd.
- `load_snapshot` is not written. Until it is, leave `snapshot` empty and reset the puzzle by hand.
- The Big Walk controls in the system prompt are a draft.
