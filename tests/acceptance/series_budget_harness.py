# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Batch top-k budget WIRING harness for the BDD acceptance layer (BOB-066 Срез W.2).

Drives the REAL intake seam (:class:`~bob.application.runtime.intake.dispatcher.ChatDispatcher`
+ the real focus predicate + the REAL series-salience plan) with a scripted handler that ACTS
on the ceiling the worker stamped on each turn's scope — exactly as ``HandleMessage`` will:
``ENGAGE`` → a reply, ``REACT`` → a like, ``SILENT`` → nothing. So the burst/focus scenarios
witness the OBSERVABLE collapse through the boundary — several inbound → ONE addressed reply +
a budget-capped like, and a direct address is always answered (INV-1) — without booting the LLM
graph (mirroring the ``intake_harness`` approach for the intake-развязка).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bob.application.runtime.intake import ChatDispatcher, make_focus_predicate
from bob.conversation.addressivity import ResponseOutcome
from bob.kernel.events import MessageReceived

if TYPE_CHECKING:
    from bob.application.runtime.intake.scope import TurnScope

# The chat + Bob identity the harness drives; an @mention of BOB_ID reads focused.
CHAT_ID = 42
BOB_ID = 500


@dataclass(slots=True)
class SeriesObservations:
    """What the acceptance steps witness through the boundary for a settled burst."""

    replies: list[int] = field(default_factory=list)
    likes: list[int] = field(default_factory=list)

    @property
    def reply_count(self) -> int:
        return len(self.replies)

    @property
    def like_count(self) -> int:
        return len(self.likes)


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


async def _drive(
    *, enabled: bool, specs: list[tuple[int, str, bool]]
) -> SeriesObservations:
    observations = SeriesObservations()

    async def handle(message: MessageReceived, scope: TurnScope) -> None:
        # Act on the ceiling exactly as HandleMessage will: reply / like / stay silent.
        if scope.series_ceiling is ResponseOutcome.ENGAGE:
            observations.replies.append(message.message_id)
        elif scope.series_ceiling is ResponseOutcome.REACT:
            observations.likes.append(message.message_id)

    dispatcher = ChatDispatcher(
        handle=handle,
        base_seed=1,
        is_focused=make_focus_predicate(lambda: BOB_ID),
        series_budget_enabled=enabled,
        series_max_reactions=1,
    )
    for message in _burst(*specs):
        dispatcher.submit(message)
    await dispatcher.aclose()
    return observations


async def drive_ambient_burst(*, enabled: bool) -> SeriesObservations:
    """A burst of ambient chatter (no direct address) — collapses to one reply + a like when on."""
    return await _drive(
        enabled=enabled,
        specs=[
            (1, "сегодня дождь весь день", False),
            (2, "ага, промок пока шёл", False),
            (3, "а у нас солнце", False),
        ],
    )


async def drive_burst_with_a_direct_address(*, enabled: bool) -> SeriesObservations:
    """A burst of ambient chatter with ONE direct address — the address is always answered."""
    return await _drive(
        enabled=enabled,
        specs=[
            (1, "болтаем про своё", False),
            (2, "Bob, что думаешь про зонды?", True),
            (3, "дальше болтаем", False),
        ],
    )
