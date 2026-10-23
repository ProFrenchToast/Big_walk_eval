from __future__ import annotations

from inspect_ai.tool import Tool, ToolError, tool

from big_walk_eval.episode import Episode
from big_walk_eval.prompts import NOTE_SECTIONS

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
        episode.turns_since_note[slot] = 0
        return "Note saved."

    return execute


MAX_SECTION_CHARS = 600


@tool(name="note", parallel=False)
def section_note(episode: Episode, slot: int) -> Tool:
    async def execute(section: str, text: str) -> str:
        """Replace one section of your note. Your note is shown at the start of every turn.

        You remember only your last few turns, so keep here what you need later.
        The other sections stay as they are.

        Args:
          section: The section to replace: "facts" (facts about the puzzle, copied
            exactly: text, symbols, numbers, colours, counts), "players" (what the other
            players said, and what you told them), "places" (where things and players
            are), "tried" (what you tried and what happened), or "plan" (what you
            agreed, and your plan).
          text: The whole new text of that section.
        """
        episode.begin_tool_call(slot)
        if section not in NOTE_SECTIONS:
            raise ToolError(f"section must be one of: {', '.join(NOTE_SECTIONS)}.")
        if len(text) > MAX_SECTION_CHARS:
            raise ToolError(f"A section can have at most {MAX_SECTION_CHARS} characters.")
        episode.note_sections.setdefault(slot, {})[section] = text
        episode.turns_since_note[slot] = 0
        return f"Note section {section!r} saved."

    return execute
