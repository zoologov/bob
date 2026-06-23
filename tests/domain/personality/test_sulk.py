# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for Sulk — Bob's pure обида state (BOB-014 .2b).

Bob enters обида only when the OWNER relationship sits critically low for a
SUSTAINED run (not one bad message, not casual мат), is cold-but-still-Bob while
sulking, and is GUARANTEED to come out: intensity decays to zero by time alone
(warmth accelerates it), so there is never a permanent lock-out. Memory/soul are
never touched here — this is just an affect state. All transitions are pure and
deterministic (elapsed time + signals passed in).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bob.domain.personality.sulk import (
    SulkConfig,
    SulkState,
    observe_relationship,
    recover,
)

_NOW = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)
# A warmth comfortably below the default critical threshold.
_LOW_WARMTH = -0.6
# A warmth comfortably above it (a healthy relationship).
_OK_WARMTH = 0.3


def test_fresh_state_is_not_sulking() -> None:
    # Arrange / Act
    state = SulkState()

    # Assert: a fresh Bob is not обижен, with no intensity and no streak.
    assert state.active is False
    assert state.intensity == 0.0
    assert state.low_streak == 0
    assert state.announced is False


def test_one_bad_message_does_not_enter_sulk() -> None:
    # Arrange: a single critically-low observation (one bad message).
    cfg = SulkConfig(sustain_count=3)

    # Act
    state = observe_relationship(
        SulkState(), owner_warmth=_LOW_WARMTH, hostile=False, now=_NOW, config=cfg
    )

    # Assert: a single dip never enters обида — it needs sustaining.
    assert state.active is False
    assert state.low_streak == 1


def test_sustained_critical_drop_enters_sulk() -> None:
    # Arrange
    cfg = SulkConfig(sustain_count=3)
    state = SulkState()

    # Act: three consecutive critically-low observations.
    for _ in range(3):
        state = observe_relationship(
            state, owner_warmth=_LOW_WARMTH, hostile=False, now=_NOW, config=cfg
        )

    # Assert: sustained → обида, with intensity and the entry stamp.
    assert state.active is True
    assert state.intensity > 0.0
    assert state.since == _NOW


def test_a_warm_message_resets_the_low_streak() -> None:
    # Arrange: two low observations build a streak.
    cfg = SulkConfig(sustain_count=3)
    state = SulkState()
    for _ in range(2):
        state = observe_relationship(
            state, owner_warmth=_LOW_WARMTH, hostile=False, now=_NOW, config=cfg
        )

    # Act: a healthy turn breaks the run.
    state = observe_relationship(
        state, owner_warmth=_OK_WARMTH, hostile=False, now=_NOW, config=cfg
    )

    # Assert: the streak resets, so обида never builds from intermittent dips.
    assert state.active is False
    assert state.low_streak == 0


def test_directed_hostility_drives_the_streak_even_when_warmth_ok() -> None:
    # Arrange: warmth is fine, but the turn carries DIRECTED hostility.
    cfg = SulkConfig(sustain_count=3)
    state = SulkState()

    # Act
    for _ in range(3):
        state = observe_relationship(
            state, owner_warmth=_OK_WARMTH, hostile=True, now=_NOW, config=cfg
        )

    # Assert: sustained directed hostility enters обида (it reacts to hostility,
    # not to a low number alone).
    assert state.active is True


def test_observe_is_idempotent_once_sulking() -> None:
    # Arrange: already обижен.
    cfg = SulkConfig(sustain_count=1)
    state = observe_relationship(
        SulkState(), owner_warmth=_LOW_WARMTH, hostile=False, now=_NOW, config=cfg
    )
    assert state.active is True
    entered_at = state.since

    # Act: another low observation while already sulking.
    again = observe_relationship(
        state, owner_warmth=_LOW_WARMTH, hostile=False, now=_NOW, config=cfg
    )

    # Assert: it does not re-stamp the entry nor inflate past the cap — stable.
    assert again.active is True
    assert again.since == entered_at
    assert again.intensity <= 1.0


def test_recovery_decays_to_exit_by_time_alone() -> None:
    # Arrange: обижен with full intensity, NO warmth offered.
    cfg = SulkConfig(decay_per_second=0.001, exit_intensity=0.05)
    state = SulkState(active=True, intensity=1.0, since=_NOW, announced=True)

    # Act: a very long quiet stretch with zero warmth.
    state = recover(state, elapsed_seconds=10_000.0, warmth_delta=0.0, config=cfg)

    # Assert: GUARANTEED exit — intensity decays to zero by time alone, so Bob
    # always отходит even if the owner never warms up. No permanent lock-out.
    assert state.active is False
    assert state.intensity == 0.0


def test_recovery_is_faster_with_warmth() -> None:
    # Arrange: identical обида state, recovered over the same short gap.
    cfg = SulkConfig(decay_per_second=0.0001, warmth_decay_bonus=0.5)
    base = SulkState(active=True, intensity=1.0, since=_NOW, announced=True)

    # Act
    cold = recover(base, elapsed_seconds=100.0, warmth_delta=0.0, config=cfg)
    warm = recover(base, elapsed_seconds=100.0, warmth_delta=0.4, config=cfg)

    # Assert: тёплые сообщения accelerate the recovery (warm intensity is lower).
    assert warm.intensity < cold.intensity


def test_recovery_is_idempotent_when_not_sulking() -> None:
    # Arrange: not обижен.
    state = SulkState()

    # Act: a recovery tick on a non-sulking state.
    out = recover(state, elapsed_seconds=100.0, warmth_delta=0.0)

    # Assert: a no-op — recovery never "sticks" or reactivates обида.
    assert out.active is False
    assert out.intensity == 0.0


def test_recovery_clears_the_announced_flag_on_exit() -> None:
    # Arrange: обижен and already announced once.
    cfg = SulkConfig(decay_per_second=1.0, exit_intensity=0.05)
    state = SulkState(active=True, intensity=0.1, since=_NOW, announced=True)

    # Act: enough time to fall below the exit threshold.
    state = recover(state, elapsed_seconds=1.0, warmth_delta=0.0, config=cfg)

    # Assert: on exit the one-shot announce flag is cleared so the NEXT entry
    # announces afresh.
    assert state.active is False
    assert state.announced is False


def test_negative_elapsed_is_rejected() -> None:
    # Arrange / Act / Assert: time cannot run backwards.
    with pytest.raises(ValueError, match="non-negative"):
        recover(SulkState(active=True, intensity=0.5), elapsed_seconds=-1.0)
