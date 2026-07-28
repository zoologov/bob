# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=application

"""Relationship source adapter — the live seam the compose path reads (BOB-014).

A thin application adapter that keeps :class:`HandleMessage` pure of store plumbing
for Bob's per-person relationship quality:

* :meth:`RelationshipTracker.current` LOADS the relationship Bob has with the
  perceived :class:`~bob.social.interlocutor.Interlocutor` (an unknown
  sender → ``None``), so the compose path can colour his tone (warmth) and nudge his
  willingness to compromise (warmth + compatibility) for THIS person.
* :meth:`RelationshipTracker.record_interaction` updates the relationship AFTER the
  turn: it loads the current state (or starts neutral), applies one turn's
  ``(stance, mood, sentiment)`` via the pure
  :func:`~bob.social.relationship.apply_interaction`, and persists the
  evolved state (the store UPSERTs, so a relationship accrues over many turns).

A sender with no id (``sender_id is None``) cannot be keyed, so both operations are
clean no-ops for them. This is per-PERSON data (about THEM), NOT owner-private memory
— safe even for a guest. The per-interaction deltas are injected so config can tune
them; defaults are the small (≈0.05) domain defaults.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.social.relationship import Relationship, apply_interaction

if TYPE_CHECKING:
    from bob.domain.ports import RelationshipStore
    from bob.personality.mood import Mood
    from bob.personality.negotiation import Stance
    from bob.social.interlocutor import Interlocutor
    from bob.social.relationship import RelationshipDeltas


class RelationshipTracker:
    """Load the current relationship + record one turn's evolution (per sender)."""

    def __init__(
        self, *, store: RelationshipStore, deltas: RelationshipDeltas | None = None
    ) -> None:
        self._store = store
        self._deltas = deltas

    async def current(self, interlocutor: Interlocutor) -> Relationship | None:
        """Return Bob's current relationship with this sender, or ``None``.

        A known sender (already on record) yields his stored relationship so the
        compose path can colour tone + willingness; an unknown sender — or one with no
        id — yields ``None`` (no read formed yet, so the turn behaves as a neutral one).
        """
        if interlocutor.sender_id is None:
            return None
        return await self._store.load(interlocutor.sender_id)

    async def record_interaction(
        self,
        interlocutor: Interlocutor,
        *,
        stance: Stance,
        mood: Mood,
        sentiment: float,
    ) -> None:
        """Evolve + persist the relationship from this turn's (stance, mood, sentiment).

        Loads the current relationship (or starts neutral for a new sender), applies
        one bounded interaction via the pure
        :func:`~bob.social.relationship.apply_interaction`, and UPSERTs the
        evolved state so it accrues over turns. A sender with no id is a clean no-op
        (cannot be keyed or recognised later).
        """
        if interlocutor.sender_id is None:
            return
        current = await self._store.load(interlocutor.sender_id)
        rel = (
            current
            if current is not None
            else Relationship(sender_id=interlocutor.sender_id)
        )
        evolved = apply_interaction(
            rel,
            stance=stance,
            mood=mood,
            sentiment=sentiment,
            deltas=self._deltas,
        )
        await self._store.save(evolved)
