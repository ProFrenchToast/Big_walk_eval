# Puzzle catalogue

Status: 2026-10-01, game 1.5.1 2608271531, hosted for 2 players.

`docs/puzzle_catalogue.yaml` lists all 52 puzzles in the game. Each entry has where the puzzle is, where two agents spawn, what the puzzle needs, and a verdict for this eval. The 20 puzzles that fit have a puzzle file in `puzzles/candidates/`. These files are not in the default dataset: no candidate has a scripted solution yet, and reset is not tested for them. Run them with `-T puzzles_dir=puzzles/candidates`. Move a file to `puzzles/` once a scripted solution scores C twice in a row.

## Rules for the verdict

We skip a puzzle if it needs any of these:

- **sound**: an agent must hear something (headsets, music).
- **simultaneous**: two presses at the same moment (`SimPressController`). Hot-swap runs one body at a time. Buttons that two bodies must *hold* together (`NHold`) are fine, because a held switch stays held after a switch (tested with the cave telescope).
- **far_apart**: the players must act far from each other (over about 100 m, like the cave telescope).

`maybe` means the puzzle passes these rules but has a practical problem:

- **voice_blocked**: the game blocks voice and text chat between the players. Our `say` tool does not know this, so it would leak. The faithful version needs `say` turned off for the puzzle (gestures only).
- **solo**: one agent can solve it alone, so it tells us little about cooperation.
- **long_wait**, **very_long**, **trivial**: minutes to hours of game time, or no real task.
- **no_gourd**: the black sphere rooms give no gourd. The scorer needs a new goal type, for example the state of the room's "Challenge Complete" gate.
- **rules_unverified**: we found the puzzle in the game but did not work out its rules.

## How the data was found

- **Puzzles**: every reward gourd in the scene (`RewardGourd`), with its save name (`SaveablePropName`, for example `gourdTelescopeToBox`). The puzzles are children of `LandmarksPlayerCountAny` (all player counts) and `LandmarksPlayerCount2/Contents` (the 2-player variants). The black sphere rooms are levels of `SilentGauntlet 2Player`.
- **What a puzzle needs**: the component types under its root (`puzzle_roots`). `SimPressController` means simultaneous presses, `PeckEffectHeadset` means sound, `PeckEffectMask` means a blindfold, and `SpeechlessZone` means no voice. `switch_spread_m` is the largest distance between two switches or prop homes of the puzzle. It does not see the far half of puzzles whose far half has no switch (the mountain gesture platforms).
- **Coordinates**: the in-game GPS device and the paper map show `GPSTracker.GetX/GetZ`: x_map = 0.7071 (x + z) + 1900 and z_map = 0.7071 (x − z) + 3300 (world rotated 45°). The guide writes them as (z_map, x_map). For example, the guide's red coordinates "3259, 1883" are the gourd box at world (−40.9, 14.4, 17.1).
- **Names**: matched to [big-walk.net/puzzles](https://big-walk.net/puzzles/) by the guide's coordinates (`guide_match: coordinates`), by its description (`description`), or by a best guess (`guess`).
- **Spawns**: the designers put a `TeleportPoint` at almost every puzzle (for example "124 labyrinth"), facing the puzzle. Ash spawns there and Birch 1.5 m to Ash's right, both at the designer's yaw. `scripts/survey_puzzles.py check-spawns` teleports both bodies to every entry. On 2026-10-01 no body moved more than 0.13 m.

## The puzzles

Guide coords are in the guide's order (z_map, x_map), at the gourd's home.

### Run (20)

| id | Guide name | Guide coords | Reasons |
| --- | --- | --- | --- |
| `blindfold_catwalk` | Blindfolded Obstacle Course | 3344, 1943 | - |
| `blindfold_fishtrap` | Golden Mask Obstacle Race (possibly) | 3943, 2102 | - |
| `cannonball_carry` | Heavy Golf Ball ('Hole In Many') (probably) | 3663, 1629 | - |
| `carousel` | Aerial Seat | 3569, 1639 | - |
| `centurion_seance` | Many Lights (purple #7) (probably), post-game | 4407, 1690 | - |
| `centurion_song` | Button Room | 3275, 1676 | - |
| `charades_rooms` | Double Green Barn (possibly), post-game | 4430, 1865 | - |
| `conductor_concert` | Stage Directions | 3400, 1587 | - |
| `dancer_and_selecter` | 9 Symbols / Posing (purple #5) (probably), post-game | 4392, 1805 | - |
| `fielding` | Train Station Cannon | 3880, 1524 | - |
| `invisible_ink` | (not in the guide) | 3753, 2149 | - |
| `kick_up_pits` | Deep Well | 3600, 1564 | - |
| `labyrinth` | Yellow Maze (timer hand-off) | 3843, 1360 | - |
| `observation_room` | Green Room (symbol call-out), or the Black Tower 'Green Room Red Light' (probably) | 3481, 1709 | - |
| `perspective_counting` | Blue Signal Counting (counting / face puzzle) (probably) | 4087, 1871 | - |
| `poet_and_pontiff` | 36 Drawings (purple #3) (probably), post-game | 4517, 1906 | - |
| `poet_and_priest` | Turnstile House | 3511, 1964 | - |
| `semaphore_rooms` | Charades Locked Room | 3267, 1945 | - |
| `tall_button` | Mechanical Arm (stacking puzzle) | 3521, 1273 | - |
| `teller_window` | Blue Room (peg / pin puzzle) | 3658, 1291 | - |

### Maybe (17)

| id | Guide name | Guide coords | Reasons |
| --- | --- | --- | --- |
| `basketball` | Basketball court (light / bulb puzzle) | 3834, 1568 | solo |
| `cabin_fever` | Locked Room / Five-Minute Countdown | 3592, 2030 | long_wait, trivial |
| `cabin_fever_long` | Wait 30 Minutes House (purple #1), post-game | 4287, 1657 | long_wait, trivial |
| `cannonball_commute` | Long-Distance Golf (purple #2) (probably), post-game | 4267, 1869 | very_long |
| `egg_hunt` | Easter Egg Hunt | 3369, 1478 | very_long |
| `gauntlet_0_pegboard` | Symbols on the Wall (probably) | black sphere | no_gourd, voice_blocked |
| `gauntlet_1_pointers` | Blue Totems (probably) | black sphere | no_gourd, voice_blocked |
| `gauntlet_2_kick` | Tomato Timer (probably) | black sphere | no_gourd, voice_blocked |
| `gauntlet_4_volleyball` | Red Kettle & Switches (probably) | black sphere | no_gourd, voice_blocked |
| `gauntlet_5_invisible` | Hidden Symbols (probably) | black sphere | no_gourd, voice_blocked |
| `gauntlet_6_sculptures` | Shapes & Switches (probably) | black sphere | no_gourd, voice_blocked |
| `memory_bombs` | Yellow Stands (meter puzzle) | 4028, 1877 | solo |
| `pointers_paradise` | Black Tower symbol room (possibly) | 3768, 1443 | rules_unverified |
| `ring_room` | (not in the guide) | 3833, 1935 | rules_unverified |
| `scout_bombs` | (not in the guide) | 3233, 1839 | rules_unverified |
| `tile_thief` | (not in the guide) | 3878, 2259 | rules_unverified |
| `trap_room` | Orange Barn (sealed player guides gestures) (probably) | 4140, 1782 | voice_blocked |

### Skip (15)

| id | Guide name | Guide coords | Reasons |
| --- | --- | --- | --- |
| `breadcrumb_loop` | (not in the guide) | 3668, 1712 | simultaneous, far_apart |
| `coordinates_holding` | The 4166, 1899 Puzzle | 3908, 1474 | far_apart |
| `coordinates_sim_press` | Red Coordinates (3259, 1883 & 3231, 1976) | 3259, 1883 | simultaneous, far_apart |
| `flare_run` | Green Flare | 3725, 2245 | far_apart |
| `gauntlet_3_sim_press` | Race Track (probably) | black sphere | simultaneous, voice_blocked |
| `medium_sim_press` | (not in the guide) | 3787, 2258 | simultaneous |
| `microphone_array` | Microphone puzzle (chair / headphones) | 3395, 1231 | sound |
| `musical_holiday` | Green Seat Speaker Mic | 3896, 1781 | sound, far_apart |
| `obby` | Obstacle Course | 3687, 1998 | simultaneous |
| `optical_telegraph` | Mountain Gesture (telescopes & charades) | 3921, 1614 | far_apart |
| `signal_flags` | Seaside Counting Binoculars | 4182, 2177 | far_apart |
| `singer_and_selecter` | Music Room | 3193, 1259 | sound |
| `small_sim_press` | Green Structure (simultaneous switches) | 3653, 1224 | simultaneous |
| `speed_obby` | Platforming (purple #6), post-game | 4560, 1744 | simultaneous |
| `telescope_to_gourd_box` | Cave & Telescope | 3590, 1338 | far_apart |

`telescope_to_gourd_box` is `puzzles/cave_telescope.yaml`. It stays in the repo as a harness smoke test.

### Not in the catalogue

- Scene roots that are not puzzles: `BlackTower PlayerCount2` (the tower's piece sockets), `EndingGate 2Player`, `SecondGoodbye PlayerCount2`, the black sphere's level 7 (the bell chamber at the end), and the gourds on the overflow monument (`notSavable`).
- Guide entries with no gourd puzzle in the game: Dome Microphone and 9 Speakers (both sound), Blue Slope Music (fetches blocks from four arenas across the island), Chairlift Shape Sequence, the radio stations, and Lost & Found. The Beach House may be `scout_bombs`.
- `SaveablePropName` has about 15 more gourd names with no object in the scene (for example `gourdFirstPegBoard`, `gourdHotPotato`, `gourdMaypole`). They are probably cut puzzles.

## Problems to solve before the candidates can be scored

1. **Reset.** Reset moves bodies and props, pins each gourd back into its home, and releases held switches. Most candidates also have state it does not restore: sealed rooms, boards, timers, and gourd vices that open on success. Write `load_snapshot`, or a reset step per puzzle, and test each candidate twice in a row.
2. **Time of day.** The game clock runs, and reset does not set it. By the end of the 2026-10-01 session it was night in the game, and the agents' screenshots were nearly black. Reset needs to set the time of day (the game uses Enviro; there is a `StopEnviroTimeOperation` in the remote debug tools).
3. **Voice blocking.** `say` uses distance only. Puzzles where the game blocks voice need `say` off, and the in-game text chat also fades with occlusion.
4. **Blindfolds under hot-swap.** `PeckEffectMask` acts on the local player. Check that the mask follows the masked body when control switches, as `ChatSync` had to do for chat.
5. **Player count.** The 2-player variants are active because `host_walk` hosts with `--players 2`. For 3 or 4 agents, host with that count and run the survey again; the `LandmarksPlayerCount3/4` roots were empty in a 2-player walk.
6. **Post-game variants** (`post_game_variant: true`) are active in the `evalwalk` save before the true ending. They are harder twins of other puzzles.

Suggested order for scripted solutions, simplest first: `teller_window`, `tall_button`, `poet_and_priest`, `centurion_song`, `labyrinth`, `conductor_concert`.

## Refresh after a game update

```bash
uv run python scripts/survey_puzzles.py dump runs/survey.json
```

```bash
uv run python scripts/survey_puzzles.py check-spawns
```

`dump` writes the raw survey (gourds, teleport points, mechanisms, puzzle root profiles). Compare it with the catalogue. `check-spawns` fails if a spawn moved more than 0.3 m.
