from __future__ import annotations

from pathlib import Path

import pytest
from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalSample
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    ContentImage,
    ContentText,
    GenerateConfig,
    ModelOutput,
    get_model,
)

from big_walk_eval.episode import EpisodeConfig, EpisodeLog
from big_walk_eval.game.fake_game import FakeGame
from big_walk_eval.protocol import PuzzleConfig
from big_walk_eval.scripted import ScriptedPolicy, ScriptStep
from big_walk_eval.solver import OLD_SCREENSHOT, round_robin, trim_images


def step(*calls: tuple[str, dict]) -> ScriptStep:
    return ScriptStep(calls=[{f: a} for f, a in calls])


def chat(text: str) -> tuple[str, dict]:
    keys = [{"action": "key", "text": "Return"}]
    return ("computer", {"actions": [*keys, {"action": "type", "text": text}, *keys]})


def run(
    tmp_path: Path,
    puzzle: PuzzleConfig,
    agents: dict[str, list[ScriptStep]],
    config: EpisodeConfig | None = None,
    max_turns: int = 8,
    n_agents: int = 2,
    policy=None,
    game_factory=None,
) -> tuple[EvalSample, EpisodeLog]:
    task = Task(
        dataset=[
            Sample(input="play", metadata={"puzzle": puzzle.model_dump(), "n_agents": n_agents})
        ],
        solver=round_robin(
            game_factory or (lambda: FakeGame(seed=0)),
            config or EpisodeConfig(),
            controls="test controls",
            game_name="a test game",
            max_turns=max_turns,
        ),
    )
    model = get_model("mockllm/model", custom_outputs=policy or ScriptedPolicy(agents))
    [log] = eval(task, model=model, log_dir=str(tmp_path), display="none")
    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]
    return sample, sample.store_as(EpisodeLog)


def test_agents_chat_in_game(tmp_path, fake_puzzle):
    sample, log = run(
        tmp_path,
        fake_puzzle,
        {
            "Ash": [step(chat("hello Birch")), step(("end_episode", {}))],
            "Birch": [step(("end_episode", {}))],
        },
    )
    chats = [e for e in log.events if e["type"] == "text_chat"]
    assert [(e["turn"], e["slot"], e["data"]) for e in chats] == [
        (0, 1, {"message": "hello Birch"})
    ]
    birch_headers = [
        m
        for m in sample.messages
        if isinstance(m, ChatMessageUser) and (m.metadata or {}).get("agent") == "Birch"
    ]
    # Birch reads the chat in its view, not in the header.
    assert birch_headers[0].text == (
        "Turn 2. It is your turn, Birch.\nYour note:\n(empty)\nYour current view:"
    )
    assert log.ended_by_vote
    assert log.n_turns == 3
    assert log.votes == {"Ash": True, "Birch": True}


def test_votes_end_the_loop(tmp_path, fake_puzzle):
    _, log = run(
        tmp_path,
        fake_puzzle,
        {"Ash": [step(("end_episode", {}))], "Birch": [step(("end_episode", {}))]},
    )
    assert log.ended_by_vote
    assert log.n_turns == 2


def test_withdraw(tmp_path, fake_puzzle):
    _, log = run(
        tmp_path,
        fake_puzzle,
        {
            "Ash": [step(("end_episode", {}), ("end_episode", {"withdraw": True}))],
            "Birch": [step(("end_episode", {}))],
        },
        max_turns=4,
    )
    assert not log.ended_by_vote
    assert log.n_turns == 4
    assert log.votes == {"Ash": False, "Birch": True}


def test_max_turns_stops_the_loop(tmp_path, fake_puzzle):
    sample, log = run(tmp_path, fake_puzzle, {}, max_turns=5, n_agents=3)
    assert log.n_turns == 5
    assert [t["name"] for t in log.turns] == ["Ash", "Birch", "Cedar", "Ash", "Birch"]
    assert not log.ended_by_vote
    assert "Turn limit reached after 5 turns" in sample.output.completion


def test_tool_call_limit_in_loop(tmp_path, fake_puzzle):
    calls = [("computer", {"action": "screenshot"})] * 4
    sample, log = run(
        tmp_path,
        fake_puzzle,
        {"Ash": [step(*calls)]},
        config=EpisodeConfig(max_tool_calls_per_turn=3),
        max_turns=1,
    )
    assert log.turns[0]["tool_calls"] == 3
    results = [m for m in sample.messages if isinstance(m, ChatMessageTool)]
    assert [r.error is not None for r in results] == [False, False, False, True]


def test_game_time_budget_ends_turn(tmp_path, fake_puzzle):
    sample, log = run(
        tmp_path,
        fake_puzzle,
        {
            "Ash": [
                step(("computer", {"action": "hold_key", "text": "w", "duration": 5})),
                step(chat("second step")),
            ]
        },
        max_turns=1,
    )
    assert log.turns[0]["game_ms"] == 3000
    assert log.turns[0]["truncated"]
    assert log.turns[0]["generates"] == 1
    assert not [e for e in log.events if e["type"] == "text_chat"]


class ImageCountingPolicy(ScriptedPolicy):
    def __init__(self, agents):
        super().__init__(agents)
        self.max_images = 0

    def __call__(self, input, tools, tool_choice, config):
        n = sum(
            1
            for m in input
            if not isinstance(m.content, str)
            for c in m.content
            if isinstance(c, ContentImage)
        )
        self.max_images = max(self.max_images, n)
        return super().__call__(input, tools, tool_choice, config)


def test_old_screenshots_are_trimmed_in_loop(tmp_path, fake_puzzle):
    look = ("computer", {"action": "screenshot"})
    policy = ImageCountingPolicy({"Ash": [step(look, look)] * 4})
    _, log = run(
        tmp_path, fake_puzzle, {}, config=EpisodeConfig(keep_images=3), max_turns=7, policy=policy
    )
    assert log.n_turns == 7
    assert policy.max_images == 3


def test_trim_images_keeps_newest():
    def img(tag: str) -> ContentImage:
        return ContentImage(image=f"data:image/png;base64,{tag}")

    messages: list[ChatMessage] = [
        ChatMessageUser(content=[ContentText(text="a"), img("AAAA")]),
        ChatMessageTool(content=[img("BBBB")], tool_call_id="1", function="computer"),
        ChatMessageUser(content=[img("CCCC"), img("DDDD")]),
    ]
    trimmed = trim_images(messages, keep=2)
    assert trimmed[0].content[1] == ContentText(text=OLD_SCREENSHOT)
    assert trimmed[1].content[0] == ContentText(text=OLD_SCREENSHOT)
    assert trimmed[2] is messages[2]
    assert isinstance(messages[0].content[1], ContentImage)


@pytest.mark.parametrize("n_agents", [2, 3])
def test_every_message_is_tagged_with_its_agent(tmp_path, fake_puzzle, n_agents):
    sample, _ = run(tmp_path, fake_puzzle, {}, max_turns=n_agents, n_agents=n_agents)
    agents = {(m.metadata or {}).get("agent") for m in sample.messages}
    assert agents == {"Ash", "Birch", "Cedar"}.intersection(agents)
    assert None not in agents
    assert len(agents) == n_agents


def test_scripted_policy_runs_one_step_per_turn():
    """Inspect can move tool-result images into a trailing user message. That
    message must not start the next step: a step is one turn."""
    steps = [step(("end_episode", {})), step(("end_episode", {"withdraw": True}))]
    policy = ScriptedPolicy({"Ash": steps})
    header = ChatMessageUser(content="Turn 1. It is your turn, Ash.\nYour current view:")
    history: list[ChatMessage] = [ChatMessageSystem(content="Your name is Ash."), header]

    first = policy(history, [], "auto", GenerateConfig())
    assert first.message.tool_calls[0].arguments == {}
    history += [
        first.message,
        ChatMessageTool(content="vote recorded", tool_call_id=first.message.tool_calls[0].id),
        ChatMessageUser(content=[ContentImage(image="data:image/png;base64,AA==")]),
    ]
    assert not policy(history, [], "auto", GenerateConfig()).message.tool_calls

    history.append(ChatMessageUser(content="Turn 3. It is your turn, Ash."))
    second = policy(history, [], "auto", GenerateConfig())
    assert second.message.tool_calls[0].arguments == {"withdraw": True}
    assert isinstance(second.message, ChatMessageAssistant)


class AlwaysActPolicy(ScriptedPolicy):
    """Asks for another action every time it is called, so only the loop ends a turn."""

    def __init__(self):
        super().__init__({})
        self.calls = 0

    def __call__(self, input, tools, tool_choice, config):
        self.calls += 1
        return ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="computer",
            tool_arguments={"action": "key", "text": "w"},
        )


def test_one_response_per_turn(tmp_path, fake_puzzle):
    policy = AlwaysActPolicy()
    sample, log = run(tmp_path, fake_puzzle, {}, max_turns=4, policy=policy)
    assert policy.calls == 4
    assert [t["generates"] for t in log.turns] == [1, 1, 1, 1]
    tool_results = [m for m in sample.messages if isinstance(m, ChatMessageTool)]
    assert len(tool_results) == 4
    assert all(isinstance(m.content, str) for m in tool_results)
    images = [
        c
        for m in sample.messages
        if not isinstance(m.content, str)
        for c in m.content
        if isinstance(c, ContentImage)
    ]
    assert len(images) == 4


def test_screenshot_per_action_mode_keeps_generating(tmp_path, fake_puzzle):
    policy = AlwaysActPolicy()
    config = EpisodeConfig(one_response_per_turn=False, max_generates_per_turn=3)
    _, log = run(tmp_path, fake_puzzle, {}, config=config, max_turns=2, policy=policy)
    assert [t["generates"] for t in log.turns] == [3, 3]


def test_zoom_shows_in_the_next_turn_header(tmp_path, fake_puzzle):
    zoom = ("computer", {"action": "zoom", "region": [0, 0, 683, 384]})
    sample, _ = run(tmp_path, fake_puzzle, {"Ash": [step(zoom)]}, max_turns=3)
    ash_headers = [
        m
        for m in sample.messages
        if isinstance(m, ChatMessageUser) and (m.metadata or {}).get("agent") == "Ash"
    ]
    n_images = [sum(isinstance(c, ContentImage) for c in m.content) for m in ash_headers]
    assert n_images == [1, 2]
    assert "zoomed into [0, 0, 683, 384]" in ash_headers[1].text


def test_recent_keeps_system_prompt_and_last_turns():
    from inspect_ai.model import ChatMessageSystem, ChatMessageUser

    from big_walk_eval.solver import Agent, recent

    msgs = [ChatMessageSystem(content="sys")]
    agent = Agent(slot=1, name="Ash", messages=msgs, tools=[])
    for t in range(4):
        agent.turn_starts.append(len(agent.messages))
        agent.messages += [ChatMessageUser(content=f"turn {t}"), ChatMessageUser(content="x")]
    assert recent(agent, 0) is agent.messages
    kept = recent(agent, 2)
    assert [m.text for m in kept] == ["sys", "turn 2", "x", "turn 3", "x"]


async def test_note_tool_shows_in_header():
    from big_walk_eval.episode import Episode, EpisodeConfig
    from big_walk_eval.game.fake_game import FakeGame
    from big_walk_eval.prompts import turn_header
    from big_walk_eval.tools.note import note

    ep = Episode(FakeGame(seed=0), EpisodeConfig(memory_turns=2), {1: "Ash", 2: "Birch"})
    ep.start_turn(0, 1)
    await note(ep, 1)(text="vice on the north wall")
    assert "vice on the north wall" in turn_header(turn=1, name="Ash", note=ep.notes[1])


def test_turns_as_text_keeps_actions_and_drops_headers():
    from inspect_ai.model import ContentReasoning
    from inspect_ai.tool import ToolCall

    from big_walk_eval.solver import turns_as_text

    text = turns_as_text(
        [
            ChatMessageUser(
                content=[
                    ContentText(text="Turn 3. It is your turn, Ash.\nYour note:\nold"),
                    ContentImage(image="data:image/png;base64,AAAA"),
                ]
            ),
            ChatMessageAssistant(
                content=[
                    ContentReasoning(reasoning="", summary="a code on the wall: 7 3"),
                    ContentText(text="Going in."),
                ],
                tool_calls=[ToolCall(id="1", function="turn", arguments={"right_deg": 90})],
            ),
            ChatMessageTool(content="Turned.", tool_call_id="1", function="turn"),
        ]
    )
    assert text.splitlines() == [
        "Turn 3. It is your turn, Ash.",
        "[screenshot]",
        "Your thinking: a code on the wall: 7 3",
        "You wrote: Going in.",
        'You called: turn({"right_deg": 90})',
        "Result: Turned.",
    ]


def test_summary_and_note_reminder(tmp_path, fake_puzzle):
    scripted = ScriptedPolicy(
        {
            "Ash": [
                step(("note", {"section": "facts", "text": "code 7 3"})),
                step(("end_episode", {})),
            ]
        }
    )
    summary_inputs = []

    def policy(input, tools, tool_choice, config):
        if "Write a new summary" in input[-1].text:
            summary_inputs.append(input[-1].text)
            return ModelOutput.from_content(
                model="mockllm/model", content=f"S{len(summary_inputs)}"
            )
        return scripted(input, tools, tool_choice, config)

    sample, log = run(
        tmp_path,
        fake_puzzle,
        {},
        config=EpisodeConfig(memory_turns=3, note_every=2, summary_every=2),
        max_turns=6,
        policy=policy,
    )
    headers = {
        (m.metadata["agent"], m.metadata["turn"]): m.text
        for m in sample.messages
        if isinstance(m, ChatMessageUser)
    }
    # Each agent is summarised once, after its first 2 turns (Ash before turn 5, Birch before 6).
    assert [(s["name"], s["turn"], s["text"]) for s in log.summaries] == [
        ("Ash", 4, "S1"),
        ("Birch", 5, "S2"),
    ]
    assert 'You called: note({"section": "facts", "text": "code 7 3"})' in summary_inputs[0]
    assert "Summary of your earlier turns:\nS1" in headers[("Ash", 4)]
    assert "Facts about the puzzle: code 7 3" in headers[("Ash", 2)]
    assert "You last updated your note 1 of your turns ago." in headers[("Ash", 2)]
    assert "Update your note this turn" not in headers[("Birch", 3)]
    assert "Update your note this turn" in headers[("Birch", 5)]


async def test_section_note_replaces_one_section():
    from inspect_ai.tool import ToolError

    from big_walk_eval.episode import Episode
    from big_walk_eval.tools.note import section_note

    ep = Episode(FakeGame(seed=0), EpisodeConfig(note_every=4), {1: "Ash", 2: "Birch"})
    ep.start_turn(0, 1)
    write = section_note(ep, 1)
    await write(section="facts", text="a")
    await write(section="plan", text="b")
    await write(section="facts", text="c")
    assert ep.note_sections[1] == {"facts": "c", "plan": "b"}
    with pytest.raises(ToolError, match="section must be"):
        await write(section="misc", text="d")
