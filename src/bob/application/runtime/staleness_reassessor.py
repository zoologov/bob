# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app

"""StalenessReassessor (BOB-066 Срез 3.1) — the app collaborator over the staleness gate.

Just before ``gateway.reply``, a living participant checks whether the room shifted
while he was drafting. This collaborator is that check as one decision: given the
drafted reply and what landed during generation — a non-draining
:meth:`~bob.application.runtime.intake.inbox.ChatInbox.peek_since` of the intake buffer
from Срез 2.1, passed IN so no second buffer is built — it maps each
:class:`~bob.kernel.events.MessageReceived` to the presence domain's
value-shaped :class:`~bob.presence.staleness.ArrivedMessage`, consults the semantic
:class:`~bob.presence.ports.StalenessJudge` ONLY when something landed, and returns the
pure :class:`~bob.presence.staleness.StalenessGate` outcome (SEND / REWRITE /
DROP_TO_LIKE / MERGE).

🔴 **B2 = B7.** Post-generation reassessment and mid-generation interruption are one
primitive — both hand this collaborator the draft + the burst that arrived behind it.

The transport-shaped signals (reply-to-Bob, same-author) are derived HERE, at the
application seam that knows Bob's user id and who Bob is drafting a reply to; the
presence domain stays free of ``MessageReceived``. The gate ships **inert**: the
hot-path врезка into ``handle_message`` (and its ``presence.staleness`` flag in the
composition root) is deferred to keep ``handle_message`` off the Cohesion-guard — until
it is wired, the production reply path is unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.presence.staleness import ArrivedMessage, StalenessContext, nothing_arrived

if TYPE_CHECKING:
    from bob.kernel.events import MessageReceived
    from bob.presence.ports import StalenessJudge
    from bob.presence.staleness import StalenessGate, StalenessOutcome


def _to_arrived(
    message: MessageReceived,
    *,
    draft_author_sender_id: int | None,
    bob_user_id: int,
) -> ArrivedMessage:
    """Project a runtime ``MessageReceived`` onto the domain's value-shaped arrival."""
    reply_to_bob = message.reply_to_sender_id == bob_user_id
    from_draft_author = (
        message.sender_id is not None
        and message.sender_id == draft_author_sender_id
    )
    return ArrivedMessage(
        sender_id=message.sender_id,
        text=message.text,
        mentions_bob=message.mentions_bob,
        reply_to_bob=reply_to_bob,
        from_draft_author=from_draft_author,
    )


class StalenessReassessor:
    """Reassess a drafted reply against what landed during generation (one decision)."""

    def __init__(self, judge: StalenessJudge, gate: StalenessGate) -> None:
        self._judge = judge
        self._gate = gate

    async def reassess(
        self,
        *,
        drafted: str,
        newly_arrived: tuple[MessageReceived, ...],
        draft_author_sender_id: int | None,
        bob_user_id: int,
    ) -> StalenessOutcome:
        """Return the gate outcome for ``drafted`` given the peeked ``newly_arrived`` burst.

        Nothing landed → the gate's structural SEND, with no judge call. Otherwise the
        judge verbalises the shift over the value-shaped arrivals and the pure gate
        decides the outcome.
        """
        arrived = tuple(
            _to_arrived(
                message,
                draft_author_sender_id=draft_author_sender_id,
                bob_user_id=bob_user_id,
            )
            for message in newly_arrived
        )
        if nothing_arrived(arrived):
            return self._gate.reassess(arrived, None)
        reading = await self._judge.assess(
            StalenessContext(drafted=drafted, newly_arrived=arrived)
        )
        return self._gate.reassess(arrived, reading)
