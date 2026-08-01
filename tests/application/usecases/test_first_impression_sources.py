# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for FirstImpressionTracker — the per-sender first-impression seam (BOB-019).

The thin application adapter the compose path uses: given the perceived
:class:`Interlocutor`, it reads any PRIOR first-impression note (recognised vs new)
before the reply and records a fresh, grounded note on FIRST contact after it. It
keeps :class:`HandleMessage` pure of store/clock plumbing and is grounded — the note
is derived from the interlocutor (no fabricated facts), the clock is injected.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.social.interlocutor import Interlocutor, InterlocutorKind, Trust
from bob.social.usecases.first_impression_sources import FirstImpressionTracker

if TYPE_CHECKING:
    from bob.social.first_impression import FirstImpression

_NOW = datetime(2026, 6, 22, 9, 0, tzinfo=UTC)
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


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _FakeStore:
    """In-memory FirstImpressionStore fake (DO-NOTHING on a known sender)."""

    def __init__(self) -> None:
        self.rows: dict[int, FirstImpression] = {}

    async def load(self, sender_id: int) -> FirstImpression | None:
        return self.rows.get(sender_id)

    async def save(self, impression: FirstImpression) -> None:
        self.rows.setdefault(impression.sender_id, impression)

    async def recent(self, *, limit: int) -> list[FirstImpression]:
        rows = sorted(self.rows.values(), key=lambda i: i.first_seen_at, reverse=True)
        return rows[:limit]


def _tracker(store: _FakeStore) -> FirstImpressionTracker:
    return FirstImpressionTracker(store=store, clock=_FixedClock(_NOW))


async def test_prior_impression_is_none_for_a_new_sender() -> None:
    tracker = _tracker(_FakeStore())

    assert await tracker.prior_impression(_GUEST) is None


async def test_note_first_contact_records_first_seen_for_a_new_sender() -> None:
    store = _FakeStore()
    tracker = _tracker(store)

    await tracker.note_first_contact(_GUEST)

    saved = store.rows[_GUEST_ID]
    assert saved.first_seen_at == _NOW
    assert saved.sender_id == _GUEST.sender_id
    assert saved.note.strip()


async def test_returning_sender_yields_the_prior_note() -> None:
    store = _FakeStore()
    tracker = _tracker(store)
    await tracker.note_first_contact(_GUEST)
    expected = store.rows[_GUEST_ID].note

    assert await tracker.prior_impression(_GUEST) == expected


async def test_note_first_contact_is_idempotent_first_seen_unchanged() -> None:
    store = _FakeStore()
    tracker = FirstImpressionTracker(store=store, clock=_FixedClock(_NOW))
    await tracker.note_first_contact(_GUEST)
    original = store.rows[_GUEST_ID]

    later = FirstImpressionTracker(
        store=store, clock=_FixedClock(datetime(2026, 7, 1, 12, 0, tzinfo=UTC))
    )
    await later.note_first_contact(_GUEST)

    assert store.rows[_GUEST_ID] == original


async def test_anonymous_sender_has_no_persisted_impression() -> None:
    # A sender with no id (sender_id is None) cannot be keyed/recognised — both ops
    # are clean no-ops, never raising and never writing a bogus row.
    store = _FakeStore()
    tracker = _tracker(store)

    assert await tracker.prior_impression(_ANON) is None
    await tracker.note_first_contact(_ANON)
    assert store.rows == {}


async def test_owner_is_tracked_too() -> None:
    store = _FakeStore()
    tracker = _tracker(store)

    await tracker.note_first_contact(_OWNER)

    assert _OWNER.sender_id in store.rows
    assert await tracker.prior_impression(_OWNER) == store.rows[_OWNER_ID].note
