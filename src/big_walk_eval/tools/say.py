from __future__ import annotations

from inspect_ai.tool import Tool, ToolError, tool

from big_walk_eval.episode import Episode

MAX_MESSAGE_CHARS = 500


@tool(parallel=False)
def say(episode: Episode, slot: int) -> Tool:
    async def execute(message: str) -> str:
        """Say something out loud. Only players near you hear it.

        Args:
          message: What to say.
        """
        turn = episode.begin_tool_call(slot)
        message = message.strip()
        if not message:
            raise ToolError("The message is empty.")
        message = message[:MAX_MESSAGE_CHARS]
        state = await episode.game.state()
        episode.record_events(state.events)
        positions = {b.slot: b.position for b in state.bodies}
        record = episode.chat.post(slot, message, turn.index, positions)
        episode.recorder.say(record)
        if episode.config.echo_chat:
            await episode.game.echo_chat(slot, message)
        return "sent"

    return execute
