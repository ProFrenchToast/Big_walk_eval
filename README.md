# Big Walk Cooperation Eval

An [Inspect AI](https://inspect.aisi.org.uk/) eval. LLM agents cooperate to solve puzzles in the game *Big Walk*. Each agent controls one player body, sees only its own first-person view, and talks through the game's own text chat (Enter, type, Enter), which only nearby players can read.

Read `docs/IMPLEMENTATION_PLAN.md` for the design. Section 15 there gives the current status.

## Setup

```bash
uv sync
uv run pytest            # all tests use FakeGame; no game, no network
uv run ruff check . && uv run ruff format --check .
```

## Run

FakeGame is a small 2D puzzle world (a pressure plate, a gate, and a gourd) with a first-person view. Use it to test the harness and prompts before the real game.

```bash
# Scripted two-body solution through the real turn loop. Expect "score: C".
uv run python scripts/scripted_run.py scripts/solutions/fake_plate_gate.yaml --save-images runs/fake

# Agents on FakeGame
uv run inspect eval big_walk_eval/big_walk_coop --model anthropic/claude-sonnet-5-5

# The same, through the HTTP game server
uv run --extra server python -m server.app --fake &
uv run inspect eval big_walk_eval/big_walk_coop -T backend=http -T puzzle_game=fake --model ...
```

Real game (Windows machine with the game, BepInEx 6 be.788 IL2CPP, big-walk-practice 0.6.0, and `bridge/`; see `bridge/README.md` for the one-time setup):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File bridge\deploy.ps1   # build, install, start the game through Steam
copy server\config.example.yaml server.yaml
uv run --extra server python -m server.app --config server.yaml
# Scripted 3-body smoke test: walk, look, jump, crouch, sit, wave, pick up, drop, chat, vote. Expect "score: C".
uv run python scripts/scripted_run.py scripts/solutions/footy_walkabout.yaml --backend http --save-images runs/real
uv run inspect eval big_walk_eval/big_walk_coop -T backend=http -T puzzles=footy_walkabout --max-samples 1 --model ...
```

The server hosts a walk on the first `/reset` if the game is at the title screen. Do not touch the mouse or keyboard during a run: the server sends real input to the game window. Helpers: `python -m server.host_walk` (host a walk), `python -m server.calibrate` (mouse counts per degree), `python -m server.record_spawns --names Ash,Birch` (print a `spawns:` block).

The server binds to `127.0.0.1:47801`. From another machine, use an SSH tunnel: `ssh -L 47801:127.0.0.1:47801 <windows-host>`.

## Replay

Each episode records every input that the agents send to the game. The solver puts the recording in the sample store (`EpisodeLog.replay`), so the Inspect log holds it. The recording also has the votes, the game events of each action (chat messages are `text_chat` events), and the position of each body after each action.

```bash
# Send the recorded inputs to a fresh game, compare each body with the recording, and make a video.
uv run python scripts/replay.py logs/scripted/<log>.eval -v
# Real game: also save the view after each action.
uv run python scripts/replay.py <log>.eval --backend http --frames runs/replay
```

FakeGame replays exactly. On the real game, the drift shows how deterministic the game is under replayed input.

The playback also captures every body's view and writes the same grid video as `scripts/make_video.py` (see Video), to `<frames>/replay.mp4` or `--video PATH`. So an episode that ran without capture can still get a video. The capture uses the task's `capture_fps`/`capture_width`/`capture_height` if the log has them, else 30 fps at 683x384; the `--capture-*` flags change them. Use `--no-video` to skip the capture. If the log has several samples or epochs, choose one with `--sample-id` and `--epoch` (`--list` shows them). `scripts/make_video.py` takes the same flags. On the real game, run the script on the game's machine, because the game writes the frames there. The video shows the replayed run, so where the real game drifts under replayed input, the video drifts too.

## Video

With `-T capture=true`, the game records each body's own view while game time runs. It writes the frames on the machine that runs the game. `scripts/make_video.py` puts the views of all agents side by side in one video. A yellow border shows the agent that acts. Each view captions the chat messages that its agent sent. The other views show a message only where the game shows it, over the speaker's head.

```bash
uv sync --extra video     # ffmpeg, if it is not on PATH
uv run python scripts/scripted_run.py scripts/solutions/fake_plate_gate.yaml --capture
uv run python scripts/make_video.py logs/scripted/<log>.eval      # writes <frames>/episode.mp4
uv run inspect eval big_walk_eval/big_walk_coop -T capture=true --model ...
```

The frames have no pauses between actions, because no game time passes then. Each chat message stops the video for 2 s (`--hold-s`) so that viewers can read it. On the real game, the bridge renders one extra camera per body. This is **NEEDS GAME** (see `bridge/README.md`).

## Layout

| Path | What |
| --- | --- |
| `src/big_walk_eval/protocol.py` | Models shared by the harness and the game server |
| `src/big_walk_eval/task.py` | `@task big_walk_coop` and its parameters |
| `src/big_walk_eval/solver.py` | Round-robin multi-agent solver |
| `src/big_walk_eval/tools/` | `computer` (native computer-use binding, also used to chat in game), `end_episode` |
| `src/big_walk_eval/game/` | `GameClient` interface, `FakeGame`, `HttpGame` |
| `src/big_walk_eval/replay.py` | Records the inputs of an episode and plays them back |
| `src/big_walk_eval/video.py` | Makes one video from the per-body frames of an episode |
| `src/big_walk_eval/timeline.py` | Actions to timed input events, shared by FakeGame and the server |
| `server/` | Game server (FastAPI), bridge client, input backends, calibration. Windows for real input |
| `bridge/` | BepInEx plugin (C#) that the game server talks to over TCP |
| `puzzles/` | One YAML file per puzzle |
| `scripts/` | `scripted_run.py`, `replay.py`, `make_video.py`, and scripted solutions |
