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

## Commands

- `uv run pytest` runs every test against FakeGame and a fake bridge. The tests need no network (`tests/conftest.py` stubs mockllm's tiktoken count).
- `uv run ruff check . && uv run ruff format --check .`
- `uv run python scripts/scripted_run.py scripts/solutions/fake_plate_gate.yaml` must score C after any change to the loop or the tools.
