# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for NaturalDelayPolicy — the human floor under Bob's reply speed."""

from __future__ import annotations

import pytest

from bob.presence.natural_delay import NaturalDelayPolicy


def _policy() -> NaturalDelayPolicy:
    return NaturalDelayPolicy()


def test_short_reply_still_has_a_human_floor() -> None:
    # Arrange: a tiny "ок" reply.
    policy = _policy()

    # Act
    floor = policy.floor_seconds(char_len=2, complexity=0.0, urgency=0.0)

    # Assert: a real person does not fire back in milliseconds — floor > 1s.
    assert floor > 1.0


def test_longer_reply_floors_longer() -> None:
    # Arrange
    policy = _policy()

    # Act
    short = policy.floor_seconds(char_len=10, complexity=0.0, urgency=0.0)
    long = policy.floor_seconds(char_len=400, complexity=0.0, urgency=0.0)

    # Assert: more to "type" ⇒ a longer floor.
    assert long > short


def test_complexity_stretches_the_floor() -> None:
    # Arrange
    policy = _policy()

    # Act
    simple = policy.floor_seconds(char_len=50, complexity=0.0, urgency=0.0)
    complex_ = policy.floor_seconds(char_len=50, complexity=1.0, urgency=0.0)

    # Assert
    assert complex_ > simple


def test_urgency_shortens_the_floor() -> None:
    # Arrange: same reply, but one is a demanded, time-critical answer.
    policy = _policy()

    # Act
    calm = policy.floor_seconds(char_len=80, complexity=0.3, urgency=0.0)
    urgent = policy.floor_seconds(char_len=80, complexity=0.3, urgency=1.0)

    # Assert: urgency relieves the floor — a demanded answer comes quicker.
    assert urgent < calm


def test_floor_is_capped_for_huge_drafts() -> None:
    # Arrange: an enormous draft.
    policy = _policy()

    # Act
    floor = policy.floor_seconds(char_len=100_000, complexity=1.0, urgency=0.0)

    # Assert: never an absurd wait — capped at the configured max.
    assert floor <= policy.config.delay_max_seconds


def test_floor_is_non_negative() -> None:
    # Arrange: maximum urgency on a trivial reply.
    policy = _policy()

    # Act
    floor = policy.floor_seconds(char_len=0, complexity=0.0, urgency=1.0)

    # Assert
    assert floor >= 0.0


def test_out_of_range_complexity_and_urgency_are_clamped() -> None:
    # Arrange: absurd inputs must not blow up the floor.
    policy = _policy()

    # Act: over-1.0 complexity clamps to the same as exactly 1.0.
    at_one = policy.floor_seconds(char_len=50, complexity=1.0, urgency=0.0)
    over_one = policy.floor_seconds(char_len=50, complexity=5.0, urgency=0.0)

    # Assert
    assert over_one == pytest.approx(at_one)


def test_floor_value_is_pinned_at_a_known_point() -> None:
    # Arrange: default config — base 1.5, 0.03/char, 4.0*complexity, no urgency.
    policy = _policy()

    # Act: 50 chars + full complexity ⇒ 1.5 + 50*0.03 + 1.0*4.0 = 7.0s.
    floor = policy.floor_seconds(char_len=50, complexity=1.0, urgency=0.0)

    # Assert: pins the additive contribution of complexity (a divide would give 3.25s).
    assert floor == pytest.approx(7.0, abs=0.01)


def test_rejects_negative_char_len() -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="char_len"):
        _policy().floor_seconds(char_len=-1, complexity=0.0, urgency=0.0)
