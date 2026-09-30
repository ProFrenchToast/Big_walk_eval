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
from big_walk_eval.protocol import GameState


@scorer(metrics=[accuracy(), stderr()])
def gourd_held() -> Scorer:
    """Correct when a body holds the gourd and every agent voted to end."""

    async def score(state: TaskState, target: Target) -> Score:
        log = state.store_as(EpisodeLog)
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
                "gourd_holder": holder.name if holder else None,
                "votes": log.votes,
                "turns": log.n_turns,
                "total_game_ms": log.total_game_ms,
                "n_messages": len(log.chat),
                "ended_by_vote": log.ended_by_vote,
                "ended_by_limit": not log.ended_by_vote,
                "false_end": all_voted and log.ended_by_vote and holder is None,
            },
        )

    return score
