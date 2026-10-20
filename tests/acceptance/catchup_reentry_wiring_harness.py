# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Catch-up re-entry WIRING acceptance harness (BOB-066 Срез W.3).

Drives the REAL intake seam (:class:`~bob.application.runtime.intake.dispatcher.ChatDispatcher`
+ the real :class:`~bob.application.runtime.catch_up_reentry.CatchUpReentry`) with a scripted
handler that records which messages it actually handled — exactly as ``HandleMessage`` would.
So the re-entry scenarios witness the OBSERVABLE «catch up like a person» behaviour through the
boundary: after an away period a backlogged direct question is answered in ONE pass while the
ambient asides beyond budget are skimmed — without booting the LLM graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from bob.application.runtime.catch_up_reentry import CatchUpReentry
from bob.application.runtime.intake import ChatDispatcher, make_focus_predicate
from bob.kernel.events import MessageReceived

if TYPE_CHECKING:
    from bob.application.runtime.intake.scope import TurnScope

CHAT_ID = 42
BOB_ID = 500

_T0 = datetime(2026, 7, 29, 9, 0, 0, tzinfo=UTC)


class _AdvancingClock:
    """Returns each queued instant in turn (one per drained batch)."""

    def __init__(self, *instants: datetime) -> None:
        self._instants = list(instants)

    def now(self) -> datetime:
        return self._instants.pop(0)


@dataclass(slots=True)
class CatchUpObservations:
    """What the acceptance steps witness through the boundary."""

    handled: list[int] = field(default_factory=list)


def _msg(message_id: int, *, mentions_bob: bool = False) -> MessageReceived:
    return MessageReceived(
        update_id=message_id,
        chat_id=CHAT_ID,
        message_id=message_id,
        text=f"сообщение {message_id}",
        sender_id=1,
        sender_name="Norman",
        mentions_bob=mentions_bob,
    )


async def run_reentry(*, enabled: bool) -> CatchUpObservations:
    """Drive a first batch (establishes last-seen), then a backlog after a long gap.

    The backlog carries ONE direct address to Bob among ambient chatter. On re-entry (ON) the
    direct address is answered while the ambient beyond budget 1 is skimmed; OFF replays all.
    """
    observations = CatchUpObservations()

    async def handle(message: MessageReceived, _scope: TurnScope) -> None:
        observations.handled.append(message.message_id)

    reentry = (
        CatchUpReentry(
            clock=_AdvancingClock(_T0, _T0 + timedelta(hours=6)),
            bob_user_id_source=lambda: BOB_ID,
            absence_threshold_hours=4.0,
            budget=1,
            enabled=True,
        )
        if enabled
        else None
    )
    dispatcher = ChatDispatcher(
        handle=handle,
        base_seed=1,
        is_focused=make_focus_predicate(lambda: BOB_ID),
        catch_up_reentry=reentry,
    )
    # Batch 1 at T0 establishes Bob's last-seen in this chat.
    dispatcher.submit(_msg(1))
    await dispatcher.wait_for_idle()
    # Batch 2 — the away-period backlog — lands after a 6h gap.
    dispatcher.submit(_msg(2))
    dispatcher.submit(_msg(3, mentions_bob=True))
    dispatcher.submit(_msg(4))
    dispatcher.submit(_msg(5))
    await dispatcher.wait_for_idle()
    await dispatcher.aclose()
    return observations
