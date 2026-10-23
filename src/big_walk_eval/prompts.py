"""System prompt and per-turn header for each agent.

Keep puzzle-specific hints out of these. A general description of the reward is fine.
"""

from __future__ import annotations

# Read from the game's Rewired keyboard and mouse maps with the bridge `controls`
# command (game 1.5.1 2608271531). The game has no separate hands: you carry one thing.
BIG_WALK_CONTROLS = """\
- Walk: hold W (forward), S (back), A (left), D (right). For example hold_key with text "w" and duration 1. \
You walk about 1.5 meters per second. Hold shift as well to run ("shift+w").
- Look around: mouse_move to the point you want to look at. That point moves to the center of your view.
- Use: left_click. This picks up an object, presses a switch or button, or puts what you carry \
into a place where it fits. You carry what you pick up until you drop it, \
also while other players act. You can carry one thing at a time.
- Aim before you use: a small thin white ring shows on what a left_click would act on, near the \
center of your view, when it is near enough: an object you can pick up, a button you can press, or \
a place where the thing you carry fits (for example a hole for a peg). No ring means a left_click \
does nothing. So point at the thing first (mouse_move) and end your turn there. If your next \
screenshot shows the ring on it, left_click without a coordinate. If not, move closer or point \
more exactly. left_click with a coordinate turns and clicks at once, so you cannot check the ring.
- Drop: right_click drops what you carry.
- Hold a button down: left_mouse_down keeps "use" pressed, also while other players act, until left_mouse_up.
- Jump: key "space". Crouch: hold "ctrl". Sit down: key "z", and "z" again to stand up. \
Wave: hold "q" (left arm) or "e" (right arm), for example hold_key with text "q" and duration 1."""

MOUSE_LOOK_LINE = (
    "- Look around: mouse_move to the point you want to look at. "
    "That point moves to the center of your view."
)
TURN_LOOK_LINE = (
    "- Look around: the `turn` tool turns your head by degrees, for example right_deg=90 "
    "(a quarter turn right), right_deg=-90 (left), right_deg=180 (turn around), or "
    "up_deg=-30 (look down). Your view is about 120 degrees wide. mouse_move also turns "
    "your head to a point on the screen."
)


def with_turn_tool(controls: str) -> str:
    """Controls text for agents that have the `turn` tool."""
    return controls.replace(MOUSE_LOOK_LINE, TURN_LOOK_LINE)


LOOK_AROUND_LINE = (
    "- See all around you: the `look_around` action shows four views (front, right, "
    "behind, left) at the start of your next turn. You end facing the same way."
)


def with_look_around(controls: str) -> str:
    """Controls text for agents that can use `look_around`."""
    return controls.replace(MOUSE_LOOK_LINE, MOUSE_LOOK_LINE + "\n" + LOOK_AROUND_LINE)


BIG_WALK_GOURD = """\
The gourd is a small red object shaped like a pear. It is often locked in a vice \
that opens when the puzzle is solved."""

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
    reward_description: str = "",
    max_game_ms: int,
    max_tool_calls: int,
    one_response: bool = True,
    memory_turns: int = 0,
) -> str:
    n = len(others) + 1
    reward = f" {reward_description}" if reward_description else ""
    if one_response:
        turns = f"""\
The game pauses while you think. Time moves only while your actions run. \
The players take turns. Each turn starts with a screenshot of your current view, and you \
give one reply. Put everything you want to do this turn in that reply: several tool \
calls, or one call with a list of `actions`. They run in order, and each returns only a \
short text result, not a screenshot. Then your turn ends and the other players take \
their turns. You see the result in the screenshot at the start of your next turn. \
In one turn you can use up to {max_tool_calls} tool calls and up to \
{max_game_ms / 1000:g} seconds of game time."""
    else:
        turns = f"""\
The game pauses while you think. Time moves only while your actions run. \
The players take turns. In your turn you can use up to {max_tool_calls} tool calls and \
up to {max_game_ms / 1000:g} seconds of game time. Your turn ends when you reply without \
a tool call, or when you reach a limit. Then the other players take their turns."""
    if memory_turns:
        turns += f"""

You remember only your last {memory_turns} turns. Keep what you need later (what you \
have seen and where, what the other players said, and your plan) with the `note` tool. \
Each call replaces your note, and your note is shown at the start of every turn."""
    return f"""\
You are one of {n} players in the game {game_name}. Your name is {name}. \
The other players are {", ".join(others)}.

Goal: work with the other players to solve the puzzle near you and get the reward, a gourd. \
At least one player must hold the gourd at the end.{reward}

You see only your own first-person view. The other players see different views. \
Tell them what you see, and ask them what they see.

You start facing the other players. First introduce yourselves, then agree on a plan \
to solve the puzzle.

To talk, use the in-game text chat: press Enter (`key` "Return"), write your message \
with `type`, and press Enter again to send it. While the chat is open, your keys go into \
the message and you do not move. The chat box holds about 35 characters, and the game \
drops anything longer, so send several short messages. Close the chat with Enter before \
you move. Your message shows above your head, not in a chat log. \
The other players read it in their own view, so a player reads it only while they look \
at you and are near enough. Chat carries like sound: walls, closed rooms, and distance \
fade it or block it, and radios, intercoms, and speakers can show it somewhere else. \
You are not told who read your message. In the same way, you read what another player \
says only above their head, in your view. When a player out of your view talks, a speech \
bubble appears at the edge of your view on the side where they are: turn that way to \
read it. To read small text, `zoom` into that part of your view.

{turns}

Controls:
{controls}

When a player holds the gourd and you agree that the task is done, call `end_episode`. \
The episode ends only when all players have called it. You can withdraw your vote with \
`end_episode(withdraw=true)`."""


def turn_header(*, turn: int, name: str, note: str | None = None) -> str:
    head = f"Turn {turn + 1}. It is your turn, {name}.\n"
    if note is not None:
        head += f"Your note:\n{note or '(empty)'}\n"
    return head + "Your current view:"
