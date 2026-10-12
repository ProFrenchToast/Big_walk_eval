from __future__ import annotations

from inspect_ai.tool import Tool, ToolError, tool

from big_walk_eval.episode import Episode

MAX_NOTE_CHARS = 1500


@tool(parallel=False)
def note(episode: Episode, slot: int) -> Tool:
    async def execute(text: str) -> str:
        """Replace your note. Your note is shown at the start of every turn.

        You remember only your last few turns, so keep here what you need later:
        what you have seen and where, what the other players said, and your plan.

        Args:
          text: The whole new note. It replaces the old one.
        """
        episode.begin_tool_call(slot)
        if len(text) > MAX_NOTE_CHARS:
            raise ToolError(f"The note can have at most {MAX_NOTE_CHARS} characters.")
        episode.notes[slot] = text
        return "Note saved."

    return execute
