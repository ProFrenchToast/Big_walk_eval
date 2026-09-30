from __future__ import annotations

from inspect_ai.tool import Tool, tool

from big_walk_eval.episode import Episode


@tool(parallel=False)
def end_episode(episode: Episode, slot: int) -> Tool:
    async def execute(withdraw: bool = False) -> str:
        """Vote to end the episode, or withdraw your vote.

        The episode ends when every player has an active vote. Your vote stays
        active until you withdraw it.

        Args:
          withdraw: Set to true to take back your vote.
        """
        episode.begin_tool_call(slot)
        episode.votes[slot] = not withdraw
        return "vote recorded"

    return execute
