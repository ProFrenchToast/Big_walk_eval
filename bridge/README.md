# BigWalk.EvalBridge

A BepInEx 6 IL2CPP plugin. It lets the eval game server (`server/`) control the game over TCP. It needs [big-walk-practice](https://github.com/iameli/big-walk-practice) 0.6.0 for extra bodies and slot switching.

Status: skeleton. It has not been compiled. Every part past compile is **NEEDS GAME**.

## Build

The references are the same as in big-walk-practice's `Directory.Build.props`, plus `UnityEngine.ImageConversionModule` and `UnityEngine.ScreenCaptureModule`.

```powershell
dotnet build bridge\BigWalk.EvalBridge.csproj -c Release /p:GamePath="<r2modman profile base or game folder>"
```

Copy `bin\Release\BigWalk.EvalBridge.dll` to `BepInEx\plugins\BigWalk.EvalBridge\`. The load log line is `Loading [Big Walk — Eval Bridge 0.1.0]`.

To move the plugin into a fork of big-walk-practice, copy the `.cs` files to `mods/BigWalk.EvalBridge/`. Keep only the project properties and the two extra module references in the csproj.

## Game setup

- Run the game windowed at 1366 x 768. The screenshot is then 1:1 with what the model sees.
- In `com.bigwalk.practice.cfg`: set `MaxExtraBodies` to at least the number of agents minus 1, and set `ShowNameOverlay = false`.
- Host a lobby. The practice mod works only on the host.

## Threads

The TCP listener runs on a background thread and never touches Unity or Il2Cpp objects. Each request goes into a queue. `BridgeBehaviour.Update` runs it on the main thread. `Update` still runs at `Time.timeScale = 0`, so commands work while the game is paused. A command that needs more than one frame (switch, spawn, screenshot) returns an `IPending` that is polled once per frame.

## Protocol

One JSON object per line, UTF-8, on `127.0.0.1:47800`.

```
request:  {"id": 7, "cmd": "get_state", "args": {}}
response: {"id": 7, "ok": true, "result": {...}}
          {"id": 7, "ok": false, "error": "message"}
```

Slots are 1-based. Slot 1 is key `1` and practice index 0 (the original player).

| Command | Args | Result | State |
| --- | --- | --- | --- |
| `hello` | | `game_version`, `bridge_version`, `practice_version` | written |
| `pause` / `resume` | | `time_s` (scaled game time) | written |
| `get_state` | | `paused`, `active_slot`, `time_s`, `camera_vfov_deg`, `bodies: [{slot, position, yaw_deg, pitch_deg, held}]` | written, `held` is TODO(dump) |
| `switch_slot` | `slot` | `active_slot` | written, through practice mod reflection |
| `spawn_bodies` | `n` | `count` | written, through practice mod reflection |
| `teleport` | `slot`, `position`, `yaw_deg` | | written, `PlayerGrease.Teleport` |
| `screenshot` | `width`, `height` | `png_base64` | written, end-of-frame capture |
| `overview_shot` | `position`, `look_at`, `width`, `height` | `png_base64` | written, free camera |
| `events` | | `events: [{type, slot, t_ms, data}]` | queue written, game hooks TODO(dump) |
| `look` | `dyaw_deg`, `dpitch_deg` | | TODO(dump). Server fallback: `look_mode: mouse` |
| `load_snapshot` / `save_snapshot` | `name` | | TODO(dump). No fallback |
| `chat` | `slot`, `text` | | TODO(dump). Optional |
| `input` | `slot`, `op`, ... | | TODO(dump). Backend B only |

The Python side of this protocol is `server/bridge_client.py`. The tests in `tests/fake_bridge.py` use a fake bridge that speaks the same protocol.

## TODO(dump)

Run the Cpp2IL dump as the practice mod's `AGENTS.md` describes. Never commit the dump.

| What | Where | Grep |
| --- | --- | --- |
| Held item per hand, reward (gourd) class | `HeldItems.Read` in `Commands/StateReader.cs` | `rg -n "class PlayerHands\|class PlayerArms" out/dummy`, `rg -n "Grab\|Hold\|Gourd\|Reward" out/dummy/Assembly-CSharp` |
| Pickup, drop, reward spawn, puzzle done events | `GameEvents.Install` | `rg -n "void (Grab\|Pick\|Hold\|Release\|Drop)" out/dummy/Assembly-CSharp` |
| Exact camera turn | `Unfinished.Look` | `rg -n "class PlayerHead" -A 60 out/dummy/Assembly-CSharp` |
| Save and load | `Unfinished.LoadSnapshot` | `rg -n "class .*Save\|LoadGame\|SaveGame" out/dummy/Assembly-CSharp` |
| Text chat | `Unfinished.Chat` | `rg -n "class .*(Chat\|Texter)" out/dummy/Assembly-CSharp` |
| Rewired actions (Backend B) | `Unfinished.Input` | `rg -n "GetButton\|GetAxis" out/isil/Assembly-CSharp` |

## Risks to check first

1. **Hot-swap and grip (check 1).** The practice mod 0.6.0 does not freeze inactive bodies with `bypassUpdate`. It calls `ReplacePlayerForConnection` and makes the old body a remote body (`MakeRemote`). Test whether a remote body keeps its grip. With OS input (Backend A), the server also releases the mouse button while paused before a switch and presses it again after a switch back. Test that exact sequence.
2. **Spawning at `timeScale = 0`.** `spawn_bodies` runs while paused. The practice mod skips a spawn while `LocalPlayerFullyReady` is false; the command retries until it times out.
3. **Screenshot at `timeScale = 0`.** `WaitForEndOfFrame` must still fire while paused.
4. **Look direction after teleport.** `teleport` sets the body rotation. The camera may keep its old direction.
