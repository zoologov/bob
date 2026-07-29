# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Staleness/merge-gate harness (BOB-066 Срез 3.1) — drives the reassess contract.

The gate ships inert behind the deferred ``presence.staleness`` врезка, so its
observable behaviour is exercised here through its application collaborator
(:class:`~bob.application.runtime.staleness_reassessor.StalenessReassessor`) over the
pure gate, with a scripted judge standing in for the Tier-0/1 semantic read. The
acceptance steps read as living documentation of «Bob does not fire a stale reply»: a
reply whose point was already answered while he drafted it drops to a reaction, and a
same-author follow-up question merges into one deduplicated reply.
"""

from __future__ import annotations

from bob.application.runtime.events import MessageReceived
from bob.application.runtime.staleness_reassessor import StalenessReassessor
from bob.presence.staleness import (
    StalenessContext,
    StalenessGate,
    StalenessReading,
)

_BOB_USER_ID = 100
_AUTHOR_ID = 7


class _ScriptedJudge:
    """Verbalises a fixed reading regardless of the context it is handed."""

    def __init__(self, reading: StalenessReading) -> None:
        self._reading = reading

    async def assess(self, ctx: StalenessContext) -> StalenessReading:
        return self._reading


def _arrival(update_id: int, *, sender_id: int) -> MessageReceived:
    return MessageReceived(
        update_id=update_id,
        chat_id=1,
        message_id=update_id,
        text="что-то пришло за время генерации",
        sender_id=sender_id,
    )


async def reassess_outcome(
    *,
    answered_by_other: bool = False,
    topic_closed: bool = False,
    same_author_clarified: bool = False,
    new_direct_question: bool = False,
    arrival_author_id: int,
) -> str:
    """Run the reassess collaborator with a scripted judge read; return the outcome value."""
    judge = _ScriptedJudge(
        StalenessReading(
            answered_by_other=answered_by_other,
            topic_closed=topic_closed,
            same_author_clarified=same_author_clarified,
            new_direct_question=new_direct_question,
            reason="scripted",
        )
    )
    reassessor = StalenessReassessor(judge, StalenessGate())
    outcome = await reassessor.reassess(
        drafted="Боб уже написал ответ",
        newly_arrived=(_arrival(5, sender_id=arrival_author_id),),
        draft_author_sender_id=_AUTHOR_ID,
        bob_user_id=_BOB_USER_ID,
    )
    return outcome.value


DRAFT_AUTHOR_ID = _AUTHOR_ID
OTHER_ID = 9
