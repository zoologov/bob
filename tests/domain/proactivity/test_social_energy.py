# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for SocialEnergy — a pure [0, 1] reservoir with elapsed-time transitions."""

from __future__ import annotations

import pytest

from bob.proactivity.social_energy import SocialEnergy


def test_level_must_be_within_unit_interval() -> None:
    # Arrange / Act / Assert: energy is a [0, 1] reservoir.
    with pytest.raises(ValueError, match="social energy"):
        SocialEnergy(1.5)
    with pytest.raises(ValueError, match="social energy"):
        SocialEnergy(-0.1)


def test_recover_grows_with_elapsed_silence() -> None:
    # Arrange: a depleted reservoir.
    energy = SocialEnergy(0.2)

    # Act: recover over an hour of silence.
    recovered = energy.recover(elapsed_seconds=3600.0)

    # Assert: energy rose toward the cap.
    assert recovered.level > energy.level


def test_recover_is_monotonic_in_elapsed_time() -> None:
    # Arrange
    energy = SocialEnergy(0.0)

    # Act: longer silence recovers at least as much.
    short = energy.recover(elapsed_seconds=600.0)
    long = energy.recover(elapsed_seconds=7200.0)

    # Assert
    assert long.level >= short.level


def test_recover_saturates_at_full() -> None:
    # Arrange: an already-high reservoir over a very long silence.
    energy = SocialEnergy(0.9)

    # Act
    recovered = energy.recover(elapsed_seconds=10_000_000.0)

    # Assert: never overflows 1.0.
    assert recovered.level == pytest.approx(1.0)


def test_recover_rejects_negative_elapsed() -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="elapsed"):
        SocialEnergy(0.5).recover(elapsed_seconds=-1.0)


def test_spend_lowers_energy() -> None:
    # Arrange: a full reservoir.
    energy = SocialEnergy(1.0)

    # Act: Bob speaks once.
    after = energy.spend()

    # Assert
    assert after.level < energy.level


def test_spend_never_goes_below_zero() -> None:
    # Arrange: an almost-empty reservoir.
    energy = SocialEnergy(0.01)

    # Act
    after = energy.spend()

    # Assert: saturates at the floor.
    assert after.level == pytest.approx(0.0)


def test_owner_reply_partially_restores() -> None:
    # Arrange: a half-spent reservoir.
    energy = SocialEnergy(0.4)

    # Act: the owner replies.
    restored = energy.replenish_from_reply()

    # Assert: a partial bump, capped at 1.0.
    assert restored.level > energy.level
    assert restored.level <= 1.0


def test_owner_reply_restore_saturates() -> None:
    # Arrange: an already-high reservoir.
    energy = SocialEnergy(0.95)

    # Act
    restored = energy.replenish_from_reply()

    # Assert
    assert restored.level == pytest.approx(1.0)


def test_transitions_are_pure() -> None:
    # Arrange
    energy = SocialEnergy(0.5)

    # Act
    energy.spend()
    energy.recover(elapsed_seconds=100.0)
    energy.replenish_from_reply()

    # Assert: the original instance is untouched (frozen value object).
    assert energy.level == pytest.approx(0.5)
