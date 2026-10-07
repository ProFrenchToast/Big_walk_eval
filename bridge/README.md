# BigWalk.EvalBridge

A BepInEx 6 IL2CPP plugin. It lets the eval game server (`server/`) control the game over TCP. It needs [big-walk-practice](https://github.com/iameli/big-walk-practice) 0.6.0 for extra bodies and slot switching.

Status (2026-09-30): compiled and tested in game 1.5.1 2608271531 (Unity 6000.3.17f1) with BepInEx 6.0.0-be.788. A scripted three-body run (`scripts/solutions/footy_walkabout.yaml`) scores C through the full harness, and video capture of every body's view works (2026-10-01). The first real puzzle, the cave telescope (`puzzles/cave_telescope.yaml`), scores C with a scripted two-body solution (2026-10-01). Still missing: save snapshots, the exact `look` command, Backend B input. In-game text chat through the keyboard works, over each speaker's head and range-limited by the game (2026-10-01): `scripts/solutions/text_chat_circle.yaml` scores C.

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
| `get_state` | | `paused`, `active_slot`, `time_s`, `camera_vfov_deg`, `bodies: [{slot, position, yaw_deg, pitch_deg, held, pose}]` | tested. `held` is `PlayerHands.heldProp` (one per body). `pose`: crouch, sitting, jump, arm pointing and waving, `held_switch` (path of the world switch the local body holds down) |
| `switch_slot` | `slot` | `active_slot` | tested, about 0.04 s while paused |
| `spawn_bodies` | `n` | `count` | tested, while paused |
| `teleport` | `slot`, `position`, `yaw_deg` | | tested. See "Teleports" below |
| `place_prop` | `item_type`, `position`, `near`?, `home`? | `item_id`, `item_type`, `is_reward`, `moved_m`, `home`? | tested. Moves the nearest prop of that type. With `home: true`, pins the prop whose start home is nearest to `position` back into that home, and sets a gourd back to Locked |
| `screenshot` | | `png_base64`, `width`, `height` | tested, about 0.12 s while paused |
| `events` | | `events: [{type, slot, t_ms, data}]` | tested: `switched`, `item_picked_up`, `item_dropped`, `reward_state` (gourd `Locked` to `Loose` when taken). Also tested: `text_chat` (`TextChatSource.AddMessage`, a message shows in the game) and `text_chat_sent` (`PlayerTexter.CompleteInput`, the local body sent one), once per message each |
| `controls` | | keyboard and mouse bindings per game action, from Rewired | tested |
| `menu` | `action`: `status`, `title_host`, `new_game`, `load_save {name}`, `host_confirm {name}`, `player_count {n}` | `open_menus`, `hosting`, `local_player_ready` | tested. `server/host_walk.py` drives it |
| `list_props` | `slot`?, `radius`?, `limit`? | props near a body, nearest first | tested. For writing puzzle files |
| `find_objects` | `name`? or `component`? (substring), `near`?, `radius`?, `limit`?, `include_inactive`?, `components`? | scene objects, nearest first: `name`, `path`, `position`, `yaw_deg`, components, `gourd_state` | tested. For writing puzzle files: finds switches, telescopes and gourds anywhere |
| `peck_states` | `near`, `radius`?, `include_inactive`? | `states: [{path, label, state}]` (`TrackedPeckState`), `held_switches: [{path, slot}]` | tested. Puzzle state: buttons, doors, boxes |
| `release_switches` | `slots`? | `released: [{path, slot}]` | tested. Reset calls it. See "Held world switches" below |
| `debug_practice`, `debug_body {slot}` | | practice slot table; every position the game keeps for a body | tested. For debugging |
| `debug_chat` | `sync`?, `view_slot`? | every `TextChatSource` (head and screen text, `isLocalPlayer`, visible, audibility, text, `estimated_readability` from the camera), each body's texter, the input field. With `view_slot`, the scene is set up as for that body's capture camera (`CaptureView`) while the report is read | tested. For debugging the chat |
| `clear_chat` | | `cleared_sources` | tested. Removes every chat message from heads and the HUD. Reset calls it |
| `overview_shot` | `position`, `look_at`, `width`?, `height`?, `fov_deg`? | `png_base64`, `width`, `height` (null without a position) | tested (2026-10-01). A hidden free camera, read back through a pointer; the PNG is encoded in managed code (`Commands/Capture.cs`). Terrain and trees load only near the active body, so teleport a body close first |
| `survey` | | `gourds` (save name, start home, house number), `teleport_points` (the designers' `TeleportPoint`s), `mechanisms` (puzzle component types), each with `position` and `map` | tested. For the puzzle catalogue (`scripts/survey_puzzles.py`) |
| `puzzle_roots` | `parents`, `include_inactive`? | per child of the parents: component counts, `switches`, `homes`, `props` with positions | tested. Profiles each puzzle |
| `children` | `name`, `include_inactive`? | the children of each object with that name | tested |
| `map_coords` | `positions` | `map: [[x, z]]` (`GPSTracker.GetX/GetZ`) | tested |
| `ground` | `positions`, `up`?, `down`? | the first surface below `up` (2 m) above each position (`Physics.Raycast`) | tested |
| `look` | `dyaw_deg`, `dpitch_deg` | | TODO(dump). The server uses `look_mode: mouse` |
| `load_snapshot` / `save_snapshot` | `name` | | TODO(dump). `place_prop` covers simple cases |
| `capture_start` | `directory`, `fps`, `width`, `height`, `slots` | | tested. One camera per body, frames to ffmpeg. Each idle body's frame shows the scene as that body sees it (`Commands/CaptureView.cs`). The active body's frame is a copy of the screen, with the HUD. See `Commands/BodyCapture.cs` and "Screenshots" below |
| `capture_stop` | | `frames`, `start_time_s` | tested |
| `capture_config` | `per_body_view`?, `looks`?, `own_text`?, `other_text`?, `active_from_screen`?, `diagnostics`? | the same keys, as now set | NEEDS GAME. Sets the capture switches at runtime (`python -m server.capture_config`). For the PerBodyView pickup bug, see `docs/PERBODYVIEW_PICKUP_BUG.md` |
| `input` | `slot`, `op`, ... | | TODO(dump). Backend B only |

The Python side of this protocol is `server/bridge_client.py`. The tests in `tests/fake_bridge.py` use a fake bridge that speaks the same protocol.

## What we learned in the game

- **Controls** (from `controls`): WASD move, Shift run, Space jump, Ctrl crouch (hold), Z sit (toggle), Q and E wave (hold), Enter text chat, V mute. Left mouse is "use" (pick up, press), right mouse is "drop". There are no per-hand buttons: a body carries one prop in both hands.
- **Check 1 (hot-swap), for carried props: passes.** A body keeps its prop while other bodies act, because carrying is game state, not a held button. A held "use" button (left arm pointing) also comes back after a switch, because the server presses it again. A world switch that a body holds down also stays held (see below).
- **Held world switches** (tested with the cave telescope button, a `BasicPushButton`): a body presses and holds "use" on the button, the server releases the OS button while paused and switches to another body, and the button stays held by the first body (`PeckSwitch.playerHoldingThis`, button and box state 1) while the second body walks and takes the gourd. So Backend A works for hold-and-act puzzles. But the switch then stays held for good: a later OS release, a switch back with the button up, and `PlayerNetworking.ServerForceLetGoSwitch` (and the server side of `CmdReleaseHeldSwitch`) all leave it held. `release_switches` pecks the switch's `upSwitch` and clears `playerHoldingThis`, and `reset` calls it.
- **Gourds after a run:** taking a gourd sets it `Loose`. The game saves that, and on the next load it moves the gourd to a "valet" home (the cave telescope gourd appears on the viewing platform, next to the button). So `place_prop` by position can pick the wrong gourd (it once took the TellerWindow gourd from its vice). Puzzle files put their gourd back with `home: true`, which pins it into its start home as in a new game.
- **Text chat** (tested with `text_chat_circle`): Enter opens the chat, `SendInput` Unicode characters (`KEYEVENTF_UNICODE`) go into the field, and Enter sends. Typed `r` and digits do not trigger the practice-mod hotkeys. Each body sends as itself after a hot-swap. A message shows in two places: over the speaker's head (its `TextChatSource`, world-space text that other players see), and as an echo on the speaker's own HUD (`TextChatInput.output`, one shared field). **Under hot-swap both were wrong at first:** the game sets `TextChatSource.isLocalPlayer` when a body spawns, and the practice mod spawns every body as the local player, so every head text counted as "mine" and stayed hidden; and the one HUD echo kept the last body's message, so every body saw it on its own HUD. `ChatSync` (`Commands/ChatSync.cs`) fixes both whenever the local body changes: only the active body's head text is local, and the HUD echo shows the active body's own last message. Since then other bodies see a message only over the speaker's head, and only in range: the game fades head text by distance and occlusion (`TextChatSource.audibility`, from the audio occlusion system). Measured: readable at 8 m, hidden at 154 m. Only the newest message shows over a head, and it stays while the game is paused. `TextChatHud` shows a blip at the screen edge for a speaker (not yet checked what it tracks). Reset calls `clear_chat`, so no message carries over to the next episode. `PlayerTexter.DisplayMessage` never runs (probably inlined by IL2CPP); `ReceieveMessage`, `CompleteDisplayMessage` and `TextChatSource.AddMessage` each run once per message.
- **Sitting carries over:** a body that sits (the `z` toggle, or landing on a seat) keeps sitting through a teleport and cannot walk. Reset stands up every sitting body (`sit_key`). Found when a body stayed seated after an experiment and `cave_telescope` failed.
- **footy_walkabout can flake:** after Cedar drops the football, the ball sometimes comes to rest below the crosshair, and the click to take it again misses (1 run in 3 on 2026-10-01). Run it again before you look for a bug.
- **Taking a gourd from a glass box:** only the lid opens. Aim through the open top; from the side, the crosshair stays hollow and "use" does nothing. The crosshair fills when it is on something usable.
- **Pause:** `timeScale = 0` stops movement. Rendering, switching, spawning, and screenshots all work while paused.
- **Mouse look:** 25 counts per degree at the default sensitivity, no Y inversion, positive pitch looks down. The camera has a vertical FOV of 90 degrees, so 121.3 degrees horizontal at 1366 x 768.
- **Teleports:** teleport a body while it is the local (active) body, then let the game run for about 1.5 s. Otherwise the next switch puts the body back where the network last saw it (0.3 s is not enough). `mover.ResetPosition()` in the practice mod's switch also restores a position cache that only updates in `FixedUpdate`. `BridgeGame.reset` does this per body.
- **Screenshots:** `EncodeToPNG`, and every other call that returns a Unity byte array, fails in this interop build ("Instances of abstract classes cannot be created" in `BlittableArrayWrapper.Unmarshal`). `screenshot` uses `ScreenCapture.CaptureScreenshot` to a temp file instead. Video capture reads its `Texture2D` through the pointer from `GetWritableImageData(0)` (size from `GetImageDataSize()`) and `Marshal.Copy`, which returns no Unity array. The `screenshot` has the game HUD (crosshair, chat input) but not the Steam overlay. Capture cameras render no HUD: the HUD canvases are screen overlays. So the active body's capture frames are a copy of the screen instead (`ScreenCapture.CaptureScreenshotIntoRenderTexture` at the end of the frame, from a `WaitForEndOfFrame` coroutine, then scaled with `Graphics.Blit`; config `Capture.ActiveFromScreen`). The copy is upside down compared with a camera's render texture (D3D12), so the blit flips it. Idle bodies' frames have no HUD. **The game draws the scene for the active body only, and every capture camera inherits it** (found 2026-10-01): head text faces `Camera.main` (`TextChatSource.RefreshOpacityAndRotation`), so other cameras see it edge-on or from behind; the active body's own text is hidden; text alpha is the audio occlusion from the active body's listener (`AudioOcclusionBasic`, smoothed over frames); and the active body is in the local look (`PlayerLooks`: its head and body renderers cast shadows only, its first-person arms show), so other bodies see it headless with floating arms. Before each idle body's render, `CaptureView` turns each head text to that camera, shows the active body's text, hides the viewer's own text, sets the alpha from that camera (the opacity curve over distance, 1 at 10 m and 0 at 20 m, times the share of five clear rays on the occlusion layers), and shows the active body in the remote look. It undoes all of it right after the render, so the main camera and the agents' screenshots do not change. Config `Capture.PerBodyView` turns it off; `PerBodyViewLooks`, `PerBodyViewOwnText` and `PerBodyViewOtherText` turn off one part each. **With it on, pickups failed on the work laptop (3 Oct)**: see `docs/PERBODYVIEW_PICKUP_BUG.md`. The game's head text size is `textScalar * (1 + distanceScalar * distance)` (1 and 0.2), 0.25 m above `TextChatSource.transform`. Not checked: the estimated alpha against the game's at 10 to 20 m with a clear line (both agree at 6 m, and both hide a text 12 m and 18 m away behind the ledge).
- **Puzzle survey (2026-10-01):** every puzzle root is a child of `LandmarksPlayerCountAny` or `LandmarksPlayerCount2/Contents` (the host's player count picks the variant; the 3- and 4-player roots are empty in a 2-player walk). The designers put a `TeleportPoint` (`customName` such as "124 labyrinth", with a yaw) at almost every puzzle; they make good spawns. Map coordinates (the GPS device and the paper map) are the world rotated 45 degrees: x_map = 0.7071 (x + z) + 1900, z_map = 0.7071 (x - z) + 3300. Puzzle types show in their components: `SimPressController` (simultaneous presses), `PeckEffectHeadset` (sound), `PeckEffectMask` (blindfold), `SpeechlessZone` (no voice; the whole black sphere is in one), `ButtonNHoldTwo` (two bodies hold buttons). See `docs/PUZZLE_CATALOGUE.md`.
- **Day and night:** the game clock runs while the game is unpaused, and nothing resets it. A long session reaches night, and screenshots go nearly black.
- **Stripped methods:** `Object.FindFirstObjectByType` fails with "Method unstripping failed". Use `Resources.FindObjectsOfTypeAll`.
- **Practice mod bug (0.6.0):** `PracticeController.ResetAll` (on `OnStopClient` and `OnStopHost`, which the menus trigger) calls `_slots.Clear()` instead of zeroing the slots. Then every practice tick throws in `RegisterCurrent`, and no body can spawn. `Practice.Slots` refills the list, and the watchdog reads it every 120 frames. Worth an upstream fix.
- **Host menu:** a new save needs a lobby password in the UI. `menu host_confirm` clears `passwordRequired` for local eval sessions; the 6-digit join code still gates the lobby.
- **HUD noise:** after long pauses the game shows "WARNING: RECONNECTION IN PROGRESS" (`BadConnectionWarning`), though the lobby is fine. The bridge hides it (`HideConnectionWarning` in its config).

## Class names found (interop signatures, not decompiled code)

| What | Where |
| --- | --- |
| Held prop | `PlayerCharacter.hands` (`PlayerHands`): `heldProp` (`Prop`), `heldCharacter`, `PickUp(Prop, bool)`, `Drop(PlayerHeldInformation)` |
| Reward | `RewardGourd : NetworkBehaviour` on a `Prop`; `gourdState` (`GourdFlag.GourdState`: Locked, Loose, Stashed, Hidden), `OnChangeGourdState`, `ServerSetGourdState` |
| Prop homes | `Prop.startHome`, `Prop.currentHome`, `Prop.ServerSetPinned(PropHome)` |
| World switches | `PeckSwitch`: `playerHoldingThis`, `upSwitch`, `Peck(PeckContext)`. `TrackedPeckState.currentPeckContext.state`. `PlayerCharacter.decisions` (`PlayerDecisions`): `heldDownSwitch` (local body only) |
| Cave telescope | `FixedTelescopeToGourd`: `Positioner-Platform/ViewingPlatform_DistantGourd/.../BasicPushButton` (button), `Positioner-Box/BoxPositioner/GourdBox/OpenableBox` (`boxLogic`, `BoxGourdHome`), `Positioner-Platform/GourdValet` |
| Pose | `croucher.localTrueCrouchness`, `sitter.isSittingLocal`, `jumper.Jumpness`, `gestures.left/rightArmWavingState`, `gestures.left/rightArmPointing` |
| Head | `PlayerHead.headState` (Vector2), `runningTotalLookSpin`, `SetHeadStateLocal()`. Lead for an exact `look` |
| Mover | `PlayerMover.cachedKernalPos`, `ResetPosition()` |
| Save | `SaveManager`, `SaveData` (`slotName`, `entries`, `inventory`), `HostMenuSelect.ActionSelectSaveData` |
| Text chat | `PlayerCharacter.texter` (`PlayerTexter`): `TrySendTextChat`, `CompleteInput(string, ref bool sent)`, `DisplayMessage`, `ReceieveMessage` (sic), `isPlayerTextChatting`, `source` (head text) and `globalTextChatOutput`. `TextChatInput.instance` (one `TMP_InputField` for the local player, `inputIsOpen`, `output`: the HUD echo). `TextChatSource` shows the messages at a body's head (`isLocalPlayer`, `audibility`, `isVisible`, static `IsPlayerTextLocallyReadable(pc)`). `TextChatHud` shows blips at the screen edge for speakers out of view |
| Menus | `TitleMenu`, `HostMenuSelect`, `HostMenuConfirm`, `PlayerCountMenu` |
| Rewired actions | `RewiredConsts.Action`: `moveX`, `moveY`, `use`, `drop`, `jump`, `sprint`, `crouch`, `sit`, `waveLeft`, `waveRight`, `textChat`, `mute` |

To regenerate the signatures, load the interop assemblies with reflection (a 40-line console app: `Assembly.LoadFrom` plus an `AssemblyResolve` handler for `interop\` and `core\`). Keep the output out of the repo, like the Cpp2IL dump.

## Next

1. `load_snapshot`: reset puzzle state (switches, doors, gourds), not only props and bodies. `release_switches` and `place_prop home` cover the cave telescope.
2. `look` through `PlayerHead`, so turns do not depend on mouse sensitivity.
3. More real puzzles. `docs/PUZZLE_CATALOGUE.md` lists every puzzle, with spawns and a verdict; `puzzles/candidates/` has the 20 that fit. Each needs a scripted solution and a working reset.
4. `set_time`: set the time of day to a fixed point at each reset (Enviro). The game clock runs, so a long session reaches night and the screenshots go dark. Not started.
5. Backend B (per-body Rewired input), for puzzles that need two bodies to act at the same moment (the green structure switches).
