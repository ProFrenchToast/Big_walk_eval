# Big Walk Cooperation Eval

An Inspect AI eval where LLM agents cooperate to solve puzzles in the game Big Walk. Each agent controls one player body, sees only its own view, and talks through range-limited text chat.

Read `docs/IMPLEMENTATION_PLAN.md` before you start work. It has the background, decisions, interfaces, and the ordered build plan (M0 to M8).

## Rules

- Python 3.11+, `uv`, `ruff`, `pytest`. Only add comments where the code is not clear.
- The harness talks to the game only through the `GameClient` interface. `FakeGame` must keep working, because CI and cloud sessions have no game.
- The game runs on Windows only. Code under `server/` and `bridge/` cannot run in a Linux session. Write unit tests with fakes for it, and mark untested game paths with `# NEEDS GAME` (Python) or `// NEEDS GAME` (C#).
- Unknown game class names are marked `TODO(dump)`. Do not guess class names. Leave the marker and the grep to run.
- Never commit decompiled game code or the Cpp2IL output (`out/`).
- Shared request and response models live in `src/big_walk_eval/protocol.py`. Change them in one place only.
- Game build: Big Walk 1.5.1 2608271531 (Unity 6000.3.17f1), BepInEx 6.0.0-be.788, big-walk-practice 0.6.0. The interop signatures change with each game update, so rebuild the bridge after one.

## Commands

- `uv run pytest` runs every test against FakeGame and a fake bridge. The tests need no network (`tests/conftest.py` stubs mockllm's tiktoken count).
- `uv run ruff check . && uv run ruff format --check .`
- `uv run python scripts/scripted_run.py scripts/solutions/fake_plate_gate.yaml` must score C after any change to the loop or the tools.

## Real game (Windows machine only)

- `powershell -NoProfile -ExecutionPolicy Bypass -File bridge\deploy.ps1` builds the bridge, installs it, and starts the game through Steam. Never start `Big Walk.exe` directly (see `bridge/README.md`).
- `uv run --extra server python -m server.app --config server.yaml`, then `uv run python scripts/scripted_run.py scripts/solutions/footy_walkabout.yaml --backend http` must score C after changes to the bridge, the server, or reset.
- The server sends real mouse and keyboard input to the game window. Nobody may use the PC during a run.
- `bridge/README.md` lists what we learned in the game (teleports, screenshots, the practice mod bug) and the class names.
