from inspect_ai.tool import Tool

from big_walk_eval.episode import Episode
from big_walk_eval.tools.computer import computer_tool
from big_walk_eval.tools.end_episode import end_episode
from big_walk_eval.tools.say import say


def agent_tools(episode: Episode, slot: int) -> list[Tool]:
    return [computer_tool(episode, slot), say(episode, slot), end_episode(episode, slot)]


__all__ = ["agent_tools", "computer_tool", "end_episode", "say"]
