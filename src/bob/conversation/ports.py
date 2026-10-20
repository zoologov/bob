# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=domain

"""Conversation ports — the durable seams behind Bob's continuity in a thread.

The per-thread conversation-floor store (:class:`ConversationFloorStore`, BOB-025),
the cross-session closer ring (:class:`CloserLog`, BOB-061), and the negotiation-zone
classifier (:class:`ZoneClassifier`, a turn decision — it owns *which* territory the
topic falls in), and the pre-answer verify search (:class:`VerifySearch` returning a
:class:`HasAnswer`, BOB-113 — the narrow consumer-side view of a web search: the verify
step reads one field, so it owns the one-field contract instead of importing the
capabilities port, ISP). These are *interfaces only*: structural :class:`typing.Protocol`
definitions with no implementations; the SQLite-backed adapters live in
``bob.conversation.adapters``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bob.conversation.conversation_floor import ConversationFloor
    from bob.personality.negotiation import NegotiationZone
    from bob.personality.taste import Verdict


@runtime_checkable
class ConversationFloorStore(Protocol):
    """Durable per-thread store for the conversation floor (BOB-025).

    Round-trips the :class:`bob.conversation.conversation_floor.ConversationFloor`
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
    (:func:`~bob.conversation.conversation.is_recurring_closer_tic`) can see a motif
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


@runtime_checkable
class ZoneClassifier(Protocol):
    """Classify a topic into a :class:`NegotiationZone` for Bob's stance.

    Decides *who owns the matter at hand* — Bob's own territory of opinions
    (``BOB_PERSONAL``), the user's own business (``USER_DOMAIN``), or jointly
    owned (``SHARED``) — so :class:`~bob.personality.negotiation.Negotiation` can
    pick how firmly Bob holds. The contract is abstract on purpose: the default
    realisation is a deterministic taste/keyword heuristic, but a Tier-0 LLM
    classifier swaps in later without any consumer change. It returns a
    :class:`~bob.personality.negotiation.NegotiationZone` — a conversation→personality
    read (the turn asks the character which stance-territory a topic falls in).
    """

    def classify(
        self,
        topic: str,
        *,
        taste_verdict: Verdict,
        conviction: float,
    ) -> NegotiationZone:
        """Return the negotiation zone that owns ``topic``."""
        ...


class HasAnswer(Protocol):
    """The one field the pre-answer verify reads from a search result (BOB-113 E).

    A structural, read-only view: anything exposing a ``str`` ``answer`` satisfies it —
    the capabilities ``WebSearchResult`` (a frozen dataclass, so ``answer`` is read-only;
    hence a property here, not a settable attribute) fits as-is, and so does a minimal
    test double that knows nothing of ``sources``.
    """

    @property
    def answer(self) -> str:
        """The grounded answer text (may be blank — the caller treats blank as «empty»)."""
        ...


class VerifySearch(Protocol):
    """The ONE direct web search the pre-answer verify makes (BOB-057 .2, BOB-113 E).

    The consumer-side port of
    :class:`~bob.conversation.usecases.verify_step.VerifyStep`: «query in, something with
    an ``answer`` out». It mirrors the method shape of the capabilities web-search port
    on purpose, so the existing adapter is wired in unchanged and satisfies it
    structurally; the conversation vertical never imports ``bob.capabilities`` for it.
    An implementation RAISES on failure — the verify step turns any failure, timeout or
    blank answer into an honest hedge.
    """

    async def search(self, query: str) -> HasAnswer:
        """Return a result whose ``answer`` grounds the turn (raises on failure)."""
        ...
