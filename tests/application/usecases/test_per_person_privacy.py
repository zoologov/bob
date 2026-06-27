# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the BOB-045 per-person memory PRIVACY core (🔴 US-4 invariant).

Two pure module helpers behind the per-person dialogue memory carry the privacy
boundary, so they are tested in isolation here (the end-to-end wiring is covered by
``test_handle_message.py``):

* :func:`~bob.application.usecases.handle_message._scoped_recall` — the recall
  audience filter. The owner keeps GLOBAL recall (trusted); an unwired perception
  seam keeps global recall (pre-BOB-045 behaviour); a NON-owner only ever sees
  recalled items attributed to THEIR OWN ``sender_id`` — every owner-private
  (``sender_id`` ``None``) or foreign (a different ``sender_id``) item is dropped, and
  a non-owner with no resolved identity gets NOTHING (the safe default). This is the
  🔴 privacy invariant proven at the unit boundary.
* :func:`~bob.application.usecases.handle_message._last_seen_at` — the freshest
  prior-turn timestamp behind the absence hint (BOB-045 .3), parsed from the replayed
  per-person history (ISO string or a typed ``datetime``), tolerant of garbled/absent
  timestamps.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.application.usecases.handle_message import _last_seen_at, _scoped_recall
from bob.domain.personality.interlocutor import (
    Interlocutor,
    InterlocutorKind,
    Trust,
)

if TYPE_CHECKING:
    from bob.domain.ports import Recalled

_OWNER_ID = 1
_GUEST_ID = 2
_OTHER_ID = 3


def _owner() -> Interlocutor:
    return Interlocutor(
        sender_id=_OWNER_ID,
        display_name="Vova",
        kind=InterlocutorKind.OWNER,
        trust=Trust.TRUSTED,
    )


def _guest(sender_id: int | None = _GUEST_ID) -> Interlocutor:
    return Interlocutor(
        sender_id=sender_id,
        display_name="Norman",
        kind=InterlocutorKind.GUEST,
        trust=Trust.GUEST,
    )


def _hit(content: str, sender_id: int | None) -> Recalled:
    return {"content": content, "category": "personal", "sender_id": sender_id}


# A mixed recall pool: an owner-private fact (None), the guest's own memory, and a
# THIRD person's memory — the audience filter must keep only the current person's.
def _mixed_pool() -> list[Recalled]:
    return [
        _hit("owner private secret", None),
        _hit("norman own memory", _GUEST_ID),
        _hit("other person memory", _OTHER_ID),
    ]


# --- _scoped_recall: owner + unwired keep GLOBAL recall -----------------------


def test_owner_recall_is_global_and_unchanged() -> None:
    # The owner is trusted: every item is kept (no scoping), order preserved.
    pool = _mixed_pool()

    scoped = _scoped_recall(pool, interlocutor=_owner(), is_owner=True)

    assert list(scoped) == pool


def test_unwired_perception_keeps_global_recall() -> None:
    # No perceived interlocutor (seam unwired) -> recall stays global (pre-BOB-045).
    pool = _mixed_pool()

    scoped = _scoped_recall(pool, interlocutor=None, is_owner=False)

    assert list(scoped) == pool


# --- 🔴 _scoped_recall: a NON-owner only ever sees their OWN episodes ----------


def test_guest_recall_drops_owner_and_foreign_and_none() -> None:
    # 🔴 PRIVACY INVARIANT: a guest sees ONLY their own sender_id; an owner-private
    # (None) fact and a third person's (foreign id) memory are both dropped.
    scoped = _scoped_recall(_mixed_pool(), interlocutor=_guest(), is_owner=False)

    contents = [str(item["content"]) for item in scoped]
    assert contents == ["norman own memory"]


def test_guest_recall_drops_every_none_sender_item() -> None:
    # Owner-private memory is modelled as a None sender_id; a non-owner never sees it.
    pool = [_hit("owner secret a", None), _hit("owner secret b", None)]

    scoped = _scoped_recall(pool, interlocutor=_guest(), is_owner=False)

    assert list(scoped) == []


def test_guest_recall_keeps_all_of_their_own_items() -> None:
    # Every item attributed to the guest survives (the filter is not over-eager).
    pool = [
        _hit("mine 1", _GUEST_ID),
        _hit("foreign", _OTHER_ID),
        _hit("mine 2", _GUEST_ID),
    ]

    scoped = _scoped_recall(pool, interlocutor=_guest(), is_owner=False)

    assert [str(i["content"]) for i in scoped] == ["mine 1", "mine 2"]


def test_non_owner_without_sender_id_gets_no_recall() -> None:
    # 🔴 A non-owner with no RESOLVED identity has no scopable thread -> empty recall
    # (the safe default — never fall back to global, which would leak owner memory).
    scoped = _scoped_recall(
        _mixed_pool(), interlocutor=_guest(sender_id=None), is_owner=False
    )

    assert list(scoped) == []


def test_known_non_owner_is_scoped_like_a_guest() -> None:
    # The boundary is owner-vs-non-owner, not guest-specific: a KNOWN (trusted but not
    # owner) person is still scoped to their own episodes.
    known = Interlocutor(
        sender_id=_GUEST_ID,
        display_name="Ada",
        kind=InterlocutorKind.KNOWN,
        trust=Trust.TRUSTED,
    )

    scoped = _scoped_recall(_mixed_pool(), interlocutor=known, is_owner=False)

    assert [str(i["content"]) for i in scoped] == ["norman own memory"]


def test_empty_pool_scopes_to_empty() -> None:
    # No recall at all -> empty, for owner and guest alike (no crash on empty input).
    assert list(_scoped_recall([], interlocutor=_owner(), is_owner=True)) == []
    assert list(_scoped_recall([], interlocutor=_guest(), is_owner=False)) == []


# --- _last_seen_at: freshest prior-turn timestamp (BOB-045 .3) ----------------


def _turn(*, ts: object) -> dict[str, object]:
    return {"content": "Norman: hi\nbob: hey", "event_type": "message", "ts": ts}


def test_last_seen_parses_iso_string() -> None:
    # The freshest prior turn carries an ISO-8601 string (the stored form).
    fresh = datetime(2026, 6, 27, 9, 0, tzinfo=UTC)
    history = [_turn(ts="2026-06-26T08:00:00+00:00"), _turn(ts=fresh.isoformat())]

    assert _last_seen_at(history) == fresh


def test_last_seen_accepts_a_typed_datetime() -> None:
    # A row may already carry a typed datetime (not a string) — accepted as-is.
    fresh = datetime(2026, 6, 27, 9, 0, tzinfo=UTC)

    assert _last_seen_at([_turn(ts=fresh)]) == fresh


def test_last_seen_empty_history_is_none() -> None:
    # First contact: no prior turn -> None (the absence hint then never fires).
    assert _last_seen_at([]) is None


def test_last_seen_skips_garbled_then_uses_an_earlier_valid_ts() -> None:
    # A garbled freshest ts is skipped (no crash); the next parseable one is used.
    good = datetime(2026, 6, 25, 7, 0, tzinfo=UTC)
    history = [_turn(ts=good.isoformat()), _turn(ts="not-a-timestamp")]

    assert _last_seen_at(history) == good


def test_last_seen_all_invalid_is_none() -> None:
    # No parseable timestamp anywhere -> None (never raises).
    history = [_turn(ts="garbage"), _turn(ts=None), _turn(ts=12345)]

    assert _last_seen_at(history) is None
