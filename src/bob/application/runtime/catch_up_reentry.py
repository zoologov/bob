# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app

"""CatchUpReentry (BOB-066 Срез W.3) — the re-entry tick over a per-chat worker's batch.

When Bob's per-chat worker drains a batch AFTER an away period, a living participant does not
replay each missed message one-by-one — he glances over the pile ONCE and answers the handful
that want him, under a budget. This collaborator is that «one reflective pass» decision at the
intake seam: given a drained batch, it decides whether this is a RE-ENTRY (the gap since Bob
last handled a message in this chat is at/beyond the absence threshold) and, if so, runs ONE
:class:`~bob.application.usecases.catch_up.CatchUp` pass over the batch projected onto the
presence domain's :class:`~bob.presence.catchup.BacklogMessage`, returning the focal-first
slice Bob acts on plus the peripheral ambient he skims.

🔴 INV-1/INV-10: a focal (direct-address) message is NEVER skimmed — only ambient beyond the
budget collapses (the pure :func:`~bob.presence.catchup.select_catchup` guarantees it). The
absence-hint TONE Bob speaks on re-entry is not threaded here: the reply tier already folds the
per-person «haven't-seen-you-in-a-while» texture (BOB-045 .3) into each answered turn.

Ships behind ``presence.catchup.enabled`` (OFF by default): disabled, :meth:`select` returns the
whole batch as a non-re-entry, so the worker handles every message exactly as before
(byte-identical). The transport-shaped addressivity is projected HERE, at this application seam
(it knows Bob's user id), by :func:`_to_backlog` — the presence domain stays free of
``MessageReceived`` and this ``runtime-app`` collaborator stays free of the ``usecases`` layer
(no import cycle).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.presence.catchup import BacklogMessage, is_reentry, select_catchup

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from bob.application.runtime.events import MessageReceived
    from bob.kernel.ports import Clock

# The default ambient salience for a backlogged message at the intake seam: the reflective
# «worth chiming in» read is a per-turn compose concern, not available here, so every message
# ranks on its BAND (focal vs ambient) + freshness — the load-bearing catch-up order.
_DEFAULT_BACKLOG_SALIENCE = 0.0


def _to_backlog(
    message: MessageReceived, *, bob_user_id: int, at: datetime
) -> BacklogMessage:
    """Project a runtime ``MessageReceived`` onto the presence domain's ``BacklogMessage``.

    An @mention of Bob or a reply to one of his messages is the focal band
    (``addressed_to_bob``) — the band :func:`~bob.presence.catchup.select_catchup` never drops.
    ``at`` is the arrival instant (``now`` at re-entry — a just-drained backlog is all recent) and
    ``salience`` the default ambient read, since ``MessageReceived`` carries neither. Kept local so
    this ``runtime-app`` seam does not import the ``usecases`` layer (no cycle).
    """
    addressed = message.mentions_bob or message.reply_to_sender_id == bob_user_id
    return BacklogMessage(
        sender_id=message.sender_id,
        text=message.text,
        addressed_to_bob=addressed,
        reply_to_bob_thread=False,
        salience=_DEFAULT_BACKLOG_SALIENCE,
        at=at,
    )


@dataclass(frozen=True, slots=True)
class CatchUpSelection:
    """What one re-entry check yields for a drained batch.

    ``to_handle`` is the slice the worker still runs (in arrival order — INV-5); on a re-entry it
    is the focal-first catch-up pick, otherwise the whole batch. ``skipped`` is the peripheral
    ambient the catch-up pass collapsed (empty when not a re-entry). ``is_reentry`` tells the
    worker whether this was a catch-up pass (so it answers the pick uncapped, not batch-budgeted).
    """

    to_handle: tuple[MessageReceived, ...]
    skipped: tuple[MessageReceived, ...]
    is_reentry: bool

    @classmethod
    def passthrough(cls, batch: Sequence[MessageReceived]) -> CatchUpSelection:
        """The no-op selection — handle the whole batch as before (catch-up off / normal flow)."""
        return cls(to_handle=tuple(batch), skipped=(), is_reentry=False)


class CatchUpReentry:
    """Decide the re-entry catch-up pass over a worker's drained batch (flag OFF by default)."""

    def __init__(
        self,
        *,
        clock: Clock,
        bob_user_id_source: Callable[[], int | None],
        absence_threshold_hours: float,
        budget: int,
        enabled: bool = False,
    ) -> None:
        self._clock = clock
        self._bob_user_id_source = bob_user_id_source
        self._absence_threshold_hours = absence_threshold_hours
        self._budget = budget
        self._enabled = enabled
        self._last_seen: dict[int, datetime] = {}

    def select(
        self, chat_id: int, batch: Sequence[MessageReceived]
    ) -> CatchUpSelection:
        """Return the catch-up selection for ``chat_id``'s drained ``batch`` (updates last-seen).

        Disabled (the default) or a non-re-entry (short gap / first batch / no Bob id) → the whole
        batch as a passthrough (byte-identical). A re-entry → one
        :func:`~bob.presence.catchup.select_catchup` pass: every focal message plus ambient up to
        the budget is handled (arrival order preserved — INV-5), the rest is skimmed. Records
        ``now`` as the chat's last-seen so the NEXT gap is measured from here.
        """
        now = self._clock.now()
        last_seen = self._last_seen.get(chat_id)
        self._last_seen[chat_id] = now
        bob_user_id = self._bob_user_id_source()
        if (
            not self._enabled
            or bob_user_id is None
            or not is_reentry(
                last_seen, now, threshold_hours=self._absence_threshold_hours
            )
        ):
            return CatchUpSelection.passthrough(batch)
        pairs = [
            (message, _to_backlog(message, bob_user_id=bob_user_id, at=now))
            for message in batch
        ]
        plan = select_catchup(
            [backlog for _, backlog in pairs], now=now, budget=self._budget
        )
        answered_ids = {id(backlog) for backlog in plan.to_answer}
        to_handle = tuple(m for m, b in pairs if id(b) in answered_ids)
        skipped = tuple(m for m, b in pairs if id(b) not in answered_ids)
        return CatchUpSelection(
            to_handle=to_handle, skipped=skipped, is_reentry=True
        )
