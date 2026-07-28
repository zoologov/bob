# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the absence-hint timestamp helper (BOB-045 .3).

The pure module helper behind the per-person absence hint is tested in isolation here
(the end-to-end wiring is covered by ``test_handle_message.py``):

* :func:`~bob.application.usecases.handle_message._last_seen_at` — the freshest
  prior-turn timestamp behind the absence hint (BOB-045 .3), parsed from the replayed
  per-person history (ISO string or a typed ``datetime``), tolerant of garbled/absent
  timestamps.

The former per-person recall audience filter (``_scoped_recall``) was removed in
BOB-051: memory is now UNIFIED for the closed group, so recall is no longer scoped by
``sender_id`` — privacy moved off memory and onto privileges (tools / inner-life /
owner-data), covered by the privilege-invariant tests in ``test_handle_message.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bob.conversation.thread import _last_seen_at

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
