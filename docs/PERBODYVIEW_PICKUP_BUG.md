# PerBodyView pickup bug

On the work laptop (3 Oct 2026), with capture on and `Capture.PerBodyView = true`, every
pickup failed: `footy_walkabout` and `cave_telescope` scored I. With `PerBodyView = false`
they scored C. On 1 Oct, on another PC, both scored C with it on.

**Result (7 Oct, same laptop): not reproduced.** With the diagnostics below and the server
started with `--config server.yaml`, PerBodyView on scored C on every run (`footy_walkabout`,
`footy_hold_use`, `cave_telescope`). The one I was with PerBodyView off: the game saw "use"
but Cedar had stopped short of the ball (the known re-pickup flake). Each click registered
for 1 to 3 frames at 12 to 97 ms per frame, with the pickup on the same frame. With capture,
frames took 14 to 27 ms on average (max 79 ms) either way; `ReadPixels` costs 210 to 350 ms
per second, PerBodyView only 10 to 16 ms. Likely cause on 3 Oct (not proven): a run with the
default `counts_per_degree` (server started without the laptop config), or the flake.
PerBodyView can go back on. H1 stays a risk if frames get slower: a click is often 1 frame.

## What PerBodyView does

`BodyCapture.Tick` runs in `LateUpdate`. For each 1/fps step of game time, it renders one
camera per idle body and reads the pixels back (`ReadPixels`, which waits for the GPU).
With PerBodyView on, `CaptureView.Apply` changes live game objects before each idle render,
and `Undo` puts them back right after:

1. **Looks** (`PerBodyViewLooks`): the active body's head and body renderers go from
   shadows-only to on, and its first-person arms get `forceRenderingOff`.
2. **Own text** (`PerBodyViewOwnText`): `SetActive(false)` on the idle viewer's head text,
   then `SetActive(true)`. This runs on every idle render, also with no chat, so the text
   object gets `OnDisable` and `OnEnable` up to 30 times a second per idle body.
3. **Other text** (`PerBodyViewOtherText`): the other bodies' head texts move, turn, scale
   and change alpha (5 raycasts each). Only for texts with messages.

## Hypotheses

**H1, timing (Patrick's).** A click holds "use" for 50 ms of wall time (`CLICK_MS`). If one
frame takes longer than that, the press and the release can both land between two Rewired
polls, and the game never sees "use". Walking holds keys for 0.5 to 2 s, so it survives slow
frames. The re-pickup in `footy_walkabout` already flaked 1 run in 3 without the laptop.
Against: PerBodyView adds a few ms of CPU per idle render (TMP rebuilds, raycasts). That
only matters if the laptop is already at the edge with PerBodyView off.

**H2, game state.** One of the three changes above breaks the active body's interaction.
Looks is the main suspect, because it is the only change made to the active body. Own text
is next, because its `OnDisable` and `OnEnable` callbacks run all the time. A callback on
renderer visibility (`OnBecameVisible`, Animator culling on the arms) is one possible path.

## Experiments (laptop, game and game server running)

Get the branch and deploy the bridge:

```
git fetch origin claude/per-body-view-pickups-iuogjy
git checkout claude/per-body-view-pickups-iuogjy
powershell -NoProfile -ExecutionPolicy Bypass -File bridge\deploy.ps1
uv run --extra server python -m server.app --config server.yaml
```

The switches change at runtime, with no restart (the bridge also saves them to
`BepInEx\config\com.bigwalk.evalbridge.cfg`):

```
uv run --extra server python -m server.capture_config --per-body-view on --diagnostics on
```

The bridge writes `diag` lines to `BepInEx\LogOutput.log` in the game folder. Read them with:

```
Select-String -Path "C:\Program Files (x86)\Steam\steamapps\common\Big Walk\BepInEx\LogOutput.log" -Pattern "diag (use|pickup)|capture stats|capture config"
```

1. **Find which hypothesis.** Run `footy_walkabout` with capture:
   `uv run python scripts/scripted_run.py scripts/solutions/footy_walkabout.yaml --backend http --capture`.
   Look at Cedar's clicks in the log:
   - No `diag use ... down True` line for a click: the game never saw it. That is H1.
     Note the frame times in the `capture stats` lines.
   - `use` went down for one or more frames, but no `diag pickup` line: H2.
2. **Check H1.** Run `scripts/solutions/footy_hold_use.yaml` the same way. It holds "use"
   for 0.5 s. C here and I in step 1 confirms H1.
3. **Find the change for H2.** Repeat step 1 three times, each time with one switch off:
   `--looks off`, then `--own-text off`, then `--other-text off` (turn the last one back on
   each time). The run that scores C names the change.
4. **Baseline.** Repeat step 1 with `--per-body-view off`. Compare the frame times with step 1.
5. **Cleanup.** Set the switches back to what you want, for example
   `--per-body-view off --diagnostics off`.

## Possible fixes

For H1:
- Hold every click for a minimum number of game frames, not 50 ms of wall time. The bridge
  can report its frame count, or the server can make `CLICK_MS` larger.
- Make capture cheaper: `AsyncGPUReadback` instead of `ReadPixels` (no GPU wait; needs a
  check in this interop build), a lower capture fps or size, or one idle body per frame
  in turn.
- Capture only in replays (draft PR #12), not in live runs. Frame time then cannot change a
  live result. It does not help a replay, because the replay also sends wall-time input.

For H2:
- Own text: hide it with `forceRenderingOff` on its renderer, not `SetActive`, so no
  `OnDisable` or `OnEnable` callbacks run.
- Looks: keep the change, but skip it while "use" is held, or drop it (idle views then show
  the active body headless with floating arms, as with PerBodyView off).
- General: give the capture cameras bridge-owned copies (head texts, a body stand-in) on a
  layer that only the capture cameras render, so the bridge never touches game objects.
