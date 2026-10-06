"""Round-robin multi-agent solver.

Each agent has its own message history and sees only its own body. Agents
take turns. A turn starts with a header and a fresh screenshot, then runs
up to `max_generates_per_turn` generate calls and their tool calls. The turn
ends early when the model replies without a tool call, or when the turn's
tool call or game time limit is used up.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass

import anyio
from inspect_ai.log import transcript
from inspect_ai.model import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageUser,
    ContentImage,
    ContentText,
    Model,
    ModelOutput,
    execute_tools,
    get_model,
)
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import Tool
from inspect_ai.util import span

from big_walk_eval.episode import Episode, EpisodeConfig, EpisodeLog
from big_walk_eval.game.client import GameClient
from big_walk_eval.prompts import system_prompt, turn_header
from big_walk_eval.protocol import CaptureRequest, PuzzleConfig
from big_walk_eval.replay import Recorder, RecordingGame
from big_walk_eval.tools import agent_tools, computer_tool_name
from big_walk_eval.tools.computer import png_content

OLD_SCREENSHOT = "[old screenshot removed]"


@dataclass
class Agent:
    slot: int
    name: str
    messages: list[ChatMessage]
    tools: list[Tool]


def trim_images(messages: list[ChatMessage], keep: int) -> list[ChatMessage]:
    """Copy of `messages` with all but the last `keep` images replaced by a text note."""
    out = list(messages)
    seen = 0
    for i in range(len(out) - 1, -1, -1):
        content = out[i].content
        if isinstance(content, str) or not any(isinstance(c, ContentImage) for c in content):
            continue
        new_content = []
        changed = False
        for c in reversed(content):
            if isinstance(c, ContentImage):
                seen += 1
                if seen > keep:
                    c = ContentText(text=OLD_SCREENSHOT)
                    changed = True
            new_content.append(c)
        if changed:
            new_content.reverse()
            out[i] = out[i].model_copy(update={"content": new_content})
    return out


@solver
def round_robin(
    game_factory: Callable[[], GameClient],
    config: EpisodeConfig,
    controls: str,
    game_name: str = "Big Walk",
    max_turns: int | None = None,
    game_lock: anyio.Lock | None = None,
) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        async with AsyncExitStack() as stack:
            if game_lock is not None:
                await stack.enter_async_context(game_lock)
            return await play(state)

    async def play(state: TaskState) -> TaskState:
        puzzle = PuzzleConfig.model_validate(state.metadata["puzzle"])
        n_agents = int(state.metadata["n_agents"])
        turn_limit = max_turns or puzzle.max_turns
        request = puzzle.reset_request(n_agents)
        names = {b.slot: b.name for b in request.bodies}
        log = state.store_as(EpisodeLog)
        log.puzzle_id = puzzle.id
        log.agents = {str(slot): name for slot, name in names.items()}

        # The sample input is not shown to agents. The merged transcript starts empty.
        state.messages = []
        recorder = Recorder()
        game = RecordingGame(game_factory(), recorder)
        episode = Episode(game, config, names, recorder=recorder)
        model = get_model()
        capturing = False
        try:
            start = await game.reset(request)
            if start.camera_hfov_deg:
                episode.hfov_deg = start.camera_hfov_deg
            episode.record_events(start.events)
            if config.capture_fps:
                await game.start_capture(
                    CaptureRequest(
                        episode_id=f"{puzzle.id}_{state.uuid}",
                        fps=config.capture_fps,
                        width=config.capture_width,
                        height=config.capture_height,
                    )
                )
                capturing = True
            agents = [
                Agent(
                    slot=slot,
                    name=name,
                    messages=[
                        ChatMessageSystem(
                            content=system_prompt(
                                name=name,
                                others=[o for o in names.values() if o != name],
                                game_name=game_name,
                                controls=controls,
                                max_game_ms=config.max_game_ms_per_turn,
                                max_tool_calls=config.max_tool_calls_per_turn,
                            )
                        )
                    ],
                    tools=agent_tools(episode, slot, computer_tool_name(model)),
                )
                for slot, name in names.items()
            ]
            for agent in agents:
                _mirror(state, agent, agent.messages, turn=-1)
            transcript().info(
                {
                    "puzzle": puzzle.id,
                    "agents": log.agents,
                    "turn_limit": turn_limit,
                    "hfov_deg": episode.hfov_deg,
                },
                source="big_walk_eval",
            )

            turn = 0
            while turn < turn_limit:
                agent = agents[turn % n_agents]
                async with span(f"turn {turn + 1}: {agent.name}", type="agent_turn"):
                    record = await _run_turn(episode, agent, turn, model, state, config)
                log.turns = [*log.turns, record]
                turn += 1
                if episode.all_voted:
                    log.ended_by_vote = True
                    break

            final = await game.state()
            episode.record_events(final.events)
            log.final_state = final.model_dump(mode="json", exclude={"events"})
            recorder.end(log.ended_by_vote, final)
            holder = final.reward_holder()
            summary = (
                f"{'Ended by vote' if log.ended_by_vote else 'Turn limit reached'} "
                f"after {turn} turns. Gourd held by: {holder.name if holder else 'nobody'}."
            )
            state.output = ModelOutput.from_content(model=str(model), content=summary)
        finally:
            log.n_turns = len(log.turns)
            log.votes = {names[s]: v for s, v in episode.votes.items()}
            log.events = [
                {"turn": r.turn, **r.event.model_dump(mode="json")} for r in episode.events
            ]
            log.total_game_ms = episode.total_game_ms
            log.replay = recorder.recording.model_dump(mode="json")
            if capturing:
                try:
                    info = await game.stop_capture()
                    log.capture = info.model_dump(mode="json") if info else None
                except Exception as e:
                    log.capture_error = f"{type(e).__name__}: {e}"
            await game.close()
        return state

    return solve


async def _run_turn(
    episode: Episode,
    agent: Agent,
    index: int,
    model: Model,
    state: TaskState,
    config: EpisodeConfig,
) -> dict:
    game = episode.game
    turn = episode.start_turn(index, agent.slot)
    await game.switch(agent.slot)
    png = await game.screenshot()
    header = ChatMessageUser(
        content=[
            ContentText(text=turn_header(turn=index, name=agent.name)),
            png_content(png),
        ]
    )
    agent.messages.append(header)
    _mirror(state, agent, [header], index)

    generates = 0
    for _ in range(config.max_generates_per_turn):
        output = await model.generate(
            trim_images(agent.messages, config.keep_images), tools=agent.tools
        )
        generates += 1
        agent.messages.append(output.message)
        _mirror(state, agent, [output.message], index)
        if not output.message.tool_calls:
            break
        result = await execute_tools(agent.messages, agent.tools)
        agent.messages.extend(result.messages)
        _mirror(state, agent, result.messages, index)
        if turn.done:
            break

    return {
        "turn": index,
        "slot": agent.slot,
        "name": agent.name,
        "generates": generates,
        "tool_calls": turn.tool_calls,
        "game_ms": turn.game_ms,
        "truncated": turn.truncated,
    }


def _mirror(state: TaskState, agent: Agent, messages: list[ChatMessage], turn: int) -> None:
    """Copy messages into the sample's merged transcript, tagged with the agent."""
    for m in messages:
        meta = {**(m.metadata or {}), "agent": agent.name, "slot": agent.slot, "turn": turn}
        state.messages.append(m.model_copy(update={"metadata": meta}))
