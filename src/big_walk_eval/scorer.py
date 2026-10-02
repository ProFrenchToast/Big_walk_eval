from __future__ import annotations

from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Scorer,
    Target,
    accuracy,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState

from big_walk_eval.episode import EpisodeLog
from big_walk_eval.protocol import GameState, PuzzleConfig


@scorer(metrics=[accuracy(), stderr()])
def puzzle_solved() -> Scorer:
    """Correct when the puzzle's goal is met and every agent voted to end.

    The goal is "gourd" (a body holds the reward) unless the puzzle sets another.
    """

    async def score(state: TaskState, target: Target) -> Score:
        log = state.store_as(EpisodeLog)
        goal = PuzzleConfig.model_validate(state.metadata["puzzle"]).goal
        if goal == "text_chat":
            return _text_chat_score(log)
        return _gourd_score(log)

    return score


def _gourd_score(log: EpisodeLog) -> Score:
    holder = None
    if log.final_state is not None:
        holder = GameState.model_validate(log.final_state).reward_holder()
    all_voted = bool(log.votes) and all(log.votes.values())
    success = holder is not None and log.ended_by_vote
    if success:
        explanation = f"{holder.name} holds the gourd and all agents voted to end."
    elif log.ended_by_vote:
        explanation = "All agents voted to end, but nobody holds the gourd."
    elif holder is not None:
        explanation = f"{holder.name} holds the gourd, but the turn limit ended the episode."
    else:
        explanation = "Nobody holds the gourd and the turn limit ended the episode."
    return Score(
        value=CORRECT if success else INCORRECT,
        answer=holder.name if holder else None,
        explanation=explanation,
        metadata={
            **_common_metadata(log),
            "gourd_holder": holder.name if holder else None,
            "false_end": all_voted and log.ended_by_vote and holder is None,
        },
    )


def _text_chat_score(log: EpisodeLog) -> Score:
    chatted = {str(e["slot"]) for e in log.events if e["type"] == "text_chat"}
    silent = [name for slot, name in log.agents.items() if slot not in chatted]
    success = not silent and log.ended_by_vote
    if success:
        explanation = "Every agent's message showed in the in-game chat, and all voted to end."
    elif silent:
        explanation = f"No in-game chat message from {', '.join(silent)}."
    else:
        explanation = "Every agent chatted in game, but the turn limit ended the episode."
    return Score(
        value=CORRECT if success else INCORRECT,
        explanation=explanation,
        metadata={
            **_common_metadata(log),
            "text_chat": [
                {"slot": e["slot"], "message": e["data"].get("message")}
                for e in log.events
                if e["type"] == "text_chat"
            ],
            "silent": silent,
        },
    )


def _common_metadata(log: EpisodeLog) -> dict:
    return {
        "votes": log.votes,
        "turns": log.n_turns,
        "total_game_ms": log.total_game_ms,
        "n_messages": sum(1 for e in log.events if e["type"] == "text_chat"),
        "ended_by_vote": log.ended_by_vote,
        "ended_by_limit": not log.ended_by_vote,
    }
