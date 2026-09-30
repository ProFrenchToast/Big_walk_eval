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
    get_model,
)

from big_walk_eval.episode import EpisodeConfig, EpisodeLog
from big_walk_eval.game.fake_game import FakeGame
from big_walk_eval.protocol import PuzzleConfig
from big_walk_eval.scripted import ScriptedPolicy, ScriptStep
from big_walk_eval.solver import OLD_SCREENSHOT, round_robin, trim_images


def step(*calls: tuple[str, dict], wait_for: str | None = None) -> ScriptStep:
    return ScriptStep(wait_for=wait_for, calls=[{f: a} for f, a in calls])


def run(
    tmp_path: Path,
    puzzle: PuzzleConfig,
    agents: dict[str, list[ScriptStep]],
    config: EpisodeConfig | None = None,
    max_turns: int = 8,
    n_agents: int = 2,
    policy=None,
) -> tuple[EvalSample, EpisodeLog]:
    task = Task(
        dataset=[
            Sample(input="play", metadata={"puzzle": puzzle.model_dump(), "n_agents": n_agents})
        ],
        solver=round_robin(
            lambda: FakeGame(seed=0),
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


def test_chat_in_range_arrives(tmp_path, fake_puzzle):
    sample, log = run(
        tmp_path,
        fake_puzzle,
        {
            "Ash": [step(("say", {"message": "hello Birch"})), step(("end_episode", {}))],
            "Birch": [step(("end_episode", {}), wait_for="hello Birch")],
        },
    )
    assert log.chat == [
        {
            "turn": 0,
            "sender": 1,
            "sender_name": "Ash",
            "text": "hello Birch",
            "sender_position": [-5.0, 0.0, 0.0],
            "recipients": [2],
        }
    ]
    birch_headers = [
        m
        for m in sample.messages
        if isinstance(m, ChatMessageUser) and (m.metadata or {}).get("agent") == "Birch"
    ]
    assert 'Ash: "hello Birch"' in birch_headers[0].text
    assert log.ended_by_vote
    assert log.n_turns == 3
    assert log.votes == {"Ash": True, "Birch": True}


def test_chat_out_of_range_does_not_arrive(tmp_path, fake_puzzle):
    _, log = run(
        tmp_path,
        fake_puzzle,
        {
            "Ash": [step(("say", {"message": "hello Birch"})), step(("end_episode", {}))],
            "Birch": [step(("end_episode", {}), wait_for="hello Birch")],
        },
        config=EpisodeConfig(chat_range_m=1.0),
        max_turns=6,
    )
    assert log.chat[0]["recipients"] == []
    assert not log.ended_by_vote
    assert log.n_turns == 6
    assert log.votes == {"Ash": True, "Birch": False}


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
                step(("say", {"message": "second step"})),
            ]
        },
        max_turns=1,
    )
    assert log.turns[0]["game_ms"] == 3000
    assert log.turns[0]["truncated"]
    assert log.turns[0]["generates"] == 1
    assert log.chat == []


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
    steps = [step(("say", {"message": "one"})), step(("say", {"message": "two"}))]
    policy = ScriptedPolicy({"Ash": steps})
    header = ChatMessageUser(content="Turn 1. It is your turn, Ash.\nYour current view:")
    history: list[ChatMessage] = [ChatMessageSystem(content="Your name is Ash."), header]

    first = policy(history, [], "auto", GenerateConfig())
    assert first.message.tool_calls[0].arguments == {"message": "one"}
    history += [
        first.message,
        ChatMessageTool(content="sent", tool_call_id=first.message.tool_calls[0].id),
        ChatMessageUser(content=[ContentImage(image="data:image/png;base64,AA==")]),
    ]
    assert not policy(history, [], "auto", GenerateConfig()).message.tool_calls

    history.append(ChatMessageUser(content="Turn 3. It is your turn, Ash."))
    second = policy(history, [], "auto", GenerateConfig())
    assert second.message.tool_calls[0].arguments == {"message": "two"}
    assert isinstance(second.message, ChatMessageAssistant)
