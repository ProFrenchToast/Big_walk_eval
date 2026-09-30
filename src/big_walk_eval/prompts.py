"""System prompt and per-turn header for each agent. Keep puzzle hints out of these."""

from __future__ import annotations

from big_walk_eval.chat import ChatRecord

# TODO(controls): Patrick to confirm the Big Walk keys and buttons (walk, jump,
# crouch, grab with each hand) before the first real run.
BIG_WALK_CONTROLS = """\
- Walk: hold W (forward), S (back), A (left), D (right). For example hold_key with text "w" and duration 1.
- Look around: mouse_move to the point you want to look at. That point moves to the center of your view.
- Hands: the left mouse button uses your left hand and the right mouse button uses your right hand. \
Press and keep the button down to grab and hold something in front of you (left_mouse_down). \
Release it to let go (left_mouse_up). A held button stays held until you release it, also while other players act.
- Jump: space."""

FAKE_GAME_CONTROLS = """\
- Walk: hold W (forward), S (back), A (left), D (right). Hold shift as well to walk faster. \
You walk 2 meters per second.
- Look around: mouse_move to the point you want to look at. That point moves to the center of your view.
- Hands: press and keep the left mouse button down (left_mouse_down) to pick up an object within 1.5 meters \
with your left hand. Release it (left_mouse_up) to put the object down. The right mouse button does the same \
with your right hand. A held button stays held until you release it, also while other players act.
- The bottom-left corner of your view shows what your hands hold."""


def system_prompt(
    *,
    name: str,
    others: list[str],
    game_name: str,
    controls: str,
    max_game_ms: int,
    max_tool_calls: int,
) -> str:
    n = len(others) + 1
    return f"""\
You are one of {n} players in the game {game_name}. Your name is {name}. \
The other players are {", ".join(others)}.

Goal: work with the other players to solve the puzzle near you and get the reward, a gourd. \
At least one player must hold the gourd at the end.

You see only your own first-person view. The other players see different views. \
Tell them what you see, and ask them what they see.

You can talk only with the `say` tool. Players far away from you do not hear you, \
and you are not told who heard you.

The game pauses while you think. Time moves only while your actions run. \
The players take turns. In your turn you can use up to {max_tool_calls} tool calls and \
up to {max_game_ms / 1000:g} seconds of game time. Your turn ends when you reply without \
a tool call, or when you reach a limit. Then the other players take their turns.

Controls:
{controls}

When a player holds the gourd and you agree that the task is done, call `end_episode`. \
The episode ends only when all players have called it. You can withdraw your vote with \
`end_episode(withdraw=true)`."""


def turn_header(*, turn: int, name: str, inbox: list[ChatRecord]) -> str:
    lines = [f"Turn {turn + 1}. It is your turn, {name}."]
    if inbox:
        lines.append("Since your last turn you heard:")
        lines += [f'- {m.sender_name}: "{m.text}"' for m in inbox]
    else:
        lines.append("You heard nothing since your last turn.")
    lines.append("Your current view:")
    return "\n".join(lines)
