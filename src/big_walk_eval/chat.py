"""Range-limited text chat between agents."""

from __future__ import annotations

import math

from pydantic import BaseModel

from big_walk_eval.protocol import Vec3


class ChatRecord(BaseModel):
    turn: int
    sender: int
    sender_name: str
    text: str
    sender_position: Vec3
    recipients: list[int]


class ChatRouter:
    """Delivers each message to the agents within `range_m` of the sender at send time.

    Recipients read their messages at the start of their next turn.
    """

    def __init__(self, range_m: float, names: dict[int, str]) -> None:
        self.range_m = range_m
        self.names = names
        self.log: list[ChatRecord] = []
        self._inbox: dict[int, list[ChatRecord]] = {slot: [] for slot in names}

    def post(self, sender: int, text: str, turn: int, positions: dict[int, Vec3]) -> ChatRecord:
        origin = positions[sender]
        recipients = [
            slot
            for slot in self.names
            if slot != sender
            and slot in positions
            and math.dist(origin, positions[slot]) <= self.range_m
        ]
        record = ChatRecord(
            turn=turn,
            sender=sender,
            sender_name=self.names[sender],
            text=text,
            sender_position=origin,
            recipients=recipients,
        )
        self.log.append(record)
        for slot in recipients:
            self._inbox[slot].append(record)
        return record

    def deliver(self, slot: int) -> list[ChatRecord]:
        messages, self._inbox[slot] = self._inbox[slot], []
        return messages
