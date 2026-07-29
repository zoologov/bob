# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ReactionBudget — the separate, gentle budget for Bob's likes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bob.presence.reaction_budget import ReactionBudget

_NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=UTC)


def _budget() -> ReactionBudget:
    return ReactionBudget()


def test_notable_message_with_no_history_is_allowed() -> None:
    # Arrange: a genuinely notable message, Bob has liked nothing yet.
    budget = _budget()

    # Act
    allowed = budget.allows([], quality=0.9, now=_NOW)

    # Assert
    assert allowed is True


def test_low_quality_message_is_refused() -> None:
    # Arrange: a bland message — not worth a like.
    budget = _budget()

    # Act
    allowed = budget.allows([], quality=0.1, now=_NOW)

    # Assert: quality gate — a bot that likes everything reads as scripted.
    assert allowed is False


def test_second_like_within_the_gap_is_refused() -> None:
    # Arrange: Bob liked something 30s ago (gap default is 90s).
    budget = _budget()
    recent = [_NOW - timedelta(seconds=30)]

    # Act
    allowed = budget.allows(recent, quality=0.95, now=_NOW)

    # Assert: one reaction per series — not a burst.
    assert allowed is False


def test_like_allowed_once_the_gap_has_passed() -> None:
    # Arrange: Bob's last like was well beyond the gap.
    budget = _budget()
    old = [_NOW - timedelta(seconds=300)]

    # Act
    allowed = budget.allows(old, quality=0.95, now=_NOW)

    # Assert
    assert allowed is True


def test_quality_exactly_at_threshold_is_allowed() -> None:
    # Arrange: quality lands exactly on the gate (default threshold 0.6).
    budget = _budget()

    # Act: `quality >= threshold` admits the boundary case.
    allowed = budget.allows([], quality=0.6, now=_NOW)

    # Assert
    assert allowed is True


def test_like_exactly_at_the_gap_is_allowed() -> None:
    # Arrange: Bob's last like was exactly the min gap ago (default 90s).
    budget = _budget()
    at_gap = [_NOW - timedelta(seconds=90)]

    # Act: `elapsed >= min_gap` admits the boundary case.
    allowed = budget.allows(at_gap, quality=0.95, now=_NOW)

    # Assert
    assert allowed is True


def test_gap_is_measured_from_the_most_recent_like() -> None:
    # Arrange: an old like AND a fresh one — the fresh one gates.
    budget = _budget()
    history = [_NOW - timedelta(seconds=1000), _NOW - timedelta(seconds=10)]

    # Act
    allowed = budget.allows(history, quality=0.95, now=_NOW)

    # Assert: the most-recent like (10s ago) is inside the gap ⇒ refused.
    assert allowed is False
