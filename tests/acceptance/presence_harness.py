# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Presence rhythm harness (BOB-066 Срез 2.3) — drives the ритм-слой contracts.

The presence rhythm layer ships inert behind the ``presence.rhythm`` flag, so its
observable behaviour is exercised here through its two application collaborators —
:class:`~bob.application.runtime.share_of_voice_gate.ShareOfVoiceGate` (the ambient
ceiling) and :class:`~bob.application.runtime.delayed_turn.DelayedTurn` (the human
delay floor) — over the pure presence policies. The acceptance steps read as living
documentation of «Bob keeps a human rhythm»: he throttles himself when he has hogged
the room, never throttles a direct address, and never fires back inhumanly fast.
"""

from __future__ import annotations

from bob.application.runtime.delayed_turn import DelayedTurn
from bob.application.runtime.share_of_voice_gate import ShareOfVoiceGate
from bob.presence.natural_delay import NaturalDelayPolicy
from bob.presence.outgoing_activity import OutgoingActivity
from bob.presence.share_of_voice import ShareOfVoicePolicy


class _FixedActivityStore:
    """Serves one fixed share-of-voice window regardless of chat_id."""

    def __init__(self, activity: OutgoingActivity) -> None:
        self._activity = activity

    async def load(self, chat_id: int) -> OutgoingActivity:
        return self._activity


class _AdvancingClock:
    """A monotonic clock whose ``sleep`` advances it — no real time passes."""

    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


async def ambient_barge_admitted(
    *,
    bob_sent: int,
    total_seen: int,
    distinct_senders: int,
    focused: bool,
    base_probability: float,
    draw: float,
) -> bool:
    """Return whether Bob barges into an ambient turn under his share-of-voice window."""
    activity = OutgoingActivity(
        bob_sent=bob_sent, total_seen=total_seen, distinct_senders=distinct_senders
    )
    gate = ShareOfVoiceGate(_FixedActivityStore(activity), ShareOfVoicePolicy())
    return await gate.admits_barge(
        chat_id=1, focused=focused, base_probability=base_probability, draw=draw
    )


async def reply_top_up_delay(*, reply: str) -> float:
    """Return the human delay (seconds) added when a reply generates instantly."""
    clock = _AdvancingClock()
    turn = DelayedTurn(
        NaturalDelayPolicy(), sleep=clock.sleep, monotonic=clock.monotonic
    )

    async def generate() -> str:
        return reply

    await turn.deliver(generate, complexity=0.0, urgency=0.0)
    return clock.slept[0] if clock.slept else 0.0
