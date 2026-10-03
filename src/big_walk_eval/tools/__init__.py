from inspect_ai.model import Model
from inspect_ai.tool import Tool, ToolDef

from big_walk_eval.episode import Episode
from big_walk_eval.tools.computer import computer_tool
from big_walk_eval.tools.end_episode import end_episode

# Inspect's Google provider sends every past call of a tool named "computer" back to
# Gemini as a native computer-use action (named from the call id, e.g. "call", with no
# arguments), also for Gemini models without native computer use. Those models then
# copy the broken calls (seen with gemini-3.1-flash-lite and gemini-3.7-flash). They
# get the same tool under another name.
GOOGLE_NATIVE_COMPUTER_USE = ("gemini-2.5-computer-use-preview", "gemini-3-flash-preview")
RENAMED_COMPUTER_TOOL = "game"


def computer_tool_name(model: Model | str | None) -> str:
    name = str(model or "")
    if name.startswith("google/") and not any(m in name for m in GOOGLE_NATIVE_COMPUTER_USE):
        return RENAMED_COMPUTER_TOOL
    return "computer"


def agent_tools(episode: Episode, slot: int, computer_name: str = "computer") -> list[Tool]:
    computer = computer_tool(episode, slot)
    if computer_name != "computer":
        computer = ToolDef(computer, name=computer_name).as_tool()
    return [computer, end_episode(episode, slot)]


__all__ = ["agent_tools", "computer_tool", "computer_tool_name", "end_episode"]
