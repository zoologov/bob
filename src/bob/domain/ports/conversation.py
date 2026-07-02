# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Conversation ports — the durable seams behind Bob's continuity in a thread.

The per-thread conversation-floor store (:class:`ConversationFloorStore`, BOB-025)
and the cross-session closer ring (:class:`CloserLog`, BOB-061). These are
*interfaces only*: structural :class:`typing.Protocol` definitions with no
implementations; the SQLite-backed adapters live in ``bob.infrastructure``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bob.domain.personality.conversation_floor import ConversationFloor


@runtime_checkable
class ConversationFloorStore(Protocol):
    """Durable per-thread store for the conversation floor (BOB-025).

    Round-trips the :class:`bob.domain.personality.conversation_floor.ConversationFloor`
    — who currently holds the "talking turn" in a thread (Bob / another person / idle),
    when that holder was last confirmed, and the silent-ambient streak — so the
    continuity read survives a restart and across heartbeat ticks. Keyed by the THREAD
    (``chat_id`` + an optional ``thread_id`` for a forum topic; ``None`` for the main
    chat), since the floor is a property of one running exchange, not of a person.
    :meth:`load` returns the default IDLE floor for a thread that has never been seen,
    so the application always has something to read. :meth:`save` UPSERTs — the floor
    advances every turn, so each turn re-saves the newer state. The concrete
    SQLite-backed adapter lives in ``bob.infrastructure.persistence``.
    """

    async def load(self, chat_id: int, thread_id: int | None) -> ConversationFloor:
        """Return the persisted floor for the thread (default IDLE if unseen)."""
        ...

    async def save(
        self, chat_id: int, thread_id: int | None, floor: ConversationFloor
    ) -> None:
        """Persist ``floor`` for the thread (UPSERT — an advancing floor is updated)."""
        ...


@runtime_checkable
class CloserLog(Protocol):
    """Bounded, local ring of Bob's recent reply CLOSERS across sessions (BOB-061 .1).

    Closes gap 1 (cross-session sparsity): the signature closer-tic recurs ONCE PER
    SESSION over days, so the live session window sees it 0-1x — below the tic bar — and
    the tic slips through. This light ring PERSISTS Bob's normalised closer after each
    reply, surviving restarts, so the near-verbatim tic detector
    (:func:`~bob.domain.personality.conversation.is_recurring_closer_tic`) can see a motif
    scattered across sessions and finally catch it. Deliberately tiny and PRIVATE — Bob's
    OWN memory of how he tends to end turns, only normalised closer phrases (never full
    replies), capped at a small size (the oldest fall off the ring). :meth:`append` logs
    one closer (a blank/whitespace closer is ignored); :meth:`recent` returns the last
    ``k`` closers (most-recent first). The concrete SQLite-backed adapter
    (``SqliteCloserLog``) lives in ``bob.infrastructure.persistence``.
    """

    async def append(self, closer: str) -> None:
        """Append ``closer`` to the ring (a blank closer is ignored); prune to the cap."""
        ...

    async def recent(self, k: int) -> tuple[str, ...]:
        """Return the last ``k`` logged closers, most-recent first (empty when none)."""
        ...
