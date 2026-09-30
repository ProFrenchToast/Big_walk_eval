# Big Walk Cooperation Eval

An [Inspect AI](https://inspect.aisi.org.uk/) eval. LLM agents cooperate to solve puzzles in the game *Big Walk*. Each agent controls one player body, sees only its own first-person view, and talks through range-limited text chat.

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

Real game (Windows machine with the game, BepInEx, big-walk-practice, and `bridge/`):

```bash
uv run --extra server python -m server.calibrate --config server.yaml     # once per machine
uv run --extra server python -m server.app --config server.yaml
uv run python -m server.record_spawns --names Ash,Birch                   # when writing a puzzle file
uv run python scripts/scripted_run.py scripts/solutions/<puzzle>.yaml --backend http
uv run inspect eval big_walk_eval/big_walk_coop -T backend=http --max-samples 1 --model ...
```

The server binds to `127.0.0.1:47801`. From another machine, use an SSH tunnel: `ssh -L 47801:127.0.0.1:47801 <windows-host>`.

## Layout

| Path | What |
| --- | --- |
| `src/big_walk_eval/protocol.py` | Models shared by the harness and the game server |
| `src/big_walk_eval/task.py` | `@task big_walk_coop` and its parameters |
| `src/big_walk_eval/solver.py` | Round-robin multi-agent solver |
| `src/big_walk_eval/tools/` | `computer` (native computer-use binding), `say`, `end_episode` |
| `src/big_walk_eval/game/` | `GameClient` interface, `FakeGame`, `HttpGame` |
| `src/big_walk_eval/timeline.py` | Actions to timed input events, shared by FakeGame and the server |
| `server/` | Game server (FastAPI), bridge client, input backends, calibration. Windows for real input |
| `bridge/` | BepInEx plugin (C#). Skeleton, not compiled yet |
| `puzzles/` | One YAML file per puzzle |
| `scripts/` | `scripted_run.py` and scripted solutions |
