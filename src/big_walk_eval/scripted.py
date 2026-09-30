"""A fixed policy that plays the model's role, for tests and scripted runs.

Pass a `ScriptedPolicy` as `custom_outputs` to Inspect's `mockllm` model. It
runs the real turn loop and the real tools, with no LLM. Each agent has a
list of steps. A step is one generate call with a fixed list of tool calls.
A step with `wait_for` runs only after the agent has heard a chat message
that contains that text. The policy reads its progress from the agent's own
history, so one instance can serve many samples.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import yaml
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
)
from inspect_ai.tool import ToolCall, ToolChoice, ToolInfo
from pydantic import BaseModel, Field

MODEL_NAME = "mockllm/model"
_NAME = re.compile(r"Your name is (\w+)\.")


class ScriptStep(BaseModel):
    wait_for: str | None = None
    calls: list[dict[str, dict[str, Any]]] = Field(default_factory=list)

    def tool_calls(self) -> list[ToolCall]:
        out = []
        for call in self.calls:
            [(function, arguments)] = call.items()
            out.append(
                ToolCall(id=f"call_{uuid.uuid4().hex[:12]}", function=function, arguments=arguments)
            )
        return out


class Script(BaseModel):
    puzzle: str
    agents: dict[str, list[ScriptStep]]

    @classmethod
    def load(cls, path: str | Path) -> Script:
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))


class ScriptedPolicy:
    def __init__(self, script: Script | dict[str, list[ScriptStep]]) -> None:
        self.agents = script.agents if isinstance(script, Script) else script

    def __call__(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        name = self._agent_name(input)
        if not isinstance(input[-1], ChatMessageUser):
            return _text("End of my turn.")
        done = sum(1 for m in input if isinstance(m, ChatMessageAssistant) and m.tool_calls)
        steps = self.agents.get(name, [])
        if done >= len(steps):
            return _text("I have nothing more to do.")
        step = steps[done]
        if step.wait_for and step.wait_for.lower() not in _heard(input).lower():
            return _text(f"Waiting to hear {step.wait_for!r}.")
        return ModelOutput(
            model=MODEL_NAME,
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=f"Step {done + 1}.",
                        model=MODEL_NAME,
                        source="generate",
                        tool_calls=step.tool_calls(),
                    ),
                    stop_reason="tool_calls",
                )
            ],
        )

    @staticmethod
    def _agent_name(input: list[ChatMessage]) -> str:
        for m in input:
            if isinstance(m, ChatMessageSystem):
                match = _NAME.search(m.text)
                if match:
                    return match.group(1)
        raise ValueError("no agent name in the system prompt")


def _heard(input: list[ChatMessage]) -> str:
    return "\n".join(m.text for m in input if isinstance(m, ChatMessageUser))


def _text(content: str) -> ModelOutput:
    return ModelOutput.from_content(model=MODEL_NAME, content=content)
