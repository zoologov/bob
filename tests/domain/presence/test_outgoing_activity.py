# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for OutgoingActivity — the rolling per-chat share-of-voice window."""

from __future__ import annotations

import pytest

from bob.presence.outgoing_activity import OutgoingActivity


def test_share_is_sent_over_seen() -> None:
    # Arrange: Bob spoke into 2 of 8 seen turns.
    activity = OutgoingActivity(bob_sent=2, total_seen=8, distinct_senders=3)

    # Act / Assert
    assert activity.share == pytest.approx(0.25)


def test_empty_window_has_zero_share() -> None:
    # Arrange: a fresh chat Bob has seen nothing in.
    activity = OutgoingActivity(bob_sent=0, total_seen=0)

    # Act / Assert: zero, not a division error — a fresh chat never trips the ceiling.
    assert activity.share == 0.0


def test_dominated_window_has_full_share() -> None:
    # Arrange: Bob spoke into every turn.
    activity = OutgoingActivity(bob_sent=5, total_seen=5, distinct_senders=1)

    # Act / Assert
    assert activity.share == pytest.approx(1.0)


def test_rejects_sent_exceeding_seen() -> None:
    # Arrange / Act / Assert: Bob cannot have spoken more than he saw.
    with pytest.raises(ValueError, match="cannot exceed"):
        OutgoingActivity(bob_sent=3, total_seen=2)


@pytest.mark.parametrize(
    ("bob_sent", "total_seen", "distinct"),
    [(-1, 0, 0), (0, -1, 0), (0, 0, -1)],
)
def test_rejects_negative_counts(bob_sent: int, total_seen: int, distinct: int) -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="non-negative"):
        OutgoingActivity(
            bob_sent=bob_sent, total_seen=total_seen, distinct_senders=distinct
        )
