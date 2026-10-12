from __future__ import annotations

from inspect_ai.tool import Tool, ToolError, tool

from big_walk_eval.episode import Episode
from big_walk_eval.protocol import LookAction

MAX_TURN_DEG = 180.0
MAX_PITCH_DEG = 80.0


@tool(parallel=False)
def turn(episode: Episode, slot: int) -> Tool:
    async def execute(right_deg: float = 0.0, up_deg: float = 0.0) -> str:
        """Turn your head by a number of degrees.

        For example right_deg=90 turns a quarter turn right, right_deg=-90 a quarter
        turn left, and right_deg=180 turns around. up_deg tilts your view up, and a
        negative up_deg tilts it down.

        Args:
          right_deg: Degrees to turn right, -180 to 180. Negative turns left.
          up_deg: Degrees to look up, -80 to 80. Negative looks down.
        """
        state = episode.begin_tool_call(slot)
        try:
            right, up = float(right_deg), float(up_deg)
        except (TypeError, ValueError) as e:
            raise ToolError("`right_deg` and `up_deg` must be numbers.") from e
        if abs(right) > MAX_TURN_DEG or abs(up) > MAX_PITCH_DEG:
            raise ToolError(
                f"`right_deg` must be within ±{MAX_TURN_DEG:g} "
                f"and `up_deg` within ±{MAX_PITCH_DEG:g}."
            )
        if state.remaining_ms == 0:
            raise ToolError("You have no game time left this turn. The action did not run.")
        result = await episode.game.act(
            slot, [LookAction(dyaw_deg=right, dpitch_deg=-up)], state.remaining_ms
        )
        episode.add_game_time(result.game_ms, result.truncated)
        episode.record_events(result.events)
        return (
            f"Turned {right:g} degrees right and {up:g} degrees up. "
            f"{state.remaining_ms} ms left this turn."
        )

    return execute
