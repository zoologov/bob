# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ShareOfVoicePolicy — the soft ambient ceiling (focus bypass, no mute)."""

from __future__ import annotations

import pytest

from bob.presence.outgoing_activity import OutgoingActivity
from bob.presence.share_of_voice import ShareOfVoicePolicy


def _policy() -> ShareOfVoicePolicy:
    return ShareOfVoicePolicy()


def test_focused_always_full_even_when_dominating() -> None:
    # Arrange: Bob has taken the whole room — but this message is a DIRECT address.
    policy = _policy()
    dominating = OutgoingActivity(bob_sent=10, total_seen=10, distinct_senders=3)

    # Act
    multiplier = policy.damping(dominating, focused=True)

    # Assert: INV-1 — a focused message is NEVER throttled.
    assert multiplier == 1.0


def test_under_fair_share_is_not_damped() -> None:
    # Arrange: with 3 distinct senders the fair target is 1/4 = 0.25; Bob is at 0.1.
    policy = _policy()
    quiet = OutgoingActivity(bob_sent=1, total_seen=10, distinct_senders=3)

    # Act
    multiplier = policy.damping(quiet, focused=False)

    # Assert: at or under fair share Bob barges freely.
    assert multiplier == 1.0


def test_over_fair_share_is_damped_below_one() -> None:
    # Arrange: fair target 0.25, Bob at 0.6 — well over his share.
    policy = _policy()
    loud = OutgoingActivity(bob_sent=6, total_seen=10, distinct_senders=3)

    # Act
    multiplier = policy.damping(loud, focused=False)

    # Assert: dampened.
    assert 0.0 < multiplier < 1.0


def test_more_dominance_damps_more() -> None:
    # Arrange: same fair target, increasing share.
    policy = _policy()
    over = OutgoingActivity(bob_sent=4, total_seen=10, distinct_senders=3)
    way_over = OutgoingActivity(bob_sent=8, total_seen=10, distinct_senders=3)

    # Act
    mild = policy.damping(over, focused=False)
    strong = policy.damping(way_over, focused=False)

    # Assert: monotonic — more airtime hogged ⇒ stronger damping.
    assert strong < mild


def test_never_fully_mutes_even_at_total_dominance() -> None:
    # Arrange: Bob spoke into every single turn.
    policy = _policy()
    total = OutgoingActivity(bob_sent=10, total_seen=10, distinct_senders=3)

    # Act
    multiplier = policy.damping(total, focused=False)

    # Assert: INV-3 — a nudge, never a hard mute; stays strictly above zero.
    assert multiplier > 0.0


def test_target_widens_with_more_participants() -> None:
    # Arrange: same share (0.4) but a busier room tolerates less of Bob.
    policy = _policy()
    small_room = OutgoingActivity(bob_sent=4, total_seen=10, distinct_senders=1)
    big_room = OutgoingActivity(bob_sent=4, total_seen=10, distinct_senders=5)

    # Act
    small = policy.damping(small_room, focused=False)
    big = policy.damping(big_room, focused=False)

    # Assert: in a 2-person room a 0.4 share is fair (no damping); in a 6-person
    # room the fair target is ~1/6, so 0.4 is over-share and gets damped.
    assert small == 1.0
    assert big < 1.0


def test_damping_curve_has_the_expected_shape_at_a_known_point() -> None:
    # Arrange: default config (floor 0.05, steepness 2.0), fair target 0.25, share 0.6.
    policy = _policy()
    over = OutgoingActivity(bob_sent=6, total_seen=10, distinct_senders=3)

    # Act
    multiplier = policy.damping(over, focused=False)

    # Assert: pins the exact damping value — excess = 0.35/0.75, decay = (1-excess)**2,
    # so the target formula, the normalisation and the floor blend are all exercised.
    assert multiplier == pytest.approx(0.3202, abs=0.005)


def test_mid_share_is_damped_at_three_senders() -> None:
    # Arrange: with 3 senders the fair target is 0.25; a 0.4 share is over it.
    policy = _policy()
    mid = OutgoingActivity(bob_sent=4, total_seen=10, distinct_senders=3)

    # Act / Assert: real target 0.25 damps 0.4 (a doubled target would not).
    assert policy.damping(mid, focused=False) < 1.0


def test_focus_bypass_beats_dominance_boundary() -> None:
    # Arrange: exactly at total dominance, focused wins regardless.
    policy = _policy()
    activity = OutgoingActivity(bob_sent=9, total_seen=10, distinct_senders=2)

    # Act / Assert
    assert policy.damping(activity, focused=True) == 1.0
    assert policy.damping(activity, focused=False) < 1.0
