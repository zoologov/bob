# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the long-gap absence hint (BOB-045 .3).

:func:`~bob.domain.personality.absence.absence_hint` is the pure, deterministic
domain helper behind the "haven't seen you in a while" texture: given the timestamp
of a person's LAST prior turn and ``now`` (+ a threshold), it returns either nothing
or a SHORT neutral note bucketing the gap humanly (hours / "вчера" / "несколько
дней"). It is a CONTEXT HINT for the compose prompt, never a scripted phrase Bob must
say. Under the threshold, with the hint disabled, or with clock skew it returns
``None`` — no line, unchanged behaviour.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bob.domain.personality.absence import absence_hint

_NOW = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)


def test_under_threshold_yields_no_hint() -> None:
    # A 4h gap with an 8h threshold -> still the same conversation, no hint.
    last_seen = _NOW - timedelta(hours=4)

    assert absence_hint(last_seen, _NOW, threshold_hours=8.0) is None


def test_gap_just_under_threshold_yields_no_hint() -> None:
    # Boundary: exactly the threshold does NOT trip (gap must EXCEED it).
    last_seen = _NOW - timedelta(hours=8)

    assert absence_hint(last_seen, _NOW, threshold_hours=8.0) is None


def test_hours_gap_yields_an_hours_hint() -> None:
    # ~14h over an 8h threshold -> an "hours" bucket hint mentioning the count.
    last_seen = _NOW - timedelta(hours=14)

    hint = absence_hint(last_seen, _NOW, threshold_hours=8.0)

    assert hint is not None
    assert "14" in hint
    assert "час" in hint


def test_about_one_day_yields_a_yesterday_hint() -> None:
    # ~1 day -> the "вчера" bucket, not a raw hour count.
    last_seen = _NOW - timedelta(hours=26)

    hint = absence_hint(last_seen, _NOW, threshold_hours=8.0)

    assert hint is not None
    assert "вчера" in hint


def test_multi_day_yields_a_several_days_hint() -> None:
    # Several days -> the coarse "несколько дней" bucket.
    last_seen = _NOW - timedelta(days=4)

    hint = absence_hint(last_seen, _NOW, threshold_hours=8.0)

    assert hint is not None
    assert "несколько дней" in hint


def test_exactly_one_day_is_a_yesterday_hint() -> None:
    # The 24h boundary lands in the "вчера" bucket, not "hours".
    last_seen = _NOW - timedelta(hours=24)

    hint = absence_hint(last_seen, _NOW, threshold_hours=8.0)

    assert hint is not None
    assert "вчера" in hint


def test_two_day_boundary_is_several_days() -> None:
    # The 48h boundary lands in the "несколько дней" bucket.
    last_seen = _NOW - timedelta(hours=48)

    hint = absence_hint(last_seen, _NOW, threshold_hours=8.0)

    assert hint is not None
    assert "несколько дней" in hint


def test_disabled_threshold_yields_no_hint() -> None:
    # threshold 0 (or negative) disables the hint entirely.
    last_seen = _NOW - timedelta(days=10)

    assert absence_hint(last_seen, _NOW, threshold_hours=0.0) is None
    assert absence_hint(last_seen, _NOW, threshold_hours=-1.0) is None


def test_clock_skew_never_hints() -> None:
    # A "last seen" in the future (clock skew) is a non-positive gap -> no hint.
    last_seen = _NOW + timedelta(hours=3)

    assert absence_hint(last_seen, _NOW, threshold_hours=8.0) is None


def test_hours_plural_agreement() -> None:
    # Russian hour-plural agreement on the count (deterministic, grammatical).
    twenty_one = absence_hint(
        _NOW - timedelta(hours=21), _NOW, threshold_hours=1.0
    )
    twenty_two = absence_hint(
        _NOW - timedelta(hours=22), _NOW, threshold_hours=1.0
    )
    eleven = absence_hint(_NOW - timedelta(hours=11), _NOW, threshold_hours=1.0)
    sixteen = absence_hint(_NOW - timedelta(hours=16), _NOW, threshold_hours=1.0)

    assert twenty_one is not None
    assert "21 час" in twenty_one
    assert twenty_two is not None
    assert "22 часа" in twenty_two
    assert eleven is not None  # teen -> "часов" despite ending in 1
    assert "11 часов" in eleven
    assert sixteen is not None  # last digit 6 -> "часов"
    assert "16 часов" in sixteen


def test_deterministic() -> None:
    # Same inputs -> same output, every call (no I/O, no randomness).
    last_seen = _NOW - timedelta(hours=14)

    first = absence_hint(last_seen, _NOW, threshold_hours=8.0)
    second = absence_hint(last_seen, _NOW, threshold_hours=8.0)

    assert first == second
