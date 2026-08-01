# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure roster domain core — новизна по времени + отбор состава (BOB-080).

:func:`is_newcomer` is strictly time-based (INV-3): someone is "new" purely because
Bob met them within ``newcomer_days``, never by authz-kind. :func:`build_roster`
turns the accumulated first impressions into a deterministic, owner-excluded roster
(DESC by first-seen, capped, name from ``display_name`` or parsed from the note). No
I/O, no clock of its own (``now`` is a parameter) — TDD + mutation target.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bob.social.first_impression import FirstImpression
from bob.social.roster import RosterMember, build_roster, is_newcomer

_NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
_NEWCOMER_DAYS = 7.0


def _impression(
    sender_id: int,
    *,
    days_ago: float,
    note: str = "кто-то — уже виделись.",
    display_name: str | None = None,
) -> FirstImpression:
    return FirstImpression(
        sender_id=sender_id,
        first_seen_at=_NOW - timedelta(days=days_ago),
        note=note,
        display_name=display_name,
    )


# --- is_newcomer ---------------------------------------------------------------


def test_is_newcomer_true_within_window() -> None:
    seen = _NOW - timedelta(days=2)

    assert is_newcomer(seen, _NOW, newcomer_days=_NEWCOMER_DAYS) is True


def test_is_newcomer_false_beyond_window() -> None:
    seen = _NOW - timedelta(days=10)

    assert is_newcomer(seen, _NOW, newcomer_days=_NEWCOMER_DAYS) is False


def test_is_newcomer_inclusive_at_exact_threshold() -> None:
    # Exactly newcomer_days old is STILL a newcomer (<= boundary is inclusive).
    seen = _NOW - timedelta(days=_NEWCOMER_DAYS)

    assert is_newcomer(seen, _NOW, newcomer_days=_NEWCOMER_DAYS) is True


def test_is_newcomer_just_beyond_threshold_is_false() -> None:
    seen = _NOW - timedelta(days=_NEWCOMER_DAYS, seconds=1)

    assert is_newcomer(seen, _NOW, newcomer_days=_NEWCOMER_DAYS) is False


def test_is_newcomer_handles_naive_first_seen_as_utc() -> None:
    # A legacy naive stamp is treated as UTC rather than raising on the subtraction.
    naive = (_NOW - timedelta(days=1)).replace(tzinfo=None)

    assert is_newcomer(naive, _NOW, newcomer_days=_NEWCOMER_DAYS) is True


# --- build_roster --------------------------------------------------------------


def test_build_roster_excludes_owner_and_self() -> None:
    impressions = [
        _impression(1, days_ago=1, display_name="Лиля"),
        _impression(2, days_ago=2, display_name="Паша"),
        _impression(99, days_ago=1, display_name="Владелец"),
    ]

    roster = build_roster(
        impressions,
        _NOW,
        newcomer_days=_NEWCOMER_DAYS,
        exclude_ids=frozenset({99}),
        limit=6,
    )

    assert [m.sender_id for m in roster] == [1, 2]


def test_build_roster_sorts_by_first_seen_desc() -> None:
    impressions = [
        _impression(1, days_ago=5, display_name="Старый"),
        _impression(2, days_ago=1, display_name="Свежий"),
        _impression(3, days_ago=3, display_name="Средний"),
    ]

    roster = build_roster(
        impressions,
        _NOW,
        newcomer_days=_NEWCOMER_DAYS,
        exclude_ids=frozenset(),
        limit=6,
    )

    assert [m.sender_id for m in roster] == [2, 3, 1]


def test_build_roster_caps_at_limit() -> None:
    impressions = [_impression(i, days_ago=i) for i in range(1, 6)]

    roster = build_roster(
        impressions,
        _NOW,
        newcomer_days=_NEWCOMER_DAYS,
        exclude_ids=frozenset(),
        limit=2,
    )

    # Kept the two most-recent (smallest days_ago) after the DESC sort.
    assert [m.sender_id for m in roster] == [1, 2]


def test_build_roster_marks_newcomers_by_time() -> None:
    impressions = [
        _impression(1, days_ago=2, display_name="Новичок"),
        _impression(2, days_ago=30, display_name="Старожил"),
    ]

    roster = build_roster(
        impressions,
        _NOW,
        newcomer_days=_NEWCOMER_DAYS,
        exclude_ids=frozenset(),
        limit=6,
    )

    by_id = {m.sender_id: m for m in roster}
    assert by_id[1].is_newcomer is True
    assert by_id[2].is_newcomer is False


def test_build_roster_empty_input_yields_empty() -> None:
    assert (
        build_roster(
            [],
            _NOW,
            newcomer_days=_NEWCOMER_DAYS,
            exclude_ids=frozenset(),
            limit=6,
        )
        == ()
    )


def test_build_roster_name_from_display_name() -> None:
    impressions = [_impression(1, days_ago=1, display_name="Лиля")]

    roster = build_roster(
        impressions,
        _NOW,
        newcomer_days=_NEWCOMER_DAYS,
        exclude_ids=frozenset(),
        limit=6,
    )

    assert roster[0].name == "Лиля"


def test_build_roster_name_parsed_from_note_when_display_name_absent() -> None:
    # Legacy row: no display_name; the name is the head of the "{name} — …" note.
    impressions = [
        _impression(1, days_ago=1, note="Паша — кто-то из знакомых, уже виделись."),
    ]

    roster = build_roster(
        impressions,
        _NOW,
        newcomer_days=_NEWCOMER_DAYS,
        exclude_ids=frozenset(),
        limit=6,
    )

    assert roster[0].name == "Паша"


def test_build_roster_returns_roster_members() -> None:
    impressions = [_impression(1, days_ago=1, display_name="Лиля")]

    roster = build_roster(
        impressions,
        _NOW,
        newcomer_days=_NEWCOMER_DAYS,
        exclude_ids=frozenset(),
        limit=6,
    )

    assert isinstance(roster, tuple)
    assert isinstance(roster[0], RosterMember)
    assert roster[0].first_seen_at == _NOW - timedelta(days=1)
