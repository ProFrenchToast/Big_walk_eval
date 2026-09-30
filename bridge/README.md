# BigWalk.EvalBridge

A BepInEx 6 IL2CPP plugin. It lets the eval game server (`server/`) control the game over TCP. It needs [big-walk-practice](https://github.com/iameli/big-walk-practice) 0.6.0 for extra bodies and slot switching.

Status (2026-09-30): compiled and tested in game 1.5.1 2608271531 (Unity 6000.3.17f1) with BepInEx 6.0.0-be.788. A scripted three-body run (`scripts/solutions/footy_walkabout.yaml`) scores C through the full harness, and video capture of every body's view works (2026-10-01). Still missing: save snapshots, the exact `look` command, in-game chat, Backend B input.

## One-time setup

1. Install BepInEx 6 bleeding edge, Unity IL2CPP win-x64, be.755 or newer, into the game folder (we used be.788 from <https://builds.bepinex.dev/projects/bepinex_be>). Launch the game once: BepInEx downloads the Unity base libraries and writes `BepInEx\interop\` (about 150 assemblies). The build compiles against these.
2. Put `BigWalk.Practice.dll` (<https://github.com/iameli/big-walk-practice/releases/latest/download/BigWalk.Practice.dll>) in `BepInEx\plugins\BigWalk.Practice\`. Optional: build `BigWalk.SkipIntro` from the same repo to skip the splash and microphone screens.
3. In `BepInEx\config\com.bigwalk.practice.cfg`: `MaxExtraBodies` at least agents minus 1 (default 9), `ShowNameOverlay = false` (default).
4. Run the game once windowed at 1366 x 768 (Settings, or launch with `-screen-fullscreen 0 -screen-width 1366 -screen-height 768` one time). Unity keeps the size in the registry. Do not keep those flags: the game reads its command line as a join address.
5. For video capture (PR #2), install ffmpeg. Put it on `PATH`, or set `FfmpegPath` in `com.bigwalk.evalbridge.cfg`.
6. Optional: `InstantFlushing = true` under `[Logging.Disk]` in `BepInEx\config\BepInEx.cfg`, so `BepInEx\LogOutput.log` is current.

## Build and deploy

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File bridge\deploy.ps1 [-GamePath <game folder>]
```

It builds, stops the game, copies `bin\Release\BigWalk.EvalBridge.dll` to `BepInEx\plugins\BigWalk.EvalBridge\`, starts the game through Steam, and waits until the bridge listens. Start the game through Steam (`steam.exe -applaunch 1478500`), not with `Big Walk.exe`: a direct launch loads the bridge, and then Steam restarts the game, which kills that first bridge. The load log line is `Loading [Big Walk — Eval Bridge 0.1.0]`.

The game is then at the title screen. The game server hosts a walk on the first `/reset` (`auto_host` in the server config), or run `uv run python -m server.host_walk`.

## Threads

The TCP listener runs on a background thread and never touches Unity or Il2Cpp objects. Each request goes into a queue. `BridgeBehaviour.Update` runs it on the main thread. `Update` still runs at `Time.timeScale = 0`, so commands work while the game is paused. A command that needs more than one frame (switch, spawn, screenshot) returns an `IPending` that is polled once per frame. A watchdog in `Update` restarts the listener if its thread dies.

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
| `hello` | | `game_version`, `bridge_version`, `practice_version` | tested |
| `pause` / `resume` | | `time_s` (scaled game time) | tested |
| `get_state` | | `paused`, `active_slot`, `time_s`, `camera_vfov_deg`, `bodies: [{slot, position, yaw_deg, pitch_deg, held, pose}]` | tested. `held` is `PlayerHands.heldProp` (one per body). `pose`: crouch, sitting, jump, arm pointing and waving |
| `switch_slot` | `slot` | `active_slot` | tested, about 0.04 s while paused |
| `spawn_bodies` | `n` | `count` | tested, while paused |
| `teleport` | `slot`, `position`, `yaw_deg` | | tested. See "Teleports" below |
| `place_prop` | `item_type`, `position`, `near`? | `item_id`, `item_type`, `is_reward`, `moved_m` | tested. Moves the nearest prop of that type |
| `screenshot` | | `png_base64`, `width`, `height` | tested, about 0.12 s while paused |
| `events` | | `events: [{type, slot, t_ms, data}]` | tested: `switched`, `item_picked_up`, `item_dropped`. `reward_state` (gourd) is hooked but not seen yet |
| `controls` | | keyboard and mouse bindings per game action, from Rewired | tested |
| `menu` | `action`: `status`, `title_host`, `new_game`, `load_save {name}`, `host_confirm {name}`, `player_count {n}` | `open_menus`, `hosting`, `local_player_ready` | tested. `server/host_walk.py` drives it |
| `list_props` | `slot`?, `radius`?, `limit`? | props near a body, nearest first | tested. For writing puzzle files |
| `debug_practice`, `debug_body {slot}` | | practice slot table; every position the game keeps for a body | tested. For debugging |
| `overview_shot` | `position`, `look_at` | `png_base64` (null without a position) | not supported, see "Screenshots" |
| `look` | `dyaw_deg`, `dpitch_deg` | | TODO(dump). The server uses `look_mode: mouse` |
| `load_snapshot` / `save_snapshot` | `name` | | TODO(dump). `place_prop` covers simple cases |
| `chat` | `slot`, `text` | | TODO(dump). Optional. `PlayerTexter` is the lead |
| `capture_start` | `directory`, `fps`, `width`, `height`, `slots` | | tested. One camera per body, frames to ffmpeg. See `Commands/BodyCapture.cs` and "Screenshots" below |
| `capture_stop` | | `frames`, `start_time_s` | tested |
| `input` | `slot`, `op`, ... | | TODO(dump). Backend B only |

The Python side of this protocol is `server/bridge_client.py`. The tests in `tests/fake_bridge.py` use a fake bridge that speaks the same protocol.

## What we learned in the game

- **Controls** (from `controls`): WASD move, Shift run, Space jump, Ctrl crouch (hold), Z sit (toggle), Q and E wave (hold), Enter text chat, V mute. Left mouse is "use" (pick up, press), right mouse is "drop". There are no per-hand buttons: a body carries one prop in both hands.
- **Check 1 (hot-swap), for carried props: passes.** A body keeps its prop while other bodies act, because carrying is game state, not a held button. A held "use" button (left arm pointing) also comes back after a switch, because the server presses it again. Not tested yet: holding down a world switch while another body acts.
- **Pause:** `timeScale = 0` stops movement. Rendering, switching, spawning, and screenshots all work while paused.
- **Mouse look:** 25 counts per degree at the default sensitivity, no Y inversion, positive pitch looks down. The camera has a vertical FOV of 90 degrees, so 121.3 degrees horizontal at 1366 x 768.
- **Teleports:** teleport a body while it is the local (active) body, then let the game run for about 1.5 s. Otherwise the next switch puts the body back where the network last saw it (0.3 s is not enough). `mover.ResetPosition()` in the practice mod's switch also restores a position cache that only updates in `FixedUpdate`. `BridgeGame.reset` does this per body.
- **Screenshots:** `EncodeToPNG`, and every other call that returns a Unity byte array, fails in this interop build ("Instances of abstract classes cannot be created" in `BlittableArrayWrapper.Unmarshal`). `screenshot` uses `ScreenCapture.CaptureScreenshot` to a temp file instead. Video capture reads its `Texture2D` through the pointer from `GetWritableImageData(0)` (size from `GetImageDataSize()`) and `Marshal.Copy`, which returns no Unity array. The capture has the game HUD (crosshair) but not the Steam overlay.
- **Stripped methods:** `Object.FindFirstObjectByType` fails with "Method unstripping failed". Use `Resources.FindObjectsOfTypeAll`.
- **Practice mod bug (0.6.0):** `PracticeController.ResetAll` (on `OnStopClient` and `OnStopHost`, which the menus trigger) calls `_slots.Clear()` instead of zeroing the slots. Then every practice tick throws in `RegisterCurrent`, and no body can spawn. `Practice.Slots` refills the list, and the watchdog reads it every 120 frames. Worth an upstream fix.
- **Host menu:** a new save needs a lobby password in the UI. `menu host_confirm` clears `passwordRequired` for local eval sessions; the 6-digit join code still gates the lobby.
- **HUD noise:** after long pauses the game shows "WARNING: RECONNECTION IN PROGRESS" (`BadConnectionWarning`), though the lobby is fine. The bridge hides it (`HideConnectionWarning` in its config).

## Class names found (interop signatures, not decompiled code)

| What | Where |
| --- | --- |
| Held prop | `PlayerCharacter.hands` (`PlayerHands`): `heldProp` (`Prop`), `heldCharacter`, `PickUp(Prop, bool)`, `Drop(PlayerHeldInformation)` |
| Reward | `RewardGourd : NetworkBehaviour` on a `Prop`; `gourdState`, `OnChangeGourdState` |
| Pose | `croucher.localTrueCrouchness`, `sitter.isSittingLocal`, `jumper.Jumpness`, `gestures.left/rightArmWavingState`, `gestures.left/rightArmPointing` |
| Head | `PlayerHead.headState` (Vector2), `runningTotalLookSpin`, `SetHeadStateLocal()`. Lead for an exact `look` |
| Mover | `PlayerMover.cachedKernalPos`, `ResetPosition()` |
| Save | `SaveManager`, `SaveData` (`slotName`, `entries`, `inventory`), `HostMenuSelect.ActionSelectSaveData` |
| Text chat | `PlayerCharacter.texter` (`PlayerTexter`): `TrySendTextChat`, `CompleteInput`, `DisplayMessage` |
| Menus | `TitleMenu`, `HostMenuSelect`, `HostMenuConfirm`, `PlayerCountMenu` |
| Rewired actions | `RewiredConsts.Action`: `moveX`, `moveY`, `use`, `drop`, `jump`, `sprint`, `crouch`, `sit`, `waveLeft`, `waveRight`, `textChat`, `mute` |

To regenerate the signatures, load the interop assemblies with reflection (a 40-line console app: `Assembly.LoadFrom` plus an `AssemblyResolve` handler for `interop\` and `core\`). Keep the output out of the repo, like the Cpp2IL dump.

## Next

1. `load_snapshot`: reset puzzle state (switches, doors, gourds), not only props and bodies.
2. `look` through `PlayerHead`, so turns do not depend on mouse sensitivity.
3. A real two-player puzzle: find a switch that must stay held (`PeckSwitch`, `PlayerDecisions.heldDownSwitch`) and test check 1 for it.
4. Backend B (per-body Rewired input), if a held world switch drops on a switch.
