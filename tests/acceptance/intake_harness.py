# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Intake-развязка harness for the BDD acceptance layer (BOB-066 Срез 2.1).

Drives the REAL intake seam (:class:`~bob.application.runtime.intake.dispatcher.
ChatDispatcher` + the real focus predicate) with a scripted per-turn handler, so the
burst/focus scenarios assert Bob's OBSERVABLE intake behaviour — submit never blocks, a
chat's burst is handled in arrival order, a focused message is answered — without booting
the whole LLM graph. The handler stands in for ``HandleMessage.handle``: it records the
turn and (for a focused message) emits a reply into the boundary.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bob.application.runtime.events import MessageReceived
from bob.application.runtime.intake import ChatDispatcher, make_focus_predicate
from bob.application.runtime.intake.focus import message_is_focused

if TYPE_CHECKING:
    from bob.application.runtime.intake.scope import TurnScope

# The chat + Bob identity the harness drives; a reply-to / @mention of BOB_ID reads focused.
CHAT_ID = 42
BOB_ID = 500
_SCRIPTED_REPLY = "Да, я здесь — слушаю."


@dataclass(slots=True)
class IntakeObservations:
    """What the acceptance steps witness through the intake boundary."""

    handled_order: list[int] = field(default_factory=list)
    replies: list[tuple[int, str]] = field(default_factory=list)
    submit_returned_before_generation: bool = False

    @property
    def answered_message_ids(self) -> list[int]:
        return [message_id for message_id, _ in self.replies]


def _burst(*specs: tuple[int, str, bool]) -> list[MessageReceived]:
    """Build a burst of messages: ``(message_id, text, mentions_bob)`` each."""
    return [
        MessageReceived(
            update_id=message_id,
            chat_id=CHAT_ID,
            message_id=message_id,
            text=text,
            sender_id=1,
            sender_name="Norman",
            mentions_bob=mentions_bob,
        )
        for message_id, text, mentions_bob in specs
    ]


async def drive_ordered_burst_without_stalling() -> IntakeObservations:
    """Submit a 3-message burst while a turn is 'generating'; observe non-blocking order.

    The handler blocks on a gate to model Bob still generating the first reply; the three
    submits must all return BEFORE that gate releases (submit is non-blocking), and the
    per-chat worker must then handle the burst in arrival order.
    """
    observations = IntakeObservations()
    generating = asyncio.Event()

    async def handle(message: MessageReceived, _scope: TurnScope) -> None:
        await generating.wait()
        observations.handled_order.append(message.message_id)

    dispatcher = ChatDispatcher(
        handle=handle, base_seed=1, is_focused=make_focus_predicate(lambda: BOB_ID)
    )
    for message in _burst((1, "раз", False), (2, "два", False), (3, "три", False)):
        dispatcher.submit(message)
    # All three submits returned though the handler is still blocked → the poller never
    # stalls on Bob's generation.
    observations.submit_returned_before_generation = not observations.handled_order
    generating.set()
    await dispatcher.aclose()
    return observations


async def drive_focused_message_in_a_burst() -> IntakeObservations:
    """Submit a burst of ambient replies with ONE direct address to Bob; observe the reply.

    The handler replies only to a focused message (a real :func:`message_is_focused`
    check) — proving the focused turn reaches handling and is answered, never dropped.
    """
    observations = IntakeObservations()

    async def handle(message: MessageReceived, _scope: TurnScope) -> None:
        observations.handled_order.append(message.message_id)
        if message_is_focused(message, bob_user_id=BOB_ID):
            observations.replies.append((message.message_id, _SCRIPTED_REPLY))

    dispatcher = ChatDispatcher(
        handle=handle, base_seed=1, is_focused=make_focus_predicate(lambda: BOB_ID)
    )
    for message in _burst(
        (1, "болтаем про своё", False),
        (2, "Боб, что думаешь?", False),
        (3, "дальше болтаем", False),
    ):
        dispatcher.submit(message)
    await dispatcher.aclose()
    return observations
