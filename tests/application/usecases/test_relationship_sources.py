# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for RelationshipTracker — the per-sender relationship seam (BOB-014).

The thin application adapter the compose path uses: given the perceived
:class:`Interlocutor`, it LOADS the current relationship (to shape tone + willingness
to compromise) before the reply and, after it, applies one turn's (stance, mood,
sentiment) via the pure :func:`apply_interaction` and persists the evolved state. It
keeps :class:`HandleMessage` pure of store plumbing and stays grounded — the update
is pure-domain, the store round-trips per ``sender_id``.
"""

from __future__ import annotations

from bob.application.usecases.relationship_sources import RelationshipTracker
from bob.domain.personality.interlocutor import Interlocutor, InterlocutorKind, Trust
from bob.domain.personality.mood import Mood
from bob.domain.personality.negotiation import Stance
from bob.domain.personality.relationship import Relationship

_GUEST_ID = 4242
_OWNER_ID = 1
_GUEST = Interlocutor(
    sender_id=_GUEST_ID,
    display_name="Алиса",
    kind=InterlocutorKind.GUEST,
    trust=Trust.GUEST,
)
_OWNER = Interlocutor(
    sender_id=_OWNER_ID,
    display_name="Влад",
    kind=InterlocutorKind.OWNER,
    trust=Trust.TRUSTED,
)
_ANON = Interlocutor(
    sender_id=None,
    display_name="незнакомец",
    kind=InterlocutorKind.GUEST,
    trust=Trust.GUEST,
)
_GOOD_MOOD = Mood(valence=0.6)


class _FakeStore:
    """In-memory RelationshipStore fake (UPSERT — an evolving relationship)."""

    def __init__(self) -> None:
        self.rows: dict[int, Relationship] = {}

    async def load(self, sender_id: int) -> Relationship | None:
        return self.rows.get(sender_id)

    async def save(self, relationship: Relationship) -> None:
        self.rows[relationship.sender_id] = relationship


def _tracker(store: _FakeStore) -> RelationshipTracker:
    return RelationshipTracker(store=store)


async def test_current_is_none_for_an_unknown_sender() -> None:
    tracker = _tracker(_FakeStore())

    assert await tracker.current(_GUEST) is None


async def test_record_interaction_creates_then_warms_a_relationship() -> None:
    store = _FakeStore()
    tracker = _tracker(store)

    await tracker.record_interaction(
        _OWNER, stance=Stance.CONCEDE, mood=_GOOD_MOOD, sentiment=0.6
    )

    saved = store.rows[_OWNER_ID]
    assert saved.sender_id == _OWNER_ID
    assert saved.warmth > 0.0


async def test_record_interaction_evolves_the_stored_relationship() -> None:
    store = _FakeStore()
    store.rows[_OWNER_ID] = Relationship(sender_id=_OWNER_ID, warmth=0.2)
    tracker = _tracker(store)

    await tracker.record_interaction(
        _OWNER, stance=Stance.CONCEDE, mood=_GOOD_MOOD, sentiment=0.6
    )

    assert store.rows[_OWNER_ID].warmth > 0.2


async def test_current_returns_the_stored_relationship() -> None:
    store = _FakeStore()
    rel = Relationship(sender_id=_GUEST_ID, warmth=0.5)
    store.rows[_GUEST_ID] = rel
    tracker = _tracker(store)

    assert await tracker.current(_GUEST) == rel


async def test_anonymous_sender_is_a_clean_no_op() -> None:
    # A sender with no id cannot be keyed — both ops are no-ops, never writing a row.
    store = _FakeStore()
    tracker = _tracker(store)

    assert await tracker.current(_ANON) is None
    await tracker.record_interaction(
        _ANON, stance=Stance.AGREE, mood=_GOOD_MOOD, sentiment=0.5
    )
    assert store.rows == {}


async def test_owner_and_guest_relationships_stay_isolated() -> None:
    store = _FakeStore()
    tracker = _tracker(store)

    await tracker.record_interaction(
        _OWNER, stance=Stance.CONCEDE, mood=_GOOD_MOOD, sentiment=0.8
    )
    await tracker.record_interaction(
        _GUEST,
        stance=Stance.PROPOSE_ALTERNATIVE,
        mood=Mood(valence=-0.6),
        sentiment=-0.6,
    )

    assert store.rows[_OWNER_ID].warmth > store.rows[_GUEST_ID].warmth
